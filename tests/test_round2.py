from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing, redirect_stderr
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from o_alquimista.analysis import compare_snapshots
from o_alquimista.archive import WINDOWS_RESERVED_COMPONENTS
from o_alquimista.cli import main
from o_alquimista.database import AlquimistaDatabase
from o_alquimista.errors import InvalidArchiveError, SaveDataError
from o_alquimista.json_codec import dumps as json_dumps
from o_alquimista.parser import snapshot_from_zip
from o_alquimista.report import build_markdown
from tests.test_milestone1 import sample_files


def create_raw_save_zip(
    archive_path: Path,
    *,
    online_balance: str,
    networth: str | None = None,
    inventory_json: str | None = None,
    extra_entries: tuple[tuple[str, str], ...] = (),
) -> None:
    files = sample_files()
    files.pop("Money.json")
    if inventory_json is not None:
        files.pop("Players/local-player/Inventory.json")
    money_json = (
        "{"
        '"GameVersion":"synthetic",'
        f'"OnlineBalance":{online_balance},'
        f'"Networth":{networth or online_balance},'
        f'"LifetimeEarnings":{online_balance},'
        f'"WeeklyDepositSum":{online_balance}'
        "}"
    )
    with zipfile.ZipFile(archive_path, mode="w") as archive:
        archive.writestr("Money.json", money_json)
        for name, value in files.items():
            archive.writestr(name, json.dumps(value))
        if inventory_json is not None:
            archive.writestr(
                "Players/local-player/Inventory.json",
                inventory_json,
            )
        for name, content in extra_entries:
            archive.writestr(name, content)


def finance_snapshot(
    value: Decimal | None,
    *,
    availability: str = "observed",
) -> dict[str, object]:
    return {
        "finance": {
            "online_balance": value,
            "loose_cash": value,
            "liquid_cash_estimate": value,
            "networth": value,
            "lifetime_earnings": value,
            "weekly_deposit_sum": value,
            "inventory_list_price_estimate": value,
        },
        "availability": {
            "finance": {
                "state": availability,
                "source_files": ["Money.json"],
                "explanation": "fixture sintética",
            }
        },
    }


class DecimalPrecisionTests(unittest.TestCase):
    def _assert_pipeline_value(self, literal: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "decimal.zip"
            create_raw_save_zip(archive, online_balance=literal)

            snapshot = snapshot_from_zip(archive)

            self.assertIsInstance(snapshot.finance.online_balance, Decimal)
            self.assertEqual(snapshot.finance.online_balance, Decimal(literal))
            self.assertNotIsInstance(snapshot.finance.online_balance, float)
            self.assertIsInstance(snapshot.time.elapsed_days, int)
            self.assertIsInstance(snapshot.npcs.total, int)

    def test_large_integer_money_remains_exact_through_real_pipeline(self) -> None:
        self._assert_pipeline_value("9007199254740993")

    def test_decimal_tenth_remains_exact(self) -> None:
        self._assert_pipeline_value("0.1")

    def test_decimal_hundredth_remains_exact(self) -> None:
        self._assert_pipeline_value("0.01")

    def test_decimal_scale_has_no_binary_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "scaled.zip"
            create_raw_save_zip(archive, online_balance="0.10")

            value = snapshot_from_zip(archive).finance.online_balance

            self.assertEqual(value, Decimal("0.10"))
            self.assertEqual(str(value), "0.10")
            self.assertEqual(json_dumps({"money": value}), '{"money": "0.10"}')

    def test_large_fractional_money_remains_exact(self) -> None:
        self._assert_pipeline_value("12345678901234567890.99")

    def test_one_hundred_hundredths_sum_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "sum.zip"
            items = ",".join(
                (
                    '{"ID":"cash",'
                    '"Quantity":1,'
                    '"CashBalance":0.01}'
                )
                for _ in range(100)
            )
            create_raw_save_zip(
                archive,
                online_balance="0",
                inventory_json=f'{{"Items":[{items}]}}',
            )

            snapshot = snapshot_from_zip(archive)

            self.assertEqual(snapshot.inventory.cash, Decimal("1.00"))
            self.assertEqual(
                snapshot.finance.liquid_cash_estimate,
                Decimal("1.00"),
            )

    def test_financial_comparison_preserves_exact_delta(self) -> None:
        previous = finance_snapshot(Decimal("9007199254740993.00"))
        current = finance_snapshot(Decimal("9007199254740993.01"))

        comparison = compare_snapshots(
            previous,
            current,
            previous_snapshot_id="previous",
            current_snapshot_id="current",
            previous_campaign_id="campaign",
            current_campaign_id="campaign",
        )

        balance = next(
            change
            for change in comparison.financial_changes
            if change.field == "online_balance"
        )
        self.assertEqual(balance.absolute_change, "0.01")

    def test_zero_base_percentage_is_finite_and_unavailable(self) -> None:
        comparison = compare_snapshots(
            finance_snapshot(Decimal("0")),
            finance_snapshot(Decimal("1")),
            previous_snapshot_id="previous",
            current_snapshot_id="current",
            previous_campaign_id="campaign",
            current_campaign_id="campaign",
        )

        balance = next(
            change
            for change in comparison.financial_changes
            if change.field == "online_balance"
        )
        serialized = json_dumps(comparison.to_dict())
        self.assertIsNone(balance.percentage_change)
        self.assertNotIn("NaN", serialized)
        self.assertNotIn("Infinity", serialized)

    def test_persisted_json_has_no_float_approximation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "persist.zip"
            database_path = temporary_path / "memory.sqlite3"
            create_raw_save_zip(archive, online_balance="9007199254740993")

            self.assertEqual(
                main(
                    [
                        "import",
                        str(archive),
                        "--database",
                        str(database_path),
                    ]
                ),
                0,
            )
            database = AlquimistaDatabase(database_path)
            history = database.history()
            with closing(sqlite3.connect(database_path)) as connection:
                stored = connection.execute(
                    "SELECT snapshot_json FROM snapshots"
                ).fetchone()[0]
            recovered = database.snapshot_record(history[0]["snapshot_id"])

            self.assertIn('"online_balance":"9007199254740993"', stored)
            self.assertNotIn("9007199254740992", stored)
            self.assertEqual(
                recovered["snapshot"]["finance"]["online_balance"],
                Decimal("9007199254740993"),
            )

    def test_report_uses_exact_decimal_representation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "report.zip"
            create_raw_save_zip(archive, online_balance="9007199254740993")

            report = build_markdown(snapshot_from_zip(archive).to_dict())

            self.assertIn("$9,007,199,254,740,993.00", report)
            self.assertNotIn("$9,007,199,254,740,992.00", report)

    def test_existing_numeric_snapshot_is_recovered_as_decimal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "legacy.sqlite3"
            database = AlquimistaDatabase(database_path)
            database.initialize()
            legacy_snapshot = (
                '{"finance":{"online_balance":12345678901234567890.99}}'
            )
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute(
                    """
                    INSERT INTO campaigns
                        (id, display_name, source_hint, created_at)
                    VALUES ('legacy-campaign', 'Legacy', 'legacy', '2026-01-01')
                    """
                )
                connection.execute(
                    """
                    INSERT INTO imports
                        (id, campaign_id, source_archive, archive_sha256,
                         save_root, imported_at)
                    VALUES ('legacy-import', 'legacy-campaign', 'legacy.zip', ?,
                            'root', '2026-01-01')
                    """,
                    ("e" * 64,),
                )
                connection.execute(
                    """
                    INSERT INTO snapshots
                        (id, import_id, schema_version, snapshot_json, created_at)
                    VALUES ('legacy-snapshot', 'legacy-import', '1.0', ?,
                            '2026-01-01')
                    """,
                    (legacy_snapshot,),
                )
                connection.commit()

            recovered = database.snapshot_record("legacy-snapshot")["snapshot"]

            self.assertEqual(
                recovered["finance"]["online_balance"],
                Decimal("12345678901234567890.99"),
            )

    def test_non_finite_json_money_is_rejected(self) -> None:
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / "non-finite.zip"
                create_raw_save_zip(archive, online_balance=token)

                with self.assertRaises(SaveDataError):
                    snapshot_from_zip(archive)

    def test_missing_and_invalid_finance_remain_unknown(self) -> None:
        previous = finance_snapshot(None, availability="missing")
        current = finance_snapshot(None, availability="invalid")

        comparison = compare_snapshots(
            previous,
            current,
            previous_snapshot_id="previous",
            current_snapshot_id="current",
            previous_campaign_id="campaign",
            current_campaign_id="campaign",
        )

        self.assertTrue(comparison.financial_changes)
        self.assertEqual(
            {change.status for change in comparison.financial_changes},
            {"unknown"},
        )


class WindowsReservedPathTests(unittest.TestCase):
    def test_all_reserved_components_and_variants_are_blocked(self) -> None:
        reserved_names = sorted(WINDOWS_RESERVED_COMPONENTS)
        variants = [
            *(name.lower() for name in reserved_names),
            "CON.txt",
            "con.json",
            "CON.",
            "CON ",
            "AUX...",
            "NUL.dat",
            "folder/COM1.json",
            "folder/lpt9.bin",
            "CONIN$",
            "CONOUT$.txt",
        ]
        for name in (*reserved_names, *variants):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / "reserved.zip"
                create_raw_save_zip(
                    archive,
                    online_balance="1",
                    extra_entries=((name, "{}"),),
                )

                with self.assertRaises(InvalidArchiveError):
                    snapshot_from_zip(archive)

    def test_similar_non_reserved_names_are_allowed(self) -> None:
        allowed = (
            "CONTAINER.json",
            "AUXILIARY.json",
            "COM10.json",
            "LPT10.json",
            "myCON.txt",
            "PRINTER.json",
        )
        for name in allowed:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / "allowed.zip"
                create_raw_save_zip(
                    archive,
                    online_balance="1",
                    extra_entries=((name, "{}"),),
                )

                snapshot = snapshot_from_zip(archive)

                self.assertEqual(snapshot.finance.online_balance, Decimal("1"))

    def test_cli_failure_is_clean_read_only_and_removes_temporary_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "reserved.zip"
            output = temporary_path / "output"
            create_raw_save_zip(
                archive,
                online_balance="1",
                extra_entries=(("folder/CON.txt", "{}"),),
            )
            original = archive.read_bytes()
            created_directories: list[Path] = []
            real_temporary_directory = tempfile.TemporaryDirectory

            def tracking_temporary_directory(*args: object, **kwargs: object):
                kwargs["dir"] = temporary_path
                context = real_temporary_directory(*args, **kwargs)
                created_directories.append(Path(context.name))
                return context

            stderr = io.StringIO()
            with (
                patch(
                    "o_alquimista.archive.tempfile.TemporaryDirectory",
                    side_effect=tracking_temporary_directory,
                ),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    ["snapshot", str(archive), "--out", str(output)]
                )

            error = stderr.getvalue()
            self.assertEqual(exit_code, 2)
            self.assertNotIn("Traceback", error)
            self.assertNotIn(str(temporary_path.resolve()), error)
            self.assertEqual(archive.read_bytes(), original)
            self.assertTrue(created_directories)
            self.assertTrue(
                all(not directory.exists() for directory in created_directories)
            )
            self.assertFalse(output.exists())
