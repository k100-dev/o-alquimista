"""Persistência SQLite local para histórico e artefatos analíticos."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from .models import Milestone, NormalizedSnapshot, Recommendation


SCHEMA = """
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

CREATE INDEX IF NOT EXISTS idx_imports_campaign ON imports(campaign_id);
CREATE INDEX IF NOT EXISTS idx_imports_imported_at ON imports(imported_at);
"""


@dataclass(frozen=True, slots=True)
class PersistedImport:
    campaign_id: str
    import_id: str
    snapshot_id: str


class AlquimistaDatabase:
    """Repositório SQLite com transações curtas e schema inicial idempotente."""

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
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(SCHEMA)

    def persist_snapshot(
        self,
        snapshot: NormalizedSnapshot,
        *,
        campaign_name: str,
    ) -> PersistedImport:
        metadata = snapshot.metadata
        if metadata.source_archive is None or metadata.archive_sha256 is None:
            raise ValueError("A persistência de import requer origem em arquivo ZIP.")

        self.initialize()
        snapshot_data = snapshot.to_dict()
        imported_at = datetime.now(UTC).isoformat()
        campaign_id = str(uuid.uuid4())
        import_id = str(uuid.uuid4())
        snapshot_id = str(uuid.uuid4())
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT id FROM campaigns WHERE source_hint = ?",
                (metadata.source_archive,),
            ).fetchone()
            if existing:
                campaign_id = str(existing["id"])
            else:
                connection.execute(
                    """
                    INSERT INTO campaigns
                        (id, display_name, source_hint, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        campaign_id,
                        campaign_name,
                        metadata.source_archive,
                        imported_at,
                    ),
                )
            connection.execute(
                """
                INSERT INTO imports
                    (id, campaign_id, source_archive, archive_sha256,
                     save_root, imported_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    import_id,
                    campaign_id,
                    metadata.source_archive,
                    metadata.archive_sha256,
                    metadata.save_root,
                    imported_at,
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
                    metadata.schema_version,
                    json.dumps(snapshot_data, ensure_ascii=False, sort_keys=True),
                    imported_at,
                ),
            )
        return PersistedImport(
            campaign_id=campaign_id,
            import_id=import_id,
            snapshot_id=snapshot_id,
        )

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
                json.dumps(asdict(milestone), ensure_ascii=False),
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
                json.dumps(asdict(recommendation), ensure_ascii=False),
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
                    c.id AS campaign_id,
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
