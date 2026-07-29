from __future__ import annotations

import copy
import io
import sqlite3
import struct
import tempfile
import unittest
import zipfile
from contextlib import closing, redirect_stderr
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from o_alquimista.analysis import compare_snapshots
from o_alquimista.cli import main
from o_alquimista.database import AlquimistaDatabase
from o_alquimista.errors import (
    InvalidArchiveError,
    UnsafeProvenanceError,
    UnsupportedDatabaseVersionError,
)
from o_alquimista.evidence import snapshot_evidence
from o_alquimista.identity import fingerprint_archive, resolve_campaign_identity
from o_alquimista.json_codec import dumps as json_dumps
from o_alquimista.json_codec import loads_snapshot
from o_alquimista.memory_reports import build_analysis_markdown
from o_alquimista.parser import snapshot_and_fingerprint_from_zip, snapshot_from_zip
from tests.test_milestone1 import create_save_zip, sample_files
from tests.test_milestone2 import campaign_files


def _import_archive(database: AlquimistaDatabase, archive: Path):
    snapshot, fingerprint = snapshot_and_fingerprint_from_zip(archive)
    identity = resolve_campaign_identity(snapshot, fingerprint)
    return database.persist_import(snapshot, fingerprint, identity)


def _zip_member_data_offset(data: bytearray, header_offset: int) -> int:
    name_length, extra_length = struct.unpack_from("<HH", data, header_offset + 26)
    return header_offset + 30 + name_length + extra_length


def _mutate_member_payload(archive: Path, member_name: str) -> None:
    with zipfile.ZipFile(archive) as source:
        info = source.getinfo(member_name)
    data = bytearray(archive.read_bytes())
    offset = _zip_member_data_offset(data, info.header_offset)
    data[offset] ^= 0x01
    archive.write_bytes(data)


def _set_zip_member_bits(
    archive: Path,
    member_name: str,
    *,
    encrypted: bool = False,
    compression_method: int | None = None,
) -> None:
    with zipfile.ZipFile(archive) as source:
        info = source.getinfo(member_name)
    data = bytearray(archive.read_bytes())
    if encrypted:
        local_flags = struct.unpack_from("<H", data, info.header_offset + 6)[0]
        struct.pack_into("<H", data, info.header_offset + 6, local_flags | 0x1)
    if compression_method is not None:
        struct.pack_into("<H", data, info.header_offset + 8, compression_method)

    central_offset = data.find(b"PK\x01\x02")
    while central_offset >= 0:
        name_length, extra_length, comment_length = struct.unpack_from(
            "<HHH", data, central_offset + 28
        )
        name_start = central_offset + 46
        name = bytes(data[name_start : name_start + name_length]).decode("utf-8")
        if name == member_name:
            if encrypted:
                central_flags = struct.unpack_from(
                    "<H", data, central_offset + 8
                )[0]
                struct.pack_into(
                    "<H", data, central_offset + 8, central_flags | 0x1
                )
            if compression_method is not None:
                struct.pack_into(
                    "<H", data, central_offset + 10, compression_method
                )
            archive.write_bytes(data)
            return
        central_offset = data.find(
            b"PK\x01\x02",
            name_start + name_length + extra_length + comment_length,
        )
    raise AssertionError("Entrada não encontrada no diretório central sintético.")


def _declare_truncated_member(archive: Path, member_name: str) -> None:
    """Declara mais bytes que os disponíveis para simular membro truncado."""
    with zipfile.ZipFile(archive) as source:
        info = source.getinfo(member_name)
    data = bytearray(archive.read_bytes())
    for offset in (info.header_offset + 18, info.header_offset + 22):
        declared = struct.unpack_from("<L", data, offset)[0]
        struct.pack_into("<L", data, offset, declared + 32)

    central_offset = data.find(b"PK\x01\x02")
    while central_offset >= 0:
        name_length, extra_length, comment_length = struct.unpack_from(
            "<HHH", data, central_offset + 28
        )
        name_start = central_offset + 46
        name = bytes(data[name_start : name_start + name_length]).decode("utf-8")
        if name == member_name:
            for offset in (central_offset + 20, central_offset + 24):
                declared = struct.unpack_from("<L", data, offset)[0]
                struct.pack_into("<L", data, offset, declared + 32)
            archive.write_bytes(data)
            return
        central_offset = data.find(
            b"PK\x01\x02",
            name_start + name_length + extra_length + comment_length,
        )
    raise AssertionError("Entrada truncada não encontrada no diretório central.")


class TimelineDeterminismTests(unittest.TestCase):
    def test_inverse_import_order_produces_identical_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_a = root / "a.zip"
            archive_z = root / "z.zip"
            files_a = campaign_files(
                day=4,
                balance=80,
                native_campaign_id="round3-timeline",
            )
            files_z = copy.deepcopy(files_a)
            money_a = files_a["Money.json"]
            money_z = files_z["Money.json"]
            assert isinstance(money_a, dict)
            assert isinstance(money_z, dict)
            money_a["DeterministicMarker"] = "A"
            money_z["DeterministicMarker"] = "Z"
            create_save_zip(archive_a, files=files_a)
            create_save_zip(archive_z, files=files_z)

            first_db = AlquimistaDatabase(root / "first.sqlite3")
            second_db = AlquimistaDatabase(root / "second.sqlite3")
            with patch.object(
                AlquimistaDatabase,
                "_now",
                side_effect=("2026-07-18T20:00:00+00:00", "2026-07-18T21:00:00+00:00"),
            ):
                record_a = _import_archive(first_db, archive_a)
                _import_archive(first_db, archive_z)
            with patch.object(
                AlquimistaDatabase,
                "_now",
                side_effect=("2030-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
            ):
                _import_archive(second_db, archive_z)
                record_z = _import_archive(second_db, archive_a)

            self.assertEqual(record_a.campaign_id, record_z.campaign_id)
            campaign_id = record_a.campaign_id
            first_timeline = first_db.campaign_history(campaign_id)
            second_timeline = second_db.campaign_history(campaign_id)
            self.assertEqual(first_timeline, second_timeline)
            self.assertEqual(
                [entry["snapshot_id"] for entry in first_timeline],
                sorted(entry["snapshot_id"] for entry in first_timeline),
            )

            def relationships(database_path: Path) -> list[tuple[object, ...]]:
                with closing(sqlite3.connect(database_path)) as connection:
                    return connection.execute(
                        """
                        SELECT id, previous_snapshot_id, current_snapshot_id,
                               relationship_type, evidence_json
                        FROM snapshot_relationships
                        ORDER BY id
                        """
                    ).fetchall()

            self.assertEqual(
                relationships(first_db.path),
                relationships(second_db.path),
            )
            first_analysis = first_db.campaign_analysis(campaign_id)
            second_analysis = second_db.campaign_analysis(campaign_id)
            self.assertEqual(first_analysis.to_dict(), second_analysis.to_dict())
            self.assertEqual(
                {
                    item.evidence_id
                    for item in (
                        *first_analysis.facts,
                        *first_analysis.derived,
                        *first_analysis.inferences,
                        *first_analysis.unavailable,
                    )
                },
                {
                    item.evidence_id
                    for item in (
                        *second_analysis.facts,
                        *second_analysis.derived,
                        *second_analysis.inferences,
                        *second_analysis.unavailable,
                    )
                },
            )
            first_report = build_analysis_markdown(first_analysis)
            second_report = build_analysis_markdown(second_analysis)
            self.assertEqual(first_report, second_report)
            self.assertNotIn("DeterministicMarker", first_report)
            self.assertNotIn("round3-timeline", first_report)
            self.assertNotIn("unknown_fields", first_report)
            self.assertNotIn("raw_value", first_report)
            self.assertEqual(
                [item.to_dict() for item in first_db.detected_milestones(campaign_id)],
                [item.to_dict() for item in second_db.detected_milestones(campaign_id)],
            )
            left_a, right_a = (
                first_db.snapshot_record(entry["snapshot_id"])
                for entry in first_timeline
            )
            left_b, right_b = (
                second_db.snapshot_record(entry["snapshot_id"])
                for entry in second_timeline
            )
            comparison_a = compare_snapshots(
                left_a["snapshot"],
                right_a["snapshot"],
                previous_snapshot_id=left_a["snapshot_id"],
                current_snapshot_id=right_a["snapshot_id"],
                previous_campaign_id=campaign_id,
                current_campaign_id=campaign_id,
            )
            comparison_b = compare_snapshots(
                left_b["snapshot"],
                right_b["snapshot"],
                previous_snapshot_id=left_b["snapshot_id"],
                current_snapshot_id=right_b["snapshot_id"],
                previous_campaign_id=campaign_id,
                current_campaign_id=campaign_id,
            )
            self.assertEqual(comparison_a.to_dict(), comparison_b.to_dict())


class EvidenceLineageTests(unittest.TestCase):
    def _liquidity_evidence(self, snapshot: dict[str, object]):
        return next(
            item
            for item in snapshot_evidence(snapshot)
            if item.field_name == "liquid_cash_estimate"
        )

    def test_liquidity_preserves_world_storage_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "world.zip"
            files = sample_files()
            files.pop("Players/local-player/Inventory.json")
            files["WorldStorageEntities.json"] = {
                "Entities": [
                    {
                        "Contents": {
                            "Items": [
                                {
                                    "ID": "cash",
                                    "Quantity": 1,
                                    "CashBalance": 20,
                                }
                            ]
                        }
                    }
                ]
            }
            create_save_zip(archive, files=files)
            evidence = self._liquidity_evidence(snapshot_from_zip(archive).to_dict())

            self.assertIn("WorldStorageEntities.json", evidence.source_file or "")
            self.assertNotIn("Players/", evidence.source_file or "")
            self.assertEqual(evidence.category, "derived")

    def test_liquidity_preserves_player_inventory_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "player.zip"
            create_save_zip(archive)
            evidence = self._liquidity_evidence(snapshot_from_zip(archive).to_dict())

            self.assertIn(
                "Players/local-player/Inventory.json",
                evidence.source_file or "",
            )
            self.assertNotIn("WorldStorageEntities.json", evidence.source_file or "")

    def test_liquidity_preserves_all_inventory_origins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "multiple-origins.zip"
            files = sample_files()
            files["WorldStorageEntities.json"] = {
                "Entities": [
                    {
                        "Contents": {
                            "Items": [
                                {
                                    "ID": "cash",
                                    "Quantity": 1,
                                    "CashBalance": 5,
                                }
                            ]
                        }
                    }
                ]
            }
            create_save_zip(archive, files=files)
            evidence = self._liquidity_evidence(snapshot_from_zip(archive).to_dict())

            self.assertIn(
                "Players/local-player/Inventory.json",
                evidence.source_file or "",
            )
            self.assertIn("WorldStorageEntities.json", evidence.source_file or "")
            self.assertTrue(evidence.supporting_evidence_ids)
            self.assertTrue(evidence.calculation)
            self.assertTrue(evidence.limitations)

    def test_history_and_recommendations_reference_semantic_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_a = root / "one.zip"
            archive_b = root / "two.zip"
            create_save_zip(
                archive_a,
                files=campaign_files(
                    day=1,
                    balance=20,
                    native_campaign_id="round3-evidence",
                ),
            )
            create_save_zip(
                archive_b,
                files=campaign_files(
                    day=2,
                    balance=25,
                    native_campaign_id="round3-evidence",
                ),
            )
            database = AlquimistaDatabase(root / "memory.sqlite3")
            first = _import_archive(database, archive_a)
            _import_archive(database, archive_b)
            analysis = database.analyze_and_persist(first.campaign_id)
            all_evidence = {
                item.evidence_id: item
                for item in (
                    *analysis.facts,
                    *analysis.derived,
                    *analysis.inferences,
                    *analysis.unavailable,
                    *(
                        evidence
                        for recommendation in analysis.recommendations
                        for evidence in (
                            *recommendation.supporting_evidence,
                            *recommendation.contradictory_evidence,
                        )
                    ),
                )
            }
            history = next(
                item
                for item in analysis.inferences
                if item.field_name == "campaign_has_history"
            )
            self.assertEqual(len(history.supporting_evidence_ids), 1)
            count = all_evidence[history.supporting_evidence_ids[0]]
            self.assertEqual(count.field_name, "snapshot_count")
            self.assertEqual(count.normalized_value, 2)
            self.assertEqual(count.related_entity, first.campaign_id)

            for evidence in all_evidence.values():
                for supporting_id in evidence.supporting_evidence_ids:
                    self.assertIn(supporting_id, all_evidence)
                if evidence.category == "derived":
                    self.assertTrue(evidence.calculation)
                    self.assertTrue(evidence.limitations)
                if evidence.category == "inferred":
                    self.assertTrue(evidence.supporting_evidence_ids)
                    self.assertTrue(evidence.calculation)
                    self.assertNotEqual(evidence.confidence, "unavailable")
                    self.assertTrue(evidence.limitations)
            for recommendation in analysis.recommendations:
                self.assertTrue(recommendation.supporting_evidence)
                if recommendation.rule_id == "liquidity.minimum-buffer.v1":
                    self.assertEqual(
                        recommendation.supporting_evidence[0].field_name,
                        "liquid_cash_estimate",
                    )
                self.assertNotIn(
                    "somente a campos observados",
                    recommendation.confidence_justification,
                )

            latest_snapshot_id = database.campaign_history(first.campaign_id)[-1][
                "snapshot_id"
            ]
            referenced_ids = {
                evidence_id
                for item in all_evidence.values()
                for evidence_id in item.supporting_evidence_ids
            }
            with closing(sqlite3.connect(database.path)) as connection:
                persisted_ids = {
                    row[0]
                    for row in connection.execute(
                        "SELECT id FROM evidence WHERE snapshot_id = ?",
                        (latest_snapshot_id,),
                    )
                }
            self.assertTrue(referenced_ids <= persisted_ids)

    def test_unavailable_is_not_presented_as_observed(self) -> None:
        evidence = snapshot_evidence({"availability": {"vehicles": {
            "state": "missing",
            "source_files": ["Vehicles.json"],
            "explanation": "arquivo opcional ausente",
        }}})
        unavailable = next(item for item in evidence if item.field_name == "vehicles")
        self.assertEqual(unavailable.category, "unavailable")
        self.assertEqual(unavailable.confidence, "unavailable")
        self.assertIsNone(unavailable.raw_value)
        self.assertIsNone(unavailable.normalized_value)

    def test_legacy_numeric_and_string_decimal_have_equivalent_evidence(self) -> None:
        legacy = loads_snapshot(
            '{"finance":{"online_balance":20.10,"loose_cash":1.20,'
            '"liquid_cash_estimate":21.30},"inventory":{"origins":[]}}'
        )
        current = loads_snapshot(
            '{"finance":{"online_balance":"20.10","loose_cash":"1.20",'
            '"liquid_cash_estimate":"21.30"},"inventory":{"origins":[]}}'
        )
        self.assertEqual(
            [item.to_dict() for item in snapshot_evidence(legacy)],
            [item.to_dict() for item in snapshot_evidence(current)],
        )

    def test_evidence_ids_ignore_operational_import_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "evidence-id.zip"
            create_save_zip(archive)
            snapshot = snapshot_from_zip(archive).to_dict()
            first = copy.deepcopy(snapshot)
            second = copy.deepcopy(snapshot)
            first["metadata"]["imported_at"] = "2025-01-01T00:00:00Z"
            second["metadata"]["imported_at"] = "2035-01-01T00:00:00Z"

            first_ids = [item.evidence_id for item in snapshot_evidence(first)]
            second_ids = [item.evidence_id for item in snapshot_evidence(second)]
            self.assertEqual(first_ids, second_ids)
            self.assertEqual(
                first_ids,
                [item.evidence_id for item in snapshot_evidence(first)],
            )


class DefensivePersistenceTests(unittest.TestCase):
    def test_direct_persistence_rejects_unsafe_provenance_atomically(self) -> None:
        unsafe_values = (
            ("source_archive", r"C:\synthetic\save.zip"),
            ("save_root", r"C:\synthetic\save"),
            ("source_archive", "C:/synthetic/save.zip"),
            ("source_archive", r"\\server\share\save.zip"),
            ("save_root", "//server/share/save.zip"),
            ("save_root", "/home/user/save.zip"),
            ("source_archive", "/var/data/save.zip"),
            ("source_archive", "../save.zip"),
            ("save_root", r"..\save.zip"),
            ("source_archive", "folder/../../save.zip"),
            ("save_root", "arquivo:stream"),
            ("source_archive", "file:///home/user/save.zip"),
            ("save_root", "~/save.zip"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "safe.zip"
            create_save_zip(
                archive,
                files=campaign_files(native_campaign_id="round3-persistence"),
            )
            snapshot, fingerprint = snapshot_and_fingerprint_from_zip(archive)
            identity = resolve_campaign_identity(snapshot, fingerprint)
            database = AlquimistaDatabase(root / "memory.sqlite3")
            database.initialize()

            for field_name, unsafe in unsafe_values:
                with self.subTest(field=field_name, path=unsafe):
                    metadata = replace(
                        snapshot.metadata,
                        **{field_name: unsafe},
                    )
                    bad_snapshot = replace(snapshot, metadata=metadata)
                    with self.assertRaises(UnsafeProvenanceError) as caught:
                        database.persist_import(bad_snapshot, fingerprint, identity)
                    self.assertNotIn(unsafe, str(caught.exception))
                    with closing(sqlite3.connect(database.path)) as connection:
                        for table in (
                            "archive_fingerprints",
                            "campaigns",
                            "imports",
                            "snapshots",
                            "timeline_entries",
                            "evidence",
                            "campaign_identity_signals",
                            "campaign_associations",
                            "campaign_milestones",
                            "milestones",
                            "recommendations",
                        ):
                            self.assertEqual(
                                connection.execute(
                                    f"SELECT COUNT(*) FROM {table}"
                                ).fetchone()[0],
                                0,
                            )
                        self.assertEqual(connection.execute("SELECT 1").fetchone()[0], 1)

            valid_metadata = replace(
                snapshot.metadata,
                source_archive="exports/save.zip",
                save_root="nested/logical-save",
            )
            persisted = database.persist_import(
                replace(snapshot, metadata=valid_metadata),
                fingerprint,
                identity,
            )
            self.assertFalse(persisted.deduplicated)
            stored = database.snapshot_record(persisted.snapshot_id)["snapshot"]
            serialized = json_dumps(stored, sort_keys=True)
            self.assertNotIn(str(root.resolve()), serialized)
            self.assertIn("nested/logical-save", serialized)

    def test_campaign_evidence_provenance_is_validated_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "identity.zip"
            create_save_zip(
                archive,
                files=campaign_files(native_campaign_id="round3-identity-origin"),
            )
            snapshot, fingerprint = snapshot_and_fingerprint_from_zip(archive)
            identity = resolve_campaign_identity(snapshot, fingerprint)
            malicious_evidence = replace(
                identity.evidence[0],
                source_path="../private/value",
            )
            malicious_identity = replace(
                identity,
                evidence=(malicious_evidence,),
            )
            database = AlquimistaDatabase(root / "memory.sqlite3")

            with self.assertRaises(UnsafeProvenanceError) as caught:
                database.persist_import(
                    snapshot,
                    fingerprint,
                    malicious_identity,
                )

            self.assertNotIn("../private/value", str(caught.exception))
            self.assertFalse(database.path.exists())

    def test_data_origin_is_also_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "safe.zip"
            create_save_zip(
                archive,
                files=campaign_files(native_campaign_id="round3-origin"),
            )
            snapshot, fingerprint = snapshot_and_fingerprint_from_zip(archive)
            identity = resolve_campaign_identity(snapshot, fingerprint)
            malicious_origin = replace(
                snapshot.finance.origins["online_balance"],
                file="/private/Money.json",
            )
            finance = replace(
                snapshot.finance,
                origins={
                    **snapshot.finance.origins,
                    "online_balance": malicious_origin,
                },
            )
            database = AlquimistaDatabase(root / "memory.sqlite3")
            with self.assertRaises(UnsafeProvenanceError):
                database.persist_import(
                    replace(snapshot, finance=finance),
                    fingerprint,
                    identity,
                )
            self.assertFalse(database.path.exists())


class ZipDomainErrorTests(unittest.TestCase):
    def _archive(self, root: Path, name: str) -> Path:
        archive = root / name
        create_save_zip(archive)
        return archive

    def test_corrupt_crc_is_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = self._archive(Path(temporary), "crc.zip")
            _mutate_member_payload(archive, "Money.json")
            with self.assertRaises(InvalidArchiveError):
                snapshot_from_zip(archive)

    def test_corrupt_central_directory_is_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = self._archive(Path(temporary), "central.zip")
            data = archive.read_bytes().replace(b"PK\x01\x02", b"ZZ\x01\x02", 1)
            archive.write_bytes(data)
            with self.assertRaises(InvalidArchiveError):
                snapshot_from_zip(archive)

    def test_encrypted_entry_is_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = self._archive(Path(temporary), "encrypted.zip")
            _set_zip_member_bits(archive, "Money.json", encrypted=True)
            with self.assertRaisesRegex(InvalidArchiveError, "criptografada"):
                snapshot_from_zip(archive)

    def test_unsupported_compression_is_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = self._archive(Path(temporary), "unsupported.zip")
            _set_zip_member_bits(
                archive,
                "Money.json",
                compression_method=99,
            )
            with self.assertRaisesRegex(InvalidArchiveError, "não suportado"):
                snapshot_from_zip(archive)

    def test_truncated_member_is_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = self._archive(Path(temporary), "truncated.zip")
            _declare_truncated_member(archive, "Money.json")
            with self.assertRaises(InvalidArchiveError):
                snapshot_from_zip(archive)

    def test_failure_during_member_read_is_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = self._archive(Path(temporary), "read.zip")
            with patch(
                "zipfile.ZipExtFile.read",
                side_effect=zipfile.BadZipFile("synthetic read failure"),
            ):
                with self.assertRaises(InvalidArchiveError):
                    snapshot_from_zip(archive)

    def test_expected_zipfile_open_errors_are_domain_errors(self) -> None:
        errors = (
            RuntimeError("password required for extraction"),
            NotImplementedError("synthetic unsupported compressor"),
        )
        for error in errors:
            with (
                self.subTest(error=type(error).__name__),
                tempfile.TemporaryDirectory() as temporary,
            ):
                archive = self._archive(Path(temporary), "open-error.zip")
                with patch("zipfile.ZipFile.open", side_effect=error):
                    with self.assertRaises(InvalidArchiveError):
                        snapshot_from_zip(archive)

    def test_programming_errors_are_not_masked_as_archive_errors(self) -> None:
        for error in (
            AssertionError("synthetic assertion"),
            TypeError("synthetic type failure"),
        ):
            with (
                self.subTest(error=type(error).__name__),
                tempfile.TemporaryDirectory() as temporary,
            ):
                archive = self._archive(Path(temporary), "programming-error.zip")
                with patch(
                    "o_alquimista.archive._copy_member_limited",
                    side_effect=error,
                ):
                    with self.assertRaises(type(error)):
                        snapshot_from_zip(archive)

    def test_cli_crc_failure_is_clean_read_only_and_cleans_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = self._archive(root, "crc-cli.zip")
            _mutate_member_payload(archive, "Money.json")
            original = archive.read_bytes()
            output = root / "output"
            created_directories: list[Path] = []
            real_temporary_directory = tempfile.TemporaryDirectory

            def tracking_temporary_directory(*args: object, **kwargs: object):
                kwargs["dir"] = root
                context = real_temporary_directory(*args, **kwargs)
                created_directories.append(Path(context.name))
                return context

            stderr = io.StringIO()
            with (
                patch(
                    "o_alquimista.archive.tempfile.TemporaryDirectory",
                    side_effect=tracking_temporary_directory,
                ),
                patch(
                    "o_alquimista.parser.fingerprint_archive",
                    wraps=fingerprint_archive,
                ) as fingerprint,
                redirect_stderr(stderr),
            ):
                exit_code = main(["snapshot", str(archive), "--out", str(output)])

            error = stderr.getvalue()
            self.assertEqual(exit_code, 2)
            self.assertNotIn("Traceback", error)
            self.assertNotIn(str(root.resolve()), error)
            self.assertEqual(archive.read_bytes(), original)
            self.assertEqual(fingerprint.call_count, 2)
            self.assertTrue(created_directories)
            self.assertTrue(
                all(not directory.exists() for directory in created_directories)
            )
            self.assertFalse(output.exists())

    def test_cli_zip_failure_matrix_is_clean_and_atomic(self) -> None:
        cases = (
            ("invalid", lambda path: path.write_bytes(b"not a zip")),
            (
                "central",
                lambda path: path.write_bytes(
                    path.read_bytes().replace(b"PK\x01\x02", b"ZZ\x01\x02", 1)
                ),
            ),
            ("crc", lambda path: _mutate_member_payload(path, "Money.json")),
            (
                "encrypted",
                lambda path: _set_zip_member_bits(
                    path,
                    "Money.json",
                    encrypted=True,
                ),
            ),
            (
                "unsupported",
                lambda path: _set_zip_member_bits(
                    path,
                    "Money.json",
                    compression_method=99,
                ),
            ),
            (
                "truncated",
                lambda path: _declare_truncated_member(path, "Money.json"),
            ),
        )
        for case_name, mutate in cases:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = self._archive(root, f"{case_name}.zip")
                database = root / "memory.sqlite3"
                mutate(archive)
                original = archive.read_bytes()
                created_directories: list[Path] = []
                real_temporary_directory = tempfile.TemporaryDirectory

                def tracking_temporary_directory(
                    *args: object,
                    **kwargs: object,
                ):
                    kwargs["dir"] = root
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
                        [
                            "import",
                            str(archive),
                            "--database",
                            str(database),
                        ]
                    )

                error = stderr.getvalue()
                self.assertEqual(exit_code, 2)
                self.assertNotIn("Traceback", error)
                self.assertNotIn(str(root.resolve()), error)
                self.assertEqual(archive.read_bytes(), original)
                self.assertTrue(
                    all(not path.exists() for path in created_directories)
                )
                self.assertFalse(database.exists())

    def test_simulated_extraction_failure_is_domain_error_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = self._archive(root, "extraction.zip")
            database = root / "memory.sqlite3"
            original = archive.read_bytes()
            created_directories: list[Path] = []
            real_temporary_directory = tempfile.TemporaryDirectory

            def tracking_temporary_directory(*args: object, **kwargs: object):
                kwargs["dir"] = root
                context = real_temporary_directory(*args, **kwargs)
                created_directories.append(Path(context.name))
                return context

            stderr = io.StringIO()
            with (
                patch(
                    "o_alquimista.archive.tempfile.TemporaryDirectory",
                    side_effect=tracking_temporary_directory,
                ),
                patch(
                    "o_alquimista.archive._copy_member_limited",
                    side_effect=EOFError("synthetic truncated stream"),
                ),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    ["import", str(archive), "--database", str(database)]
                )

            self.assertEqual(exit_code, 2)
            self.assertNotIn("Traceback", stderr.getvalue())
            self.assertNotIn(str(root.resolve()), stderr.getvalue())
            self.assertEqual(archive.read_bytes(), original)
            self.assertTrue(created_directories)
            self.assertTrue(
                all(not path.exists() for path in created_directories)
            )
            self.assertFalse(database.exists())


class FutureSchemaTests(unittest.TestCase):
    def test_future_schema_is_rejected_without_any_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "future.sqlite3"
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute(
                    "CREATE TABLE future_sentinel (value TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO future_sentinel VALUES ('preserve-me')"
                )
                connection.execute("PRAGMA user_version = 4")
                connection.commit()

            before = database_path.read_bytes()
            database = AlquimistaDatabase(database_path)
            for attempt in range(2):
                with self.subTest(attempt=attempt):
                    with self.assertRaisesRegex(
                        UnsupportedDatabaseVersionError,
                        "mais nova",
                    ):
                        database.initialize()
                    self.assertEqual(database_path.read_bytes(), before)

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    ["history", "--database", str(database_path)]
                )
            self.assertEqual(exit_code, 2)
            self.assertIn("mais nova", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
            self.assertNotIn(str(database_path.resolve()), stderr.getvalue())
            self.assertEqual(database_path.read_bytes(), before)

            with closing(sqlite3.connect(database_path)) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0],
                    4,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT value FROM future_sentinel"
                    ).fetchone()[0],
                    "preserve-me",
                )
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                self.assertEqual(tables, {"future_sentinel"})
                self.assertEqual(connection.execute("SELECT 1").fetchone()[0], 1)

    def test_very_future_schema_is_also_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "future-999.sqlite3"
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute("CREATE TABLE sentinel (value TEXT)")
                connection.execute("INSERT INTO sentinel VALUES ('unchanged')")
                connection.execute("PRAGMA user_version = 999")
                connection.commit()
            before = database_path.read_bytes()

            with self.assertRaisesRegex(
                UnsupportedDatabaseVersionError,
                "versão compatível",
            ):
                AlquimistaDatabase(database_path).initialize()

            self.assertEqual(database_path.read_bytes(), before)
            with closing(sqlite3.connect(database_path)) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0],
                    999,
                )
                self.assertEqual(
                    connection.execute("SELECT value FROM sentinel").fetchone()[0],
                    "unchanged",
                )
