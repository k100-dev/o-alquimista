"""Persistência SQLite versionada da memória de campanhas."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from .analysis import (
    RecommendationContext,
    build_campaign_analysis,
    build_timeline_entry,
    detect_milestones,
    generate_recommendations,
    timeline_sort_key,
)
from .errors import (
    RecordNotFoundError,
    UnsupportedDatabaseVersionError,
)
from .evidence import deterministic_id, snapshot_evidence
from .identity import resolve_campaign_identity
from .json_codec import dumps as json_dumps
from .json_codec import loads as json_loads
from .json_codec import loads_snapshot
from .memory_models import (
    ArchiveFingerprint,
    CampaignAnalysis,
    CampaignIdentity,
    DetectedMilestone,
    Evidence,
    StrategicRecommendation,
)
from .models import Milestone, NormalizedSnapshot, Recommendation
from .provenance import (
    validate_provenance_payload,
    validate_snapshot_provenance,
)

DATABASE_VERSION = 3

BASE_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    source_hint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS imports (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    source_archive TEXT NOT NULL,
    archive_sha256 TEXT NOT NULL,
    save_root TEXT NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    import_id TEXT NOT NULL UNIQUE REFERENCES imports(id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS milestones (
    id TEXT PRIMARY KEY,
    snapshot_id TEXT REFERENCES snapshots(id) ON DELETE CASCADE,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendations (
    id TEXT PRIMARY KEY,
    snapshot_id TEXT REFERENCES snapshots(id) ON DELETE CASCADE,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS archive_fingerprints (
    id TEXT PRIMARY KEY,
    algorithm TEXT NOT NULL CHECK (algorithm = 'sha256'),
    digest TEXT NOT NULL UNIQUE,
    file_size INTEGER NOT NULL CHECK (file_size >= 0),
    archive_member_count INTEGER NOT NULL CHECK (archive_member_count >= 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS timeline_entries (
    snapshot_id TEXT PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
    import_id TEXT NOT NULL UNIQUE REFERENCES imports(id) ON DELETE CASCADE,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    archive_hash TEXT NOT NULL,
    elapsed_days REAL,
    time_of_day TEXT,
    playtime_seconds REAL,
    progression_total_xp REAL,
    imported_at TEXT NOT NULL,
    chronological_order INTEGER NOT NULL,
    entry_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    category TEXT NOT NULL CHECK (
        category IN ('observed', 'derived', 'inferred', 'unavailable')
    ),
    payload_json TEXT NOT NULL,
    PRIMARY KEY (id, snapshot_id)
);

CREATE TABLE IF NOT EXISTS snapshot_relationships (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    previous_snapshot_id TEXT REFERENCES snapshots(id) ON DELETE CASCADE,
    current_snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    UNIQUE(previous_snapshot_id, current_snapshot_id, relationship_type)
);

CREATE TABLE IF NOT EXISTS campaign_identity_signals (
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    signal_kind TEXT NOT NULL,
    signal_digest TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_path TEXT NOT NULL,
    PRIMARY KEY (campaign_id, signal_kind, signal_digest)
);

CREATE TABLE IF NOT EXISTS campaign_associations (
    id TEXT PRIMARY KEY,
    left_campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    right_campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    association_state TEXT NOT NULL CHECK (
        association_state IN ('candidate', 'explicitly_linked')
    ),
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(left_campaign_id, right_campaign_id)
);

CREATE TABLE IF NOT EXISTS campaign_milestones (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_imports_campaign ON imports(campaign_id);
CREATE INDEX IF NOT EXISTS idx_imports_imported_at ON imports(imported_at);
CREATE INDEX IF NOT EXISTS idx_imports_archive_sha ON imports(archive_sha256);
CREATE INDEX IF NOT EXISTS idx_timeline_campaign_order
    ON timeline_entries(campaign_id, chronological_order);
CREATE INDEX IF NOT EXISTS idx_timeline_game_time
    ON timeline_entries(campaign_id, elapsed_days, playtime_seconds);
CREATE INDEX IF NOT EXISTS idx_evidence_snapshot ON evidence(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_evidence_campaign ON evidence(campaign_id);
CREATE INDEX IF NOT EXISTS idx_relationship_current
    ON snapshot_relationships(current_snapshot_id);
CREATE INDEX IF NOT EXISTS idx_campaign_signal_digest
    ON campaign_identity_signals(signal_kind, signal_digest);
CREATE INDEX IF NOT EXISTS idx_campaign_association_left
    ON campaign_associations(left_campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_association_right
    ON campaign_associations(right_campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_milestone_snapshot
    ON campaign_milestones(snapshot_id);
"""

CAMPAIGN_COLUMNS: dict[str, str] = {
    "resolution_state": "TEXT",
    "identity_strategy": "TEXT",
    "confidence": "TEXT",
    "evidence_json": "TEXT",
    "association_signals_json": "TEXT",
    "explanation": "TEXT",
}

IMPORT_COLUMNS: dict[str, str] = {
    "fingerprint_id": "TEXT REFERENCES archive_fingerprints(id)",
}


@dataclass(frozen=True, slots=True)
class PersistedImport:
    campaign_id: str
    import_id: str
    snapshot_id: str
    deduplicated: bool = False


class AlquimistaDatabase:
    """Repositório transacional, idempotente e sem caminhos absolutos persistidos."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
        except BaseException:
            connection.close()
            raise
        return connection

    @contextmanager
    def _connection(
        self,
        *,
        immediate: bool = False,
    ) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _columns(
        connection: sqlite3.Connection,
        table: str,
    ) -> set[str]:
        return {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }

    @classmethod
    def _add_missing_columns(
        cls,
        connection: sqlite3.Connection,
        table: str,
        columns: dict[str, str],
    ) -> None:
        existing = cls._columns(connection, table)
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
                )

    def initialize(self) -> None:
        with self._connection() as connection:
            current_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if current_version > DATABASE_VERSION:
                raise UnsupportedDatabaseVersionError(
                    "O banco usa uma versão de schema mais nova que esta "
                    f"aplicação (banco={current_version}, suportado={DATABASE_VERSION}); "
                    "use uma versão compatível do O Alquimista."
                )
            connection.executescript(
                f"BEGIN IMMEDIATE;\n{BASE_SCHEMA}\n{MEMORY_SCHEMA}"
            )
            self._add_missing_columns(
                connection,
                "campaigns",
                CAMPAIGN_COLUMNS,
            )
            self._add_missing_columns(
                connection,
                "imports",
                IMPORT_COLUMNS,
            )
            connection.execute(
                """
                UPDATE campaigns
                SET resolution_state = CASE
                    WHEN identity_strategy = 'native_campaign_identifier'
                        AND confidence = 'high' THEN 'resolved'
                    WHEN identity_strategy IS NULL THEN 'unresolved'
                    WHEN identity_strategy = 'archive_scoped_fallback'
                        THEN 'unresolved'
                    ELSE 'candidate'
                END
                WHERE resolution_state IS NULL
                """
            )
            connection.execute(
                """
                UPDATE campaigns SET association_signals_json = '[]'
                WHERE association_signals_json IS NULL
                """
            )
            self._backfill_identity_signals(connection)
            self._migrate_detected_milestones(connection)
            legacy_hashes = connection.execute(
                """
                SELECT archive_sha256, MIN(imported_at) AS imported_at
                FROM imports
                WHERE archive_sha256 IS NOT NULL AND archive_sha256 <> ''
                GROUP BY archive_sha256
                """
            ).fetchall()
            for row in legacy_hashes:
                fingerprint_id = f"archive-sha256-{row['archive_sha256']}"
                connection.execute(
                    """
                    INSERT OR IGNORE INTO archive_fingerprints
                        (id, algorithm, digest, file_size,
                         archive_member_count, created_at)
                    VALUES (?, 'sha256', ?, 0, 0, ?)
                    """,
                    (
                        fingerprint_id,
                        row["archive_sha256"],
                        row["imported_at"],
                    ),
                )
                connection.execute(
                    """
                    UPDATE imports SET fingerprint_id = ?
                    WHERE archive_sha256 = ? AND fingerprint_id IS NULL
                    """,
                    (fingerprint_id, row["archive_sha256"]),
                )
            connection.execute(f"PRAGMA user_version = {DATABASE_VERSION}")

    @classmethod
    def _migrate_detected_milestones(
        cls,
        connection: sqlite3.Connection,
    ) -> None:
        rows = connection.execute(
            """
            SELECT
                m.id,
                m.snapshot_id,
                m.payload_json,
                m.created_at,
                i.campaign_id
            FROM milestones AS m
            JOIN snapshots AS s ON s.id = m.snapshot_id
            JOIN imports AS i ON i.id = s.import_id
            """
        ).fetchall()
        migrated_ids: list[str] = []
        for row in rows:
            try:
                payload = json_loads(row["payload_json"])
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict) or "milestone_id" not in payload:
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO campaign_milestones
                    (id, campaign_id, snapshot_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["campaign_id"],
                    row["snapshot_id"],
                    row["payload_json"],
                    row["created_at"],
                ),
            )
            migrated_ids.append(str(row["id"]))
        connection.executemany(
            "DELETE FROM milestones WHERE id = ?",
            [(milestone_id,) for milestone_id in migrated_ids],
        )

    @classmethod
    def _backfill_identity_signals(
        cls,
        connection: sqlite3.Connection,
    ) -> None:
        rows = connection.execute(
            """
            SELECT id, evidence_json
            FROM campaigns
            WHERE evidence_json IS NOT NULL AND evidence_json <> ''
            """
        ).fetchall()
        for row in rows:
            try:
                evidence_items = json_loads(row["evidence_json"])
            except (TypeError, ValueError):
                continue
            signals: list[dict[str, str]] = []
            for evidence in evidence_items if isinstance(evidence_items, list) else []:
                normalized = (
                    evidence.get("normalized_value")
                    if isinstance(evidence, dict)
                    else None
                )
                if isinstance(normalized, dict):
                    organisation = normalized.get("organisation")
                    if isinstance(organisation, str):
                        signals.append(
                            {
                                "kind": "organisation",
                                "digest": organisation,
                                "source_file": "Game.json",
                                "source_path": "OrganisationName",
                            }
                        )
                    players = normalized.get("players")
                    if isinstance(players, list):
                        signals.extend(
                            {
                                "kind": "player",
                                "digest": digest,
                                "source_file": "Players/*",
                                "source_path": "$directory",
                            }
                            for digest in players
                            if isinstance(digest, str)
                        )
            if not signals:
                continue
            connection.executemany(
                """
                INSERT OR IGNORE INTO campaign_identity_signals
                    (campaign_id, signal_kind, signal_digest,
                     source_file, source_path)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["id"],
                        signal["kind"],
                        signal["digest"],
                        signal["source_file"],
                        signal["source_path"],
                    )
                    for signal in signals
                ],
            )
            connection.execute(
                """
                UPDATE campaigns SET association_signals_json = ?
                WHERE id = ?
                """,
                (cls._json(signals), row["id"]),
            )

    @staticmethod
    def _json(value: Any) -> str:
        return json_dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _ids(fingerprint: ArchiveFingerprint) -> tuple[str, str]:
        return (
            f"import-{fingerprint.digest[:32]}",
            f"snapshot-{fingerprint.digest[:32]}",
        )

    @staticmethod
    def _persist_evidence_rows(
        connection: sqlite3.Connection,
        *,
        snapshot_id: str,
        campaign_id: str,
        evidence: Iterable[Evidence],
    ) -> None:
        evidence_items = tuple(evidence)
        for item in evidence_items:
            validate_provenance_payload(item.to_dict())
        connection.executemany(
            """
            INSERT OR IGNORE INTO evidence
                (id, snapshot_id, campaign_id, category, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    item.evidence_id,
                    snapshot_id,
                    campaign_id,
                    item.category,
                    AlquimistaDatabase._json(item.to_dict()),
                )
                for item in evidence_items
            ],
        )

    @staticmethod
    def _existing_import(
        connection: sqlite3.Connection,
        digest: str,
    ) -> PersistedImport | None:
        row = connection.execute(
            """
            SELECT
                i.id AS import_id,
                i.campaign_id,
                s.id AS snapshot_id
            FROM imports AS i
            JOIN snapshots AS s ON s.import_id = i.id
            WHERE i.archive_sha256 = ?
            ORDER BY i.imported_at, i.id
            LIMIT 1
            """,
            (digest,),
        ).fetchone()
        if row is None:
            return None
        return PersistedImport(
            campaign_id=str(row["campaign_id"]),
            import_id=str(row["import_id"]),
            snapshot_id=str(row["snapshot_id"]),
            deduplicated=True,
        )

    @staticmethod
    def _ensure_campaign(
        connection: sqlite3.Connection,
        identity: CampaignIdentity,
        imported_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO campaigns
                (id, display_name, source_hint, created_at,
                 resolution_state, identity_strategy, confidence,
                 evidence_json, association_signals_json, explanation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identity.campaign_id,
                f"Campanha {identity.campaign_id[-8:]}",
                identity.campaign_id,
                imported_at,
                identity.resolution_state,
                identity.strategy,
                identity.confidence,
                AlquimistaDatabase._json(
                    [item.to_dict() for item in identity.evidence]
                ),
                AlquimistaDatabase._json(
                    [item.to_dict() for item in identity.association_signals]
                ),
                identity.explanation,
            ),
        )

    @classmethod
    def _persist_identity_signals_and_associations(
        cls,
        connection: sqlite3.Connection,
        identity: CampaignIdentity,
        created_at: str,
    ) -> None:
        if not identity.association_signals:
            return
        connection.executemany(
            """
            INSERT OR IGNORE INTO campaign_identity_signals
                (campaign_id, signal_kind, signal_digest,
                 source_file, source_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    identity.campaign_id,
                    signal.kind,
                    signal.digest,
                    signal.source_file,
                    signal.source_path,
                )
                for signal in identity.association_signals
            ],
        )
        matches = connection.execute(
            """
            SELECT DISTINCT other.campaign_id
            FROM campaign_identity_signals AS own
            JOIN campaign_identity_signals AS other
              ON other.signal_kind = own.signal_kind
             AND other.signal_digest = own.signal_digest
            WHERE own.campaign_id = ?
              AND other.campaign_id <> ?
            ORDER BY other.campaign_id
            """,
            (identity.campaign_id, identity.campaign_id),
        ).fetchall()
        for match in matches:
            other_id = str(match["campaign_id"])
            left_id, right_id = sorted((identity.campaign_id, other_id))
            shared = connection.execute(
                """
                SELECT own.signal_kind, own.signal_digest
                FROM campaign_identity_signals AS own
                JOIN campaign_identity_signals AS other
                  ON other.signal_kind = own.signal_kind
                 AND other.signal_digest = own.signal_digest
                WHERE own.campaign_id = ? AND other.campaign_id = ?
                ORDER BY own.signal_kind, own.signal_digest
                """,
                (identity.campaign_id, other_id),
            ).fetchall()
            association_id = deterministic_id(
                "association",
                left_id,
                right_id,
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO campaign_associations
                    (id, left_campaign_id, right_campaign_id,
                     association_state, evidence_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    association_id,
                    left_id,
                    right_id,
                    "candidate",
                    cls._json(
                        {
                            "shared_signals": [
                                {
                                    "kind": row["signal_kind"],
                                    "digest": row["signal_digest"],
                                }
                                for row in shared
                            ],
                            "explanation": (
                                "Sinais fracos coincidem; campanhas não foram unidas."
                            ),
                        }
                    ),
                    created_at,
                ),
            )

    @staticmethod
    def _timeline_rows(
        connection: sqlite3.Connection,
        campaign_id: str,
        *,
        include_imported_at: bool = False,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT entry_json, imported_at
            FROM timeline_entries
            WHERE campaign_id = ?
            """,
            (campaign_id,),
        ).fetchall()
        entries: list[dict[str, Any]] = []
        for row in rows:
            entry = json_loads(row["entry_json"])
            entry["imported_at"] = row["imported_at"]
            entries.append(entry)
        ordered = sorted(entries, key=timeline_sort_key)
        if not include_imported_at:
            for entry in ordered:
                entry.pop("imported_at", None)
        return ordered

    @classmethod
    def _reorder_timeline(
        cls,
        connection: sqlite3.Connection,
        campaign_id: str,
    ) -> list[dict[str, Any]]:
        entries = cls._timeline_rows(
            connection,
            campaign_id,
            include_imported_at=True,
        )
        for order, entry in enumerate(entries, start=1):
            entry["chronological_order"] = order
            stored_entry = dict(entry)
            stored_entry.pop("imported_at", None)
            connection.execute(
                """
                UPDATE timeline_entries
                SET chronological_order = ?, entry_json = ?
                WHERE snapshot_id = ?
                """,
                (order, cls._json(stored_entry), entry["snapshot_id"]),
            )
        return entries

    @classmethod
    def _rebuild_timeline_relationships(
        cls,
        connection: sqlite3.Connection,
        campaign_id: str,
        entries: list[dict[str, Any]],
    ) -> None:
        connection.execute(
            """
            DELETE FROM snapshot_relationships
            WHERE campaign_id = ? AND relationship_type = 'chronological_successor'
            """,
            (campaign_id,),
        )
        for previous, current in zip(entries, entries[1:]):
            relationship_id = (
                f"relationship-{previous['snapshot_id']}-to-{current['snapshot_id']}"
            )
            connection.execute(
                """
                INSERT INTO snapshot_relationships
                    (id, campaign_id, previous_snapshot_id,
                     current_snapshot_id, relationship_type, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    relationship_id,
                    campaign_id,
                    previous["snapshot_id"],
                    current["snapshot_id"],
                    "chronological_successor",
                    cls._json(
                        {
                            "ordering": (
                                "tempo interno, progressão, importação, snapshot_id"
                            )
                        }
                    ),
                ),
            )

    @classmethod
    def _refresh_timeline_milestones(
        cls,
        connection: sqlite3.Connection,
        campaign_id: str,
        entries: list[dict[str, Any]],
    ) -> dict[str, tuple[DetectedMilestone, ...]]:
        detected: dict[str, tuple[DetectedMilestone, ...]] = {}
        historical_snapshots: list[dict[str, Any]] = []
        previous_snapshot_id: str | None = None
        for entry in entries:
            snapshot_id = str(entry["snapshot_id"])
            stale_evidence_ids = [
                str(evidence["evidence_id"])
                for milestone in entry.get("milestones", [])
                if isinstance(milestone, dict)
                for evidence in milestone.get("evidence", [])
                if isinstance(evidence, dict) and evidence.get("evidence_id")
            ]
            connection.executemany(
                "DELETE FROM evidence WHERE id = ? AND snapshot_id = ?",
                [
                    (evidence_id, snapshot_id)
                    for evidence_id in stale_evidence_ids
                ],
            )
            current_snapshot = cls._snapshot_json(connection, snapshot_id)
            milestones = detect_milestones(
                historical_snapshots,
                current_snapshot,
                campaign_id=campaign_id,
                current_snapshot_id=snapshot_id,
                previous_snapshot_id=previous_snapshot_id,
            )
            entry["milestones"] = [
                milestone.to_dict() for milestone in milestones
            ]
            stored_entry = dict(entry)
            stored_entry.pop("imported_at", None)
            connection.execute(
                """
                UPDATE timeline_entries SET entry_json = ?
                WHERE snapshot_id = ?
                """,
                (cls._json(stored_entry), snapshot_id),
            )
            cls._persist_evidence_rows(
                connection,
                snapshot_id=snapshot_id,
                campaign_id=campaign_id,
                evidence=(
                    item
                    for milestone in milestones
                    for item in milestone.evidence
                ),
            )
            detected[snapshot_id] = milestones
            historical_snapshots.append(current_snapshot)
            previous_snapshot_id = snapshot_id
        return detected

    @classmethod
    def _rebuild_campaign_milestones(
        cls,
        connection: sqlite3.Connection,
        campaign_id: str,
        milestones: Iterable[DetectedMilestone],
        created_at: str,
    ) -> None:
        connection.execute(
            "DELETE FROM campaign_milestones WHERE campaign_id = ?",
            (campaign_id,),
        )
        connection.executemany(
            """
            INSERT INTO campaign_milestones
                (id, campaign_id, snapshot_id, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    milestone.milestone_id,
                    campaign_id,
                    milestone.first_seen_snapshot_id,
                    cls._json(milestone.to_dict()),
                    created_at,
                )
                for milestone in milestones
            ],
        )

    @staticmethod
    def _snapshot_json(
        connection: sqlite3.Connection,
        snapshot_id: str,
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT snapshot_json FROM snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"Snapshot não encontrado: {snapshot_id}")
        return loads_snapshot(row["snapshot_json"])

    @classmethod
    def _persist_detected_milestones(
        cls,
        connection: sqlite3.Connection,
        snapshot_id: str,
        milestones: Iterable[DetectedMilestone],
        created_at: str,
    ) -> None:
        connection.executemany(
            """
            INSERT OR IGNORE INTO milestones
                (id, snapshot_id, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    item.milestone_id,
                    snapshot_id,
                    cls._json(item.to_dict()),
                    created_at,
                )
                for item in milestones
            ],
        )

    @classmethod
    def _persist_strategic_recommendations(
        cls,
        connection: sqlite3.Connection,
        snapshot_id: str,
        recommendations: Iterable[StrategicRecommendation],
        created_at: str,
    ) -> None:
        connection.executemany(
            """
            INSERT OR REPLACE INTO recommendations
                (id, snapshot_id, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    item.recommendation_id,
                    snapshot_id,
                    cls._json(item.to_dict()),
                    created_at,
                )
                for item in recommendations
            ],
        )

    def persist_import(
        self,
        snapshot: NormalizedSnapshot,
        fingerprint: ArchiveFingerprint,
        campaign_identity: CampaignIdentity,
    ) -> PersistedImport:
        """Persiste toda a importação atomicamente e deduplica por SHA-256."""
        snapshot_data = snapshot.to_dict()
        validate_snapshot_provenance(snapshot_data)
        validate_provenance_payload(campaign_identity.to_dict())
        self.initialize()
        imported_at = self._now()
        import_id, snapshot_id = self._ids(fingerprint)
        with self._connection(immediate=True) as connection:
            existing = self._existing_import(connection, fingerprint.digest)
            if existing is not None:
                return existing

            connection.execute(
                """
                INSERT INTO archive_fingerprints
                    (id, algorithm, digest, file_size,
                     archive_member_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    fingerprint.fingerprint_id,
                    fingerprint.algorithm,
                    fingerprint.digest,
                    fingerprint.file_size,
                    fingerprint.archive_member_count,
                    imported_at,
                ),
            )
            self._ensure_campaign(connection, campaign_identity, imported_at)
            self._persist_identity_signals_and_associations(
                connection,
                campaign_identity,
                imported_at,
            )
            connection.execute(
                """
                INSERT INTO imports
                    (id, campaign_id, source_archive, archive_sha256,
                     save_root, imported_at, fingerprint_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_id,
                    campaign_identity.campaign_id,
                    snapshot.metadata.source_archive or "export.zip",
                    fingerprint.digest,
                    snapshot.metadata.save_root,
                    imported_at,
                    fingerprint.fingerprint_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO snapshots
                    (id, import_id, schema_version, snapshot_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    import_id,
                    snapshot.metadata.schema_version,
                    self._json(snapshot_data),
                    imported_at,
                ),
            )
            entry = build_timeline_entry(
                snapshot_data,
                snapshot_id=snapshot_id,
                import_id=import_id,
                campaign_id=campaign_identity.campaign_id,
                archive_hash=fingerprint.digest,
            )
            moment = entry.observable_game_moment
            connection.execute(
                """
                INSERT INTO timeline_entries
                    (snapshot_id, import_id, campaign_id, archive_hash,
                     elapsed_days, time_of_day, playtime_seconds,
                     progression_total_xp, imported_at,
                     chronological_order, entry_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    import_id,
                    campaign_identity.campaign_id,
                    fingerprint.digest,
                    moment.get("elapsed_days"),
                    (
                        str(moment["time_of_day"])
                        if moment.get("time_of_day") is not None
                        else None
                    ),
                    moment.get("playtime_seconds"),
                    entry.progression_summary.get("total_xp"),
                    imported_at,
                    0,
                    self._json(entry.to_dict()),
                ),
            )
            timeline = self._reorder_timeline(
                connection,
                campaign_identity.campaign_id,
            )
            self._rebuild_timeline_relationships(
                connection,
                campaign_identity.campaign_id,
                timeline,
            )
            milestones_by_snapshot = self._refresh_timeline_milestones(
                connection,
                campaign_identity.campaign_id,
                timeline,
            )
            self._rebuild_campaign_milestones(
                connection,
                campaign_identity.campaign_id,
                (
                    milestone
                    for milestones in milestones_by_snapshot.values()
                    for milestone in milestones
                ),
                imported_at,
            )

            evidence = (
                *campaign_identity.evidence,
                *snapshot_evidence(snapshot_data),
            )
            self._persist_evidence_rows(
                connection,
                snapshot_id=snapshot_id,
                campaign_id=campaign_identity.campaign_id,
                evidence=evidence,
            )
        return PersistedImport(
            campaign_id=campaign_identity.campaign_id,
            import_id=import_id,
            snapshot_id=snapshot_id,
            deduplicated=False,
        )

    def persist_snapshot(
        self,
        snapshot: NormalizedSnapshot,
        *,
        campaign_name: str,
    ) -> PersistedImport:
        """API retrocompatível; `campaign_name` não participa da identidade."""
        del campaign_name
        digest = snapshot.metadata.archive_sha256
        if digest is None:
            raise ValueError("A persistência de import requer origem em arquivo ZIP.")
        fingerprint = ArchiveFingerprint(
            algorithm="sha256",
            digest=digest,
            file_size=0,
            archive_member_count=0,
        )
        identity = resolve_campaign_identity(snapshot, fingerprint)
        return self.persist_import(snapshot, fingerprint, identity)

    def persist_milestones(
        self,
        snapshot_id: str,
        milestones: Iterable[Milestone],
        *,
        created_at: str,
    ) -> None:
        self.initialize()
        rows = [
            (
                milestone.id,
                snapshot_id,
                self._json(asdict(milestone)),
                created_at,
            )
            for milestone in milestones
        ]
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO milestones
                    (id, snapshot_id, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )

    def persist_recommendations(
        self,
        snapshot_id: str,
        recommendations: Iterable[Recommendation],
        *,
        created_at: str,
    ) -> None:
        self.initialize()
        rows = [
            (
                recommendation.id,
                snapshot_id,
                self._json(asdict(recommendation)),
                created_at,
            )
            for recommendation in recommendations
        ]
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO recommendations
                    (id, snapshot_id, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )

    def history(self) -> list[dict[str, Any]]:
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    i.id AS import_id,
                    i.imported_at,
                    i.source_archive,
                    i.archive_sha256,
                    i.save_root,
                    i.campaign_id,
                    c.display_name AS campaign,
                    s.id AS snapshot_id,
                    s.schema_version
                FROM imports AS i
                JOIN campaigns AS c ON c.id = i.campaign_id
                JOIN snapshots AS s ON s.import_id = i.id
                ORDER BY i.imported_at DESC, i.id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def campaign_list(self) -> list[dict[str, Any]]:
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    c.id AS campaign_id,
                    c.display_name,
                    c.resolution_state,
                    c.identity_strategy,
                    c.confidence,
                    c.explanation,
                    COUNT(DISTINCT i.id) AS import_count,
                    COUNT(DISTINCT s.id) AS snapshot_count,
                    (
                        SELECT COUNT(*)
                        FROM campaign_associations AS a
                        WHERE a.left_campaign_id = c.id
                           OR a.right_campaign_id = c.id
                    ) AS candidate_association_count
                FROM campaigns AS c
                LEFT JOIN imports AS i ON i.campaign_id = c.id
                LEFT JOIN snapshots AS s ON s.import_id = i.id
                GROUP BY c.id
                ORDER BY c.id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def campaign_associations(self, campaign_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            if exists is None:
                raise RecordNotFoundError(f"Campanha não encontrada: {campaign_id}")
            rows = connection.execute(
                """
                SELECT
                    a.id AS association_id,
                    a.association_state,
                    CASE
                        WHEN a.left_campaign_id = ? THEN a.right_campaign_id
                        ELSE a.left_campaign_id
                    END AS candidate_campaign_id,
                    a.evidence_json
                FROM campaign_associations AS a
                WHERE a.left_campaign_id = ? OR a.right_campaign_id = ?
                ORDER BY candidate_campaign_id, association_id
                """,
                (campaign_id, campaign_id, campaign_id),
            ).fetchall()
        associations: list[dict[str, Any]] = []
        for row in rows:
            association = dict(row)
            association["evidence"] = json_loads(
                association.pop("evidence_json")
            )
            associations.append(association)
        return associations

    def campaign_history(self, campaign_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
            if exists is None:
                raise RecordNotFoundError(f"Campanha não encontrada: {campaign_id}")
            return self._timeline_rows(connection, campaign_id)

    def snapshot_record(self, snapshot_id: str) -> dict[str, Any]:
        self.initialize()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT
                    s.id AS snapshot_id,
                    s.snapshot_json,
                    i.id AS import_id,
                    i.campaign_id,
                    i.archive_sha256
                FROM snapshots AS s
                JOIN imports AS i ON i.id = s.import_id
                WHERE s.id = ?
                """,
                (snapshot_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"Snapshot não encontrado: {snapshot_id}")
        return {
            "snapshot_id": row["snapshot_id"],
            "snapshot": loads_snapshot(row["snapshot_json"]),
            "import_id": row["import_id"],
            "campaign_id": row["campaign_id"],
            "archive_hash": row["archive_sha256"],
        }

    def campaign_analysis(self, campaign_id: str) -> CampaignAnalysis:
        timeline = self.campaign_history(campaign_id)
        snapshots = [
            self.snapshot_record(entry["snapshot_id"])["snapshot"]
            for entry in timeline
        ]
        milestones: list[DetectedMilestone] = []
        historical_snapshots: list[dict[str, Any]] = []
        for index, (entry, snapshot) in enumerate(zip(timeline, snapshots, strict=True)):
            previous_entry = timeline[index - 1] if index > 0 else None
            milestones.extend(
                detect_milestones(
                    historical_snapshots,
                    snapshot,
                    campaign_id=campaign_id,
                    current_snapshot_id=entry["snapshot_id"],
                    previous_snapshot_id=(
                        previous_entry["snapshot_id"] if previous_entry else None
                    ),
                )
            )
            historical_snapshots.append(snapshot)
        return build_campaign_analysis(
            campaign_id,
            timeline,
            snapshots,
            milestones,
        )

    def analyze_and_persist(self, campaign_id: str) -> CampaignAnalysis:
        analysis = self.campaign_analysis(campaign_id)
        now = self._now()
        latest_snapshot_id = (
            self.campaign_history(campaign_id)[-1]["snapshot_id"]
            if self.campaign_history(campaign_id)
            else None
        )
        if latest_snapshot_id is None:
            return analysis
        with self._connection(immediate=True) as connection:
            self._rebuild_campaign_milestones(
                connection,
                campaign_id,
                analysis.milestones,
                now,
            )
            self._persist_strategic_recommendations(
                connection,
                latest_snapshot_id,
                analysis.recommendations,
                now,
            )
            self._persist_evidence_rows(
                connection,
                snapshot_id=latest_snapshot_id,
                campaign_id=campaign_id,
                evidence=(
                    *analysis.facts,
                    *analysis.derived,
                    *analysis.inferences,
                    *analysis.unavailable,
                    *(
                        evidence
                        for recommendation in analysis.recommendations
                        for evidence in recommendation.supporting_evidence
                    ),
                ),
            )
        return analysis

    def detected_milestones(
        self,
        campaign_id: str,
    ) -> tuple[DetectedMilestone, ...]:
        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM campaign_milestones
                WHERE campaign_id = ?
                ORDER BY id
                """,
                (campaign_id,),
            ).fetchall()
        milestones: list[DetectedMilestone] = []
        for row in rows:
            payload = json_loads(row["payload_json"])
            if "milestone_id" not in payload:
                continue
            evidence = tuple(
                Evidence(**item) for item in payload.get("evidence", [])
            )
            milestones.append(
                DetectedMilestone(
                    milestone_id=payload["milestone_id"],
                    milestone_type=payload["milestone_type"],
                    title=payload["title"],
                    description=payload["description"],
                    evidence=evidence,
                    confidence=payload["confidence"],
                    first_seen_snapshot_id=payload["first_seen_snapshot_id"],
                    previous_snapshot_id=payload.get("previous_snapshot_id"),
                )
            )
        return tuple(milestones)
