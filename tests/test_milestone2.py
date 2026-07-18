from __future__ import annotations

import copy
import io
import json
import sqlite3
import stat
import tempfile
import unittest
import zipfile
from contextlib import closing, redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from o_alquimista.analysis import (
    RecommendationContext,
    build_campaign_analysis,
    compare_snapshots,
    detect_milestones,
    generate_recommendations,
    timeline_sort_key,
)
from o_alquimista.archive import MAX_DIRECTORY_DEPTH
from o_alquimista.cli import main
from o_alquimista.database import (
    BASE_SCHEMA,
    DATABASE_VERSION,
    AlquimistaDatabase,
)
from o_alquimista.errors import (
    CampaignMismatchError,
    InvalidArchiveError,
    UnsafeArchiveError,
)
from o_alquimista.evidence import (
    derived_evidence,
    inferred_evidence,
    observed_evidence,
    snapshot_evidence,
    unavailable_evidence,
)
from o_alquimista.identity import (
    fingerprint_archive,
    resolve_campaign_identity,
)
from o_alquimista.parser import snapshot_and_fingerprint_from_zip, snapshot_from_zip
from o_alquimista.report import build_markdown
from schedule_intelligence.cli import main as legacy_main
from tests.test_milestone1 import create_save_zip, sample_files


def campaign_files(
    *,
    organisation: str = "Synthetic Organisation",
    player: str = "synthetic-player",
    day: int = 1,
    balance: float = 50,
    networth: float = 200,
    product: str = "product-a",
    native_campaign_id: str | None = None,
) -> dict[str, object]:
    files = copy.deepcopy(sample_files())
    money = files["Money.json"]
    assert isinstance(money, dict)
    money["OnlineBalance"] = balance
    money["Networth"] = networth
    time_data = files["Time.json"]
    assert isinstance(time_data, dict)
    time_data["ElapsedDays"] = day
    time_data["Playtime"] = day * 1000
    game = files["Game.json"]
    assert isinstance(game, dict)
    game["OrganisationName"] = organisation
    if native_campaign_id is not None:
        game["CampaignId"] = native_campaign_id
    old_inventory = files.pop("Players/local-player/Inventory.json")
    files[f"Players/{player}/Inventory.json"] = old_inventory
    products = files["Products.json"]
    assert isinstance(products, dict)
    products["DiscoveredProducts"] = [product]
    products["ListedProducts"] = [product]
    products["ProductPrices"] = [{"String": product, "Int": 10}]
    return files


def minimal_snapshot(
    *,
    money: float | None = 100,
    networth: float | None = 200,
    product: str = "product-a",
    property_count: int = 0,
    employee_count: int = 0,
) -> dict[str, object]:
    finance: dict[str, object] = {
        "online_balance": money,
        "loose_cash": 0,
        "liquid_cash_estimate": money,
        "networth": networth,
        "lifetime_earnings": 0,
        "weekly_deposit_sum": 0,
        "inventory_list_price_estimate": 0,
    }
    return {
        "finance": finance,
        "game": {
            "elapsed_days": 1,
            "time_of_day": 900,
            "playtime_seconds": 1000,
        },
        "progression": {"rank": 1, "tier": 1, "xp": 0, "total_xp": 10},
        "properties": [
            {
                "name": f"property-{index}",
                "owned": True,
                "employee_count": employee_count,
                "object_count": 0,
            }
            for index in range(property_count)
        ],
        "businesses": [],
        "vehicles": [],
        "employees": [
            {"employee_id": f"employee-{index}"}
            for index in range(employee_count)
        ],
        "products": {"discovered": [product]},
        "inventory": {"quantities": {product: 2}},
    }


class ArchiveIdentityTests(unittest.TestCase):
    def test_sha256_is_deterministic_and_lowercase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "one.zip"
            create_save_zip(archive)
            first = fingerprint_archive(archive)
            second = fingerprint_archive(archive)
            self.assertEqual(first, second)
            self.assertEqual(first.digest, first.digest.lower())
            self.assertEqual(len(first.digest), 64)

    def test_different_content_has_different_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.zip"
            second = Path(temporary) / "second.zip"
            create_save_zip(first, files=campaign_files(day=1))
            create_save_zip(second, files=campaign_files(day=2))
            self.assertNotEqual(
                fingerprint_archive(first).digest,
                fingerprint_archive(second).digest,
            )

    def test_different_filename_same_bytes_has_same_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first-name.zip"
            second = Path(temporary) / "second-name.zip"
            create_save_zip(first)
            second.write_bytes(first.read_bytes())
            self.assertEqual(
                fingerprint_archive(first).digest,
                fingerprint_archive(second).digest,
            )

    def test_concurrent_archive_change_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "changing.zip"
            create_save_zip(archive)
            initial = fingerprint_archive(archive)
            changed = replace(initial, digest="f" * 64)

            with patch(
                "o_alquimista.parser.fingerprint_archive",
                side_effect=(initial, changed),
            ):
                with self.assertRaisesRegex(
                    InvalidArchiveError,
                    "alterado por outro processo",
                ):
                    snapshot_and_fingerprint_from_zip(archive)

    def test_native_campaign_identity_is_high_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "native.zip"
            create_save_zip(
                archive,
                files=campaign_files(native_campaign_id="synthetic-native-id"),
            )
            snapshot, fingerprint = snapshot_and_fingerprint_from_zip(archive)
            identity = resolve_campaign_identity(snapshot, fingerprint)
            self.assertEqual(identity.strategy, "native_campaign_identifier")
            self.assertEqual(identity.confidence, "high")
            serialized = json.dumps(identity.to_dict())
            self.assertNotIn("synthetic-native-id", serialized)

    def test_organisation_id_is_not_claimed_as_campaign_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "organisation-id.zip"
            files = campaign_files()
            game = files["Game.json"]
            assert isinstance(game, dict)
            game["OrganisationId"] = "synthetic-organisation-id"
            create_save_zip(archive, files=files)

            snapshot, fingerprint = snapshot_and_fingerprint_from_zip(archive)
            identity = resolve_campaign_identity(snapshot, fingerprint)

            self.assertEqual(identity.strategy, "stable_internal_identifiers")
            self.assertEqual(identity.confidence, "medium")

    def test_campaign_identity_is_stable_across_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "early.zip"
            second = Path(temporary) / "late.zip"
            create_save_zip(first, files=campaign_files(day=1, balance=20))
            create_save_zip(second, files=campaign_files(day=9, balance=900))
            snapshot_a, fingerprint_a = snapshot_and_fingerprint_from_zip(first)
            snapshot_b, fingerprint_b = snapshot_and_fingerprint_from_zip(second)
            identity_a = resolve_campaign_identity(snapshot_a, fingerprint_a)
            identity_b = resolve_campaign_identity(snapshot_b, fingerprint_b)
            self.assertEqual(identity_a.campaign_id, identity_b.campaign_id)
            self.assertEqual(identity_a.confidence, "medium")

    def test_different_internal_identity_creates_different_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "one.zip"
            second = Path(temporary) / "two.zip"
            create_save_zip(
                first,
                files=campaign_files(organisation="Campaign One", player="player-one"),
            )
            create_save_zip(
                second,
                files=campaign_files(organisation="Campaign Two", player="player-two"),
            )
            snapshot_a, fingerprint_a = snapshot_and_fingerprint_from_zip(first)
            snapshot_b, fingerprint_b = snapshot_and_fingerprint_from_zip(second)
            self.assertNotEqual(
                resolve_campaign_identity(snapshot_a, fingerprint_a).campaign_id,
                resolve_campaign_identity(snapshot_b, fingerprint_b).campaign_id,
            )

    def test_campaign_fallback_is_explicit_and_low_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "fallback.zip"
            files = campaign_files()
            files.pop("Game.json")
            files.pop("Players/synthetic-player/Inventory.json")
            create_save_zip(archive, files=files)
            snapshot, fingerprint = snapshot_and_fingerprint_from_zip(archive)
            identity = resolve_campaign_identity(snapshot, fingerprint)
            self.assertEqual(identity.strategy, "archive_scoped_fallback")
            self.assertEqual(identity.confidence, "low")
            self.assertEqual(identity.evidence[0].category, "unavailable")


class EvidenceAndAnalysisTests(unittest.TestCase):
    def test_missing_financial_fields_remain_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "missing-finance.zip"
            files = campaign_files()
            files["Money.json"] = {"GameVersion": "synthetic-version"}
            files.pop("Players/synthetic-player/Inventory.json")
            create_save_zip(archive, files=files)

            snapshot = snapshot_from_zip(archive).to_dict()

            self.assertIsNone(snapshot["finance"]["online_balance"])
            self.assertIsNone(snapshot["finance"]["loose_cash"])
            self.assertIsNone(snapshot["finance"]["liquid_cash_estimate"])
            self.assertIsNone(snapshot["finance"]["networth"])
            self.assertIn("Saldo online: **indisponível**", build_markdown(snapshot))

    def test_evidence_categories_are_explicit(self) -> None:
        observed = observed_evidence(
            source_file="Money.json",
            source_path="OnlineBalance",
            field_name="online_balance",
            value=10,
            explanation="observado",
        )
        derived = derived_evidence(
            sources=("Money.json",),
            field_name="double",
            value=20,
            calculation="10 * 2",
            explanation="derivado",
        )
        inferred = inferred_evidence(
            evidence_ids=(observed.evidence_id,),
            field_name="signal",
            value=True,
            calculation="regra sintética",
            explanation="inferido",
            confidence="low",
        )
        unavailable = unavailable_evidence(
            field_name="expenses",
            explanation="ausente",
        )
        self.assertEqual(
            {observed.category, derived.category, inferred.category, unavailable.category},
            {"observed", "derived", "inferred", "unavailable"},
        )

    def test_snapshot_evidence_has_no_absolute_path(self) -> None:
        evidence = snapshot_evidence(minimal_snapshot())
        serialized = json.dumps([item.to_dict() for item in evidence])
        self.assertNotIn("C:\\", serialized)
        self.assertTrue(any(item.category == "observed" for item in evidence))
        self.assertTrue(any(item.category == "derived" for item in evidence))
        self.assertTrue(any(item.category == "unavailable" for item in evidence))

    def test_financial_comparison_uses_decimal_and_percentage(self) -> None:
        previous = minimal_snapshot(money=100, networth=200)
        current = minimal_snapshot(money=150, networth=300)
        comparison = compare_snapshots(
            previous,
            current,
            previous_snapshot_id="snapshot-a",
            current_snapshot_id="snapshot-b",
            previous_campaign_id="campaign-one",
            current_campaign_id="campaign-one",
        )
        balance = next(
            item
            for item in comparison.financial_changes
            if item.field == "online_balance"
        )
        self.assertEqual(balance.absolute_change, "50.00")
        self.assertEqual(balance.percentage_change, "50.00")

    def test_missing_financial_value_is_not_zero(self) -> None:
        previous = minimal_snapshot()
        current = minimal_snapshot()
        assert isinstance(previous["finance"], dict)
        previous["finance"].pop("networth")
        comparison = compare_snapshots(
            previous,
            current,
            previous_snapshot_id="a",
            current_snapshot_id="b",
            previous_campaign_id="campaign",
            current_campaign_id="campaign",
        )
        networth = next(
            item for item in comparison.financial_changes if item.field == "networth"
        )
        self.assertEqual(networth.status, "unknown")
        self.assertIsNone(networth.previous)

    def test_operational_comparison_detects_added_entity(self) -> None:
        previous = minimal_snapshot(property_count=0)
        current = minimal_snapshot(property_count=1)
        comparison = compare_snapshots(
            previous,
            current,
            previous_snapshot_id="a",
            current_snapshot_id="b",
            previous_campaign_id="campaign",
            current_campaign_id="campaign",
        )
        self.assertEqual(comparison.operational_changes["properties"][0].status, "added")

    def test_cross_campaign_comparison_is_blocked_by_default(self) -> None:
        with self.assertRaises(CampaignMismatchError):
            compare_snapshots(
                minimal_snapshot(),
                minimal_snapshot(),
                previous_snapshot_id="a",
                current_snapshot_id="b",
                previous_campaign_id="campaign-a",
                current_campaign_id="campaign-b",
            )

    def test_cross_campaign_comparison_requires_explicit_override(self) -> None:
        comparison = compare_snapshots(
            minimal_snapshot(),
            minimal_snapshot(),
            previous_snapshot_id="a",
            current_snapshot_id="b",
            previous_campaign_id="campaign-a",
            current_campaign_id="campaign-b",
            allow_cross_campaign=True,
        )
        self.assertTrue(comparison.cross_campaign_override)
        self.assertIsNone(comparison.campaign_id)

    def test_timeline_prefers_internal_time(self) -> None:
        later_import_earlier_game = {
            "snapshot_id": "b",
            "observable_game_moment": {"elapsed_days": 1},
            "progression_summary": {"total_xp": 10},
            "imported_at": "2026-02-01",
        }
        earlier_import_later_game = {
            "snapshot_id": "a",
            "observable_game_moment": {"elapsed_days": 2},
            "progression_summary": {"total_xp": 20},
            "imported_at": "2026-01-01",
        }
        ordered = sorted(
            [earlier_import_later_game, later_import_earlier_game],
            key=timeline_sort_key,
        )
        self.assertEqual(ordered[0]["snapshot_id"], "b")

    def test_timeline_tie_breaker_is_deterministic(self) -> None:
        base = {
            "observable_game_moment": {"elapsed_days": 1},
            "progression_summary": {"total_xp": 10},
            "imported_at": "2026-01-01",
        }
        entries = [
            {**base, "snapshot_id": "snapshot-b"},
            {**base, "snapshot_id": "snapshot-a"},
        ]
        self.assertEqual(
            [item["snapshot_id"] for item in sorted(entries, key=timeline_sort_key)],
            ["snapshot-a", "snapshot-b"],
        )

    def test_first_milestones_are_deterministic_and_not_duplicated(self) -> None:
        current = minimal_snapshot(property_count=1, employee_count=1)
        first = detect_milestones(
            None,
            current,
            campaign_id="campaign",
            current_snapshot_id="snapshot",
            previous_snapshot_id=None,
        )
        second = detect_milestones(
            None,
            current,
            campaign_id="campaign",
            current_snapshot_id="snapshot",
            previous_snapshot_id=None,
        )
        self.assertEqual(first, second)
        ids = [item.milestone_id for item in first]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("first_property", {item.milestone_type for item in first})

    def test_recommendation_has_evidence_and_missing_information(self) -> None:
        snapshot = minimal_snapshot(money=20, property_count=1, employee_count=0)
        recommendations = generate_recommendations(
            RecommendationContext(
                campaign_id="campaign",
                snapshot_id="snapshot",
                snapshot=snapshot,
                snapshot_count=1,
            )
        )
        self.assertTrue(recommendations)
        self.assertTrue(all(item.supporting_evidence for item in recommendations))
        self.assertTrue(any(item.missing_information for item in recommendations))
        self.assertTrue(all(item.rule_id for item in recommendations))

    def test_analysis_separates_facts_inferences_and_unavailable(self) -> None:
        snapshot = minimal_snapshot()
        timeline = [
            {"snapshot_id": "a"},
            {"snapshot_id": "b"},
        ]
        analysis = build_campaign_analysis(
            "campaign",
            timeline,
            [snapshot, snapshot],
            (),
        )
        self.assertTrue(analysis.facts)
        self.assertTrue(analysis.inferences)
        self.assertTrue(analysis.unavailable)


class PersistenceAndCliTests(unittest.TestCase):
    def _import(
        self,
        database: AlquimistaDatabase,
        archive: Path,
    ):
        snapshot, fingerprint = snapshot_and_fingerprint_from_zip(archive)
        identity = resolve_campaign_identity(snapshot, fingerprint)
        return database.persist_import(snapshot, fingerprint, identity)

    def test_deduplication_and_idempotent_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "save.zip"
            database = AlquimistaDatabase(temporary_path / "memory.sqlite3")
            create_save_zip(archive, files=campaign_files())
            first = self._import(database, archive)
            second = self._import(database, archive)
            self.assertFalse(first.deduplicated)
            self.assertTrue(second.deduplicated)
            self.assertEqual(first.import_id, second.import_id)
            self.assertEqual(len(database.history()), 1)
            self.assertEqual(len(database.campaign_list()), 1)

    def test_same_bytes_with_new_name_are_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            first_archive = temporary_path / "first.zip"
            second_archive = temporary_path / "renamed.zip"
            database = AlquimistaDatabase(temporary_path / "memory.sqlite3")
            create_save_zip(first_archive, files=campaign_files())
            second_archive.write_bytes(first_archive.read_bytes())
            first = self._import(database, first_archive)
            second = self._import(database, second_archive)
            self.assertEqual(first.import_id, second.import_id)
            self.assertTrue(second.deduplicated)

    def test_timeline_orders_two_imports_of_same_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            late = temporary_path / "late.zip"
            early = temporary_path / "early.zip"
            database = AlquimistaDatabase(temporary_path / "memory.sqlite3")
            create_save_zip(late, files=campaign_files(day=10, balance=500))
            create_save_zip(early, files=campaign_files(day=2, balance=100))
            late_record = self._import(database, late)
            early_record = self._import(database, early)
            self.assertEqual(late_record.campaign_id, early_record.campaign_id)
            timeline = database.campaign_history(late_record.campaign_id)
            self.assertEqual(
                [entry["observable_game_moment"]["elapsed_days"] for entry in timeline],
                [2, 10],
            )
            self.assertEqual(
                [entry["chronological_order"] for entry in timeline],
                [1, 2],
            )
            first_property_entries = [
                entry
                for entry in timeline
                if any(
                    milestone["milestone_type"] == "first_property"
                    for milestone in entry["milestones"]
                )
            ]
            self.assertEqual(len(first_property_entries), 1)
            self.assertEqual(
                first_property_entries[0]["snapshot_id"],
                early_record.snapshot_id,
            )

    def test_same_evidence_is_linked_to_each_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            database_path = temporary_path / "memory.sqlite3"
            first_archive = temporary_path / "first.zip"
            second_archive = temporary_path / "second.zip"
            create_save_zip(first_archive, files=campaign_files(day=1))
            create_save_zip(second_archive, files=campaign_files(day=2))
            database = AlquimistaDatabase(database_path)
            first = self._import(database, first_archive)
            second = self._import(database, second_archive)

            with closing(sqlite3.connect(database_path)) as connection:
                rows = connection.execute(
                    """
                    SELECT snapshot_id, payload_json
                    FROM evidence
                    WHERE category = 'observed'
                    """
                ).fetchall()
            lifetime_snapshots = {
                snapshot_id
                for snapshot_id, payload_json in rows
                if json.loads(payload_json).get("field_name") == "lifetime_earnings"
            }
            self.assertEqual(
                lifetime_snapshots,
                {first.snapshot_id, second.snapshot_id},
            )

    def test_sqlite_foreign_keys_and_memory_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "memory.sqlite3"
            database = AlquimistaDatabase(database_path)
            database.initialize()
            with closing(sqlite3.connect(database_path)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], DATABASE_VERSION)
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertTrue(
                    {
                        "archive_fingerprints",
                        "timeline_entries",
                        "evidence",
                        "snapshot_relationships",
                    }.issubset(tables)
                )
            with database._connection() as connection:
                self.assertEqual(
                    connection.execute("PRAGMA foreign_keys").fetchone()[0],
                    1,
                )

    def test_transaction_rolls_back_partial_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "save.zip"
            database_path = temporary_path / "memory.sqlite3"
            database = AlquimistaDatabase(database_path)
            create_save_zip(archive, files=campaign_files())
            snapshot, fingerprint = snapshot_and_fingerprint_from_zip(archive)
            identity = resolve_campaign_identity(snapshot, fingerprint)
            with patch.object(
                AlquimistaDatabase,
                "_ensure_campaign",
                side_effect=RuntimeError("synthetic rollback"),
            ):
                with self.assertRaises(RuntimeError):
                    database.persist_import(snapshot, fingerprint, identity)
            with closing(sqlite3.connect(database_path)) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM archive_fingerprints"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM imports").fetchone()[0],
                    0,
                )

    def test_schema_migration_rolls_back_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "rollback-migration.sqlite3"
            database = AlquimistaDatabase(database_path)

            with patch.object(
                AlquimistaDatabase,
                "_add_missing_columns",
                side_effect=RuntimeError("synthetic migration failure"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "synthetic migration failure",
                ):
                    database.initialize()

            with closing(sqlite3.connect(database_path)) as connection:
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(tables, [])
            self.assertEqual(version, 0)

    def test_migration_from_milestone1_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "legacy.sqlite3"
            with closing(sqlite3.connect(database_path)) as connection:
                connection.executescript(BASE_SCHEMA)
                connection.execute(
                    """
                    INSERT INTO campaigns (id, display_name, source_hint, created_at)
                    VALUES ('legacy-campaign', 'Legacy', 'legacy', '2026-01-01')
                    """
                )
                connection.execute(
                    """
                    INSERT INTO imports
                        (id, campaign_id, source_archive, archive_sha256,
                         save_root, imported_at)
                    VALUES ('legacy-import', 'legacy-campaign', 'save.zip',
                            ?, 'root', '2026-01-01')
                    """,
                    ("a" * 64,),
                )
                connection.execute(
                    """
                    INSERT INTO snapshots
                        (id, import_id, schema_version, snapshot_json, created_at)
                    VALUES ('legacy-snapshot', 'legacy-import', '1.0', '{}',
                            '2026-01-01')
                    """
                )
                connection.commit()
            AlquimistaDatabase(database_path).initialize()
            with closing(sqlite3.connect(database_path)) as connection:
                fingerprint_id = connection.execute(
                    "SELECT fingerprint_id FROM imports WHERE id='legacy-import'"
                ).fetchone()[0]
                self.assertEqual(fingerprint_id, f"archive-sha256-{'a' * 64}")
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM archive_fingerprints"
                    ).fetchone()[0],
                    1,
                )

    def test_cli_campaign_compare_timeline_and_analyze(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            database_path = temporary_path / "memory.sqlite3"
            first = temporary_path / "first.zip"
            second = temporary_path / "second.zip"
            create_save_zip(first, files=campaign_files(day=1, balance=20))
            create_save_zip(second, files=campaign_files(day=2, balance=200))
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(["import", str(first), "--database", str(database_path)]),
                    0,
                )
                self.assertEqual(
                    main(["import", str(second), "--database", str(database_path)]),
                    0,
                )
            database = AlquimistaDatabase(database_path)
            campaign = database.campaign_list()[0]["campaign_id"]
            history = database.campaign_history(campaign)
            commands = (
                ["campaign", "list", "--database", str(database_path)],
                [
                    "campaign",
                    "history",
                    campaign,
                    "--database",
                    str(database_path),
                ],
                [
                    "timeline",
                    campaign,
                    "--database",
                    str(database_path),
                ],
                [
                    "compare",
                    history[0]["snapshot_id"],
                    history[1]["snapshot_id"],
                    "--database",
                    str(database_path),
                ],
                [
                    "analyze",
                    campaign,
                    "--database",
                    str(database_path),
                ],
            )
            for command in commands:
                with self.subTest(command=command[0]), redirect_stdout(io.StringIO()):
                    self.assertEqual(main(command), 0)

    def test_cli_cross_campaign_compare_returns_readable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            database_path = temporary_path / "memory.sqlite3"
            first = temporary_path / "first.zip"
            second = temporary_path / "second.zip"
            create_save_zip(
                first,
                files=campaign_files(organisation="One", player="one"),
            )
            create_save_zip(
                second,
                files=campaign_files(organisation="Two", player="two"),
            )
            with redirect_stdout(io.StringIO()):
                main(["import", str(first), "--database", str(database_path)])
                main(["import", str(second), "--database", str(database_path)])
            history = AlquimistaDatabase(database_path).history()
            error = io.StringIO()
            with redirect_stderr(error):
                exit_code = main(
                    [
                        "compare",
                        history[0]["snapshot_id"],
                        history[1]["snapshot_id"],
                        "--database",
                        str(database_path),
                    ]
                )
            self.assertEqual(exit_code, 2)
            self.assertIn("campanhas diferentes", error.getvalue())
            self.assertNotIn("Traceback", error.getvalue())

    def test_analytical_output_cannot_overwrite_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "save.zip"
            database_path = temporary_path / "memory.sqlite3"
            create_save_zip(archive, files=campaign_files())
            persisted = self._import(
                AlquimistaDatabase(database_path),
                archive,
            )
            original = database_path.read_bytes()
            error = io.StringIO()

            with redirect_stderr(error):
                exit_code = main(
                    [
                        "timeline",
                        persisted.campaign_id,
                        "--database",
                        str(database_path),
                        "--out",
                        str(database_path),
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertEqual(database_path.read_bytes(), original)
            self.assertIn("não pode sobrescrever", error.getvalue())

            protected_zip = temporary_path / "protected.zip"
            protected_zip.write_bytes(b"synthetic immutable zip marker")
            error = io.StringIO()
            with redirect_stderr(error):
                exit_code = main(
                    [
                        "timeline",
                        persisted.campaign_id,
                        "--database",
                        str(database_path),
                        "--out",
                        str(protected_zip),
                    ]
                )
            self.assertEqual(exit_code, 2)
            self.assertEqual(
                protected_zip.read_bytes(),
                b"synthetic immutable zip marker",
            )
            self.assertIn("arquivos ZIP", error.getvalue())

    def test_legacy_cli_is_pure_alias(self) -> None:
        self.assertIs(legacy_main, main)

    def test_persisted_json_does_not_contain_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "save.zip"
            database_path = temporary_path / "memory.sqlite3"
            create_save_zip(archive, files=campaign_files())
            self._import(AlquimistaDatabase(database_path), archive)
            with closing(sqlite3.connect(database_path)) as connection:
                values = connection.execute(
                    "SELECT snapshot_json FROM snapshots"
                ).fetchone()[0]
            self.assertNotIn(str(temporary_path.resolve()), values)


class AdditionalArchiveSecurityTests(unittest.TestCase):
    def test_duplicate_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "duplicate.zip"
            create_save_zip(archive)
            with zipfile.ZipFile(archive, mode="a") as zip_file:
                zip_file.writestr("Money.json", "{}")
            with self.assertRaises(UnsafeArchiveError):
                snapshot_from_zip(archive)

    def test_file_outside_detected_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "scope.zip"
            create_save_zip(archive, prefix="wrapper/save")
            with zipfile.ZipFile(archive, mode="a") as zip_file:
                zip_file.writestr("wrapper/unrelated.txt", "blocked")
            with self.assertRaises(UnsafeArchiveError):
                snapshot_from_zip(archive)

    def test_special_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "special.zip"
            create_save_zip(archive)
            special = zipfile.ZipInfo("special-fifo")
            special.create_system = 3
            special.external_attr = (stat.S_IFIFO | 0o600) << 16
            with zipfile.ZipFile(archive, mode="a") as zip_file:
                zip_file.writestr(special, b"")
            with self.assertRaises(UnsafeArchiveError):
                snapshot_from_zip(archive)

    def test_directory_depth_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "deep.zip"
            prefix = "/".join(f"level-{index}" for index in range(MAX_DIRECTORY_DEPTH + 1))
            create_save_zip(archive, prefix=prefix)
            with self.assertRaises(Exception) as caught:
                snapshot_from_zip(archive)
            self.assertIn("profundidade", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
