from __future__ import annotations

import json
import sqlite3
import stat
import tempfile
import tomllib
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from o_alquimista.archive import detect_save_root, extracted_save
from o_alquimista.cli import main
from o_alquimista.database import AlquimistaDatabase
from o_alquimista.errors import (
    ArchiveLimitError,
    IncompleteSaveError,
    InvalidArchiveError,
    UnsafeArchiveError,
)
from o_alquimista.models import Milestone, Recommendation
from o_alquimista.parser import snapshot_from_zip


def sample_files() -> dict[str, object]:
    return {
        "Money.json": {
            "GameVersion": "test-version",
            "OnlineBalance": 125.5,
            "Networth": 300,
            "LifetimeEarnings": 500,
            "WeeklyDepositSum": 25,
            "UnmappedMoneyField": {"preserve": True},
        },
        "Products.json": {
            "DiscoveredProducts": ["product-a"],
            "ListedProducts": ["product-a"],
            "ProductPrices": [{"String": "product-a", "Int": 10}],
            "MixRecipes": [],
            "ActiveMixOperation": {},
        },
        "Time.json": {
            "GameVersion": "test-version",
            "ElapsedDays": 4,
            "TimeOfDay": 900,
            "Playtime": 7200,
        },
        "Rank.json": {
            "Rank": 2,
            "Tier": 1,
            "XP": 10,
            "TotalXP": 30,
            "UnlockedRegions": [],
        },
        "Game.json": {"OrganisationName": "Example Organisation"},
        "Players/local-player/Inventory.json": {
            "Items": [
                {
                    "ID": "product-a",
                    "Quantity": 3,
                    "CashBalance": 20,
                    "UnknownItemValue": "kept",
                }
            ]
        },
        "Properties/sample-property.json": {
            "PropertyCode": "sample-property",
            "IsOwned": True,
            "Employees": [{"ID": "employee-sample", "UnknownRole": "unmapped"}],
            "Objects": [],
        },
        "NPCs.json": {"NPCs": []},
        "Vehicles.json": {"Vehicles": [{"ID": "vehicle-sample", "Unknown": 1}]},
        "Unmapped.json": {"opaque": ["data"]},
    }


def create_save_zip(
    destination: Path,
    *,
    prefix: str = "",
    files: dict[str, object] | None = None,
) -> None:
    content = files if files is not None else sample_files()
    with zipfile.ZipFile(destination, mode="w") as archive:
        for relative, value in content.items():
            name = f"{prefix.rstrip('/')}/{relative}" if prefix else relative
            archive.writestr(name, json.dumps(value))


class ArchiveImportTests(unittest.TestCase):
    def test_valid_zip_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "valid.zip"
            create_save_zip(archive)

            snapshot = snapshot_from_zip(archive).to_dict()

            self.assertEqual(snapshot["metadata"]["product_name"], "O Alquimista")
            self.assertEqual(snapshot["finance"]["online_balance"], 125.5)
            self.assertEqual(snapshot["inventory"]["quantities"], {"product-a": 3.0})
            self.assertEqual(snapshot["employees"][0]["employee_id"], "employee-sample")
            self.assertEqual(snapshot["vehicles"][0]["vehicle_id"], "vehicle-sample")
            self.assertEqual(snapshot["unknown"][0]["name"], "Unmapped.json")

    def test_non_zip_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "not-a-zip.zip"
            path.write_text("plain text", encoding="utf-8")

            with self.assertRaises(InvalidArchiveError):
                snapshot_from_zip(path)

    def test_incomplete_zip_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "incomplete.zip"
            create_save_zip(
                archive,
                files={
                    "Money.json": {},
                    "Products.json": {},
                    "Time.json": {},
                },
            )

            with self.assertRaises(IncompleteSaveError):
                snapshot_from_zip(archive)

    def test_intermediate_folder_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "nested.zip"
            create_save_zip(archive, prefix="export-folder/arbitrary-save")

            snapshot = snapshot_from_zip(archive)

            self.assertEqual(
                snapshot.metadata.save_root,
                "export-folder/arbitrary-save",
            )

    def test_path_traversal_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "unsafe.zip"
            create_save_zip(archive)
            with zipfile.ZipFile(archive, mode="a") as zip_file:
                zip_file.writestr("../../outside.txt", "blocked")

            with self.assertRaises(UnsafeArchiveError):
                snapshot_from_zip(archive)
            self.assertFalse((temporary_path / "outside.txt").exists())

    def test_all_unsafe_path_forms_are_blocked(self) -> None:
        unsafe_names = {
            "absolute": "/outside.txt",
            "parent": "folder/../../outside.txt",
            "windows_drive": "C:/outside.txt",
            "alternate_data_stream": "folder/data.txt:stream",
            "unc": r"\\server\share\outside.txt",
        }
        with tempfile.TemporaryDirectory() as temporary:
            for label, unsafe_name in unsafe_names.items():
                with self.subTest(label=label):
                    archive = Path(temporary) / f"{label}.zip"
                    create_save_zip(archive)
                    with zipfile.ZipFile(archive, mode="a") as zip_file:
                        zip_file.writestr(unsafe_name, "blocked")
                    with self.assertRaises(UnsafeArchiveError):
                        snapshot_from_zip(archive)

    def test_symbolic_link_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "symlink.zip"
            create_save_zip(archive)
            link = zipfile.ZipInfo("unsafe-link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archive, mode="a") as zip_file:
                zip_file.writestr(link, "../../outside.txt")

            with self.assertRaises(UnsafeArchiveError):
                snapshot_from_zip(archive)

    def test_archive_resource_limits_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "limits.zip"
            create_save_zip(archive)

            with patch("o_alquimista.archive.MAX_ARCHIVE_ENTRIES", 1):
                with self.assertRaises(ArchiveLimitError):
                    snapshot_from_zip(archive)

            with patch("o_alquimista.archive.MAX_MEMBER_UNCOMPRESSED_BYTES", 10):
                with self.assertRaises(ArchiveLimitError):
                    snapshot_from_zip(archive)

            with patch("o_alquimista.archive.MAX_TOTAL_UNCOMPRESSED_BYTES", 100):
                with self.assertRaises(ArchiveLimitError):
                    snapshot_from_zip(archive)

            compressed = temporary_path / "ratio.zip"
            create_save_zip(compressed)
            with zipfile.ZipFile(
                compressed,
                mode="a",
                compression=zipfile.ZIP_DEFLATED,
            ) as zip_file:
                zip_file.writestr("compressed-data.bin", b"0" * 4096)
            with (
                patch("o_alquimista.archive.MIN_RATIO_CHECK_BYTES", 1),
                patch("o_alquimista.archive.MAX_COMPRESSION_RATIO", 2.0),
            ):
                with self.assertRaises(ArchiveLimitError):
                    snapshot_from_zip(compressed)

    def test_save_root_detection_does_not_depend_on_folder_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "wrapper" / "any-name"
            root.mkdir(parents=True)
            for name in ("Money.json", "Products.json", "Time.json", "Rank.json"):
                (root / name).write_text("{}", encoding="utf-8")

            self.assertEqual(detect_save_root(Path(temporary)), root.resolve())

    def test_temporary_extraction_is_removed_after_use(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "valid.zip"
            create_save_zip(archive)
            extracted_root: Path | None = None
            with extracted_save(archive) as (root, _):
                extracted_root = root
                self.assertTrue(root.exists())

            self.assertIsNotNone(extracted_root)
            self.assertFalse(extracted_root.exists())

    def test_original_zip_is_not_modified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "immutable.zip"
            create_save_zip(archive)
            before_bytes = archive.read_bytes()
            before_stat = archive.stat()

            snapshot_from_zip(archive)

            after_stat = archive.stat()
            self.assertEqual(archive.read_bytes(), before_bytes)
            self.assertEqual(after_stat.st_mtime_ns, before_stat.st_mtime_ns)
            self.assertEqual(after_stat.st_size, before_stat.st_size)


class SnapshotAndPersistenceTests(unittest.TestCase):
    def test_snapshot_command_creates_json_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "valid.zip"
            output = temporary_path / "output"
            create_save_zip(archive)

            exit_code = main(["snapshot", str(archive), "--out", str(output)])

            self.assertEqual(exit_code, 0)
            self.assertTrue((output / "snapshot.json").is_file())
            self.assertTrue((output / "report.md").is_file())
            data = json.loads((output / "snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(data["metadata"]["schema_version"], "1.0")
            self.assertEqual(
                data["finance"]["origins"]["online_balance"],
                {"file": "Money.json", "field": "OnlineBalance"},
            )

    def test_snapshot_json_is_deterministic_and_omits_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "deterministic.zip"
            first_output = temporary_path / "first"
            second_output = temporary_path / "second"
            create_save_zip(archive)

            self.assertEqual(
                main(["snapshot", str(archive), "--out", str(first_output)]),
                0,
            )
            self.assertEqual(
                main(["snapshot", str(archive), "--out", str(second_output)]),
                0,
            )

            first = (first_output / "snapshot.json").read_bytes()
            second = (second_output / "snapshot.json").read_bytes()
            self.assertEqual(first, second)
            self.assertNotIn(str(temporary_path.resolve()).encode(), first)
            metadata = json.loads(first)["metadata"]
            self.assertIsNone(metadata["imported_at"])
            self.assertEqual(metadata["source_archive"], archive.name)

    def test_snapshot_cannot_write_inside_original_save_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "valid.zip"
            create_save_zip(archive)
            with extracted_save(archive) as (save_root, _):
                output = save_root / "generated"
                exit_code = main(
                    ["snapshot", str(save_root), "--out", str(output)]
                )
                self.assertEqual(exit_code, 2)
                self.assertFalse(output.exists())

    def test_database_cannot_replace_original_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "immutable.zip"
            create_save_zip(archive)
            original = archive.read_bytes()

            exit_code = main(
                ["import", str(archive), "--database", str(archive)]
            )

            self.assertEqual(exit_code, 2)
            self.assertEqual(archive.read_bytes(), original)

    def test_import_persists_all_core_entities_in_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "valid.zip"
            database_path = temporary_path / "history.sqlite3"
            create_save_zip(archive)

            exit_code = main(
                ["import", str(archive), "--database", str(database_path)]
            )

            self.assertEqual(exit_code, 0)
            database = AlquimistaDatabase(database_path)
            history = database.history()
            self.assertEqual(len(history), 1)
            database.persist_milestones(
                history[0]["snapshot_id"],
                [
                    Milestone(
                        id="milestone-sample",
                        titulo="Título de exemplo",
                        descricao="Descrição sintética",
                        categoria="test",
                        prioridade="medium",
                        progresso=0.25,
                        requisitos=("evidência sintética",),
                        impacto_esperado="não inferido",
                        status="in_progress",
                        evidencias=({"file": "Money.json"},),
                    )
                ],
                created_at="2026-01-01T00:00:00+00:00",
            )
            database.persist_recommendations(
                history[0]["snapshot_id"],
                [
                    Recommendation(
                        id="recommendation-sample",
                        problema="Problema sintético",
                        diagnostico="Diagnóstico de teste",
                        acao_recomendada="Ação de teste",
                        custo_estimado=None,
                        impacto_estimado=None,
                        confianca=0.5,
                        evidencias=({"file": "Time.json"},),
                    )
                ],
                created_at="2026-01-01T00:00:00+00:00",
            )
            with closing(sqlite3.connect(database_path)) as connection:
                for table in (
                    "campaigns",
                    "imports",
                    "snapshots",
                    "milestones",
                    "recommendations",
                ):
                    found = connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone()
                    self.assertIsNotNone(found, table)
                snapshot_json = connection.execute(
                    "SELECT snapshot_json FROM snapshots"
                ).fetchone()[0]
                milestone_count = connection.execute(
                    "SELECT COUNT(*) FROM milestones"
                ).fetchone()[0]
                recommendation_count = connection.execute(
                    "SELECT COUNT(*) FROM recommendations"
                ).fetchone()[0]
            self.assertEqual(
                json.loads(snapshot_json)["metadata"]["archive_sha256"],
                history[0]["archive_sha256"],
            )
            self.assertEqual(milestone_count, 1)
            self.assertEqual(recommendation_count, 1)

    def test_sqlite_connection_closes_after_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "exception.sqlite3"
            database = AlquimistaDatabase(database_path)
            database.initialize()

            with self.assertRaises(sqlite3.IntegrityError):
                database.persist_milestones(
                    "missing-snapshot",
                    [
                        Milestone(
                            id="invalid-reference",
                            titulo="Teste",
                            descricao="Teste de fechamento",
                            categoria="test",
                            prioridade="high",
                            progresso=0,
                            requisitos=(),
                            impacto_esperado="nenhum",
                            status="pending",
                            evidencias=(),
                        )
                    ],
                    created_at="2026-01-01T00:00:00+00:00",
                )

            renamed = database_path.with_suffix(".closed")
            database_path.rename(renamed)
            self.assertTrue(renamed.exists())

    def test_sqlite_connection_closes_if_configuration_fails(self) -> None:
        class FailingConnection:
            row_factory: object = None
            closed = False

            def execute(self, _statement: str) -> None:
                raise sqlite3.OperationalError("synthetic configuration failure")

            def close(self) -> None:
                self.closed = True

        connection = FailingConnection()
        database = AlquimistaDatabase(Path("synthetic.sqlite3"))
        with patch(
            "o_alquimista.database.sqlite3.connect",
            return_value=connection,
        ):
            with self.assertRaises(sqlite3.OperationalError):
                database._connect()
        self.assertTrue(connection.closed)

    def test_unknown_fields_keep_raw_value_and_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "valid.zip"
            create_save_zip(archive)

            snapshot = snapshot_from_zip(archive).to_dict()

            unknown = snapshot["finance"]["unknown"][0]
            self.assertEqual(unknown["name"], "UnmappedMoneyField")
            self.assertEqual(unknown["raw"], {"preserve": True})
            self.assertEqual(
                unknown["origin"],
                {"file": "Money.json", "field": "UnmappedMoneyField"},
            )

    def test_pyproject_declares_both_console_commands(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        configuration = tomllib.loads(
            (project_root / "pyproject.toml").read_text(encoding="utf-8")
        )

        scripts = configuration["project"]["scripts"]
        self.assertEqual(scripts["alquimista"], "o_alquimista.cli:main")
        self.assertEqual(scripts["schedule-intel"], "o_alquimista.cli:main")


if __name__ == "__main__":
    unittest.main()
