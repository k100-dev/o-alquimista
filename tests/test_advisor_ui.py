from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from o_alquimista.advisor import answer_mentor_question, build_dashboard
from o_alquimista.database import AlquimistaDatabase
from o_alquimista.errors import AdvisorUiError
from o_alquimista.ui_server import (
    UI_ROOT,
    handler_factory,
    serve_ui,
)

from tests.test_milestone3 import _create_zip, _save_files


def _multipart(filename: str, payload: bytes) -> tuple[str, bytes]:
    boundary = "alquimista-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="archive"; '
        f'filename="{filename}"\r\n'
        "Content-Type: application/zip\r\n\r\n"
    ).encode("utf-8")
    body += payload
    body += f"\r\n--{boundary}--\r\n".encode("utf-8")
    return f"multipart/form-data; boundary={boundary}", body


class AdvisorProjectionTests(unittest.TestCase):
    def test_empty_database_returns_import_invitation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = AlquimistaDatabase(Path(temporary) / "advisor.sqlite3")

            dashboard = build_dashboard(database)

            self.assertEqual(dashboard["status"], "empty")
            self.assertEqual(dashboard["campaigns"], [])
            self.assertIn("Importe", dashboard["message"]["title"])

    def test_dashboard_is_curated_after_real_parser_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "save.zip"
            database_path = root / "advisor.sqlite3"
            _create_zip(archive)
            content_type, body = _multipart(archive.name, archive.read_bytes())
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                handler_factory(database_path),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection(
                    "127.0.0.1",
                    server.server_port,
                    timeout=10,
                )
                connection.request(
                    "POST",
                    "/api/import",
                    body=body,
                    headers={
                        "Content-Type": content_type,
                        "Content-Length": str(len(body)),
                    },
                )
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(response.status, 200)
            dashboard = payload["dashboard"]
            self.assertEqual(dashboard["status"], "ready")
            self.assertEqual(dashboard["operations"]["equipment_count"], 4)
            self.assertEqual(dashboard["operations"]["productive_count"], 3)
            self.assertEqual(dashboard["operations"]["storage_count"], 1)
            self.assertEqual(dashboard["operations"]["active_count"], 2)
            self.assertEqual(dashboard["operations"]["unknown_state_count"], 2)
            self.assertEqual(dashboard["properties"][0]["name"], "laboratory")
            self.assertIn("diagnostic", dashboard)
            self.assertTrue(dashboard["action_plan"])
            self.assertIn("portfolio", dashboard)
            self.assertIn("workforce", dashboard)
            self.assertIn("availability", dashboard)
            self.assertEqual(
                dashboard["story"]["chapter_id"],
                "awakening",
            )
            self.assertEqual(len(dashboard["story"]["path"]), 4)
            self.assertTrue(dashboard["quests"])
            self.assertIn("ritual", dashboard["quests"][0])
            self.assertTrue(dashboard["achievements"])
            serialized = json.dumps(dashboard, ensure_ascii=False)
            self.assertNotIn("unknown_fields", serialized)
            self.assertNotIn('"raw"', serialized)
            self.assertNotIn("synthetic-storage-guid", serialized)

    def test_comparison_endpoint_projects_safe_exploratory_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "advisor.sqlite3"
            first = root / "first.zip"
            second = root / "second.zip"
            _create_zip(first)
            files = _save_files()
            files["Money.json"]["Networth"] = 260
            files["Time.json"]["ElapsedDays"] = 2
            _create_zip(second, files)
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                handler_factory(database_path),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            campaign_ids: list[str] = []
            snapshot_ids: list[str] = []
            try:
                for archive in (first, second):
                    content_type, body = _multipart(
                        archive.name,
                        archive.read_bytes(),
                    )
                    connection = http.client.HTTPConnection(
                        "127.0.0.1",
                        server.server_port,
                        timeout=10,
                    )
                    connection.request(
                        "POST",
                        "/api/import",
                        body=body,
                        headers={
                            "Content-Type": content_type,
                            "Content-Length": str(len(body)),
                        },
                    )
                    response = connection.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
                    connection.close()
                    self.assertEqual(response.status, 200)
                    campaign_ids.append(payload["import"]["campaign_id"])
                    snapshot_ids.append(payload["import"]["snapshot_id"])
                query = (
                    "/api/comparison?"
                    f"current_campaign_id={campaign_ids[1]}&"
                    f"baseline_campaign_id={campaign_ids[0]}&"
                    f"current_snapshot_id={snapshot_ids[1]}&"
                    f"baseline_snapshot_id={snapshot_ids[0]}"
                )
                connection = http.client.HTTPConnection(
                    "127.0.0.1",
                    server.server_port,
                    timeout=10,
                )
                connection.request("GET", query)
                response = connection.getresponse()
                comparison = json.loads(response.read().decode("utf-8"))
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(response.status, 200)
            networth = next(
                item
                for item in comparison["financial_changes"]
                if item["field"] == "networth"
            )
            self.assertEqual(networth["absolute_change"], "60.00")
            self.assertIn(
                comparison["relation"],
                {"same_campaign", "candidate", "independent"},
            )
            serialized = json.dumps(comparison, ensure_ascii=False)
            self.assertNotIn("unknown_fields", serialized)
            self.assertNotIn('"raw"', serialized)
            self.assertNotIn("synthetic-storage-guid", serialized)

    def test_mentor_answers_are_grounded_and_available_through_local_api(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "advisor.sqlite3"
            archive = root / "save.zip"
            _create_zip(archive)
            content_type, body = _multipart(archive.name, archive.read_bytes())
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                handler_factory(database_path),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection(
                    "127.0.0.1",
                    server.server_port,
                    timeout=10,
                )
                connection.request(
                    "POST",
                    "/api/import",
                    body=body,
                    headers={
                        "Content-Type": content_type,
                        "Content-Length": str(len(body)),
                    },
                )
                response = connection.getresponse()
                imported = json.loads(response.read().decode("utf-8"))
                connection.close()
                self.assertEqual(response.status, 200)

                mentor_body = json.dumps(
                    {
                        "campaign_id": imported["import"]["campaign_id"],
                        "question": "Posso expandir com segurança?",
                    }
                ).encode("utf-8")
                connection = http.client.HTTPConnection(
                    "127.0.0.1",
                    server.server_port,
                    timeout=10,
                )
                connection.request(
                    "POST",
                    "/api/mentor",
                    body=mentor_body,
                    headers={
                        "Content-Type": "application/json",
                        "Content-Length": str(len(mentor_body)),
                    },
                )
                response = connection.getresponse()
                reply = json.loads(response.read().decode("utf-8"))
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(response.status, 200)
            self.assertEqual(reply["topic"], "expansion")
            self.assertTrue(reply["evidence"])
            self.assertTrue(reply["action"])
            self.assertIn("ROI", reply["caution"])
            serialized = json.dumps(reply, ensure_ascii=False)
            self.assertNotIn("unknown_fields", serialized)
            self.assertNotIn('"raw"', serialized)

    def test_mentor_rejects_empty_question(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = AlquimistaDatabase(Path(temporary) / "advisor.sqlite3")
            with self.assertRaisesRegex(ValueError, "Escreva uma pergunta"):
                answer_mentor_question(
                    database,
                    campaign_id="campaign",
                    question="   ",
                )

    def test_static_assets_are_packaged_and_health_endpoint_is_local(self) -> None:
        for filename in ("index.html", "styles.css", "app.js"):
            self.assertTrue((UI_ROOT / filename).is_file(), filename)
        self.assertTrue(
            (UI_ROOT / "assets" / "alchemist-portrait-v1.png").is_file()
        )
        html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="mentor"', html)
        self.assertIn('id="session-review"', html)

        with tempfile.TemporaryDirectory() as temporary:
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                handler_factory(Path(temporary) / "advisor.sqlite3"),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection(
                    "127.0.0.1",
                    server.server_port,
                    timeout=10,
                )
                connection.request("GET", "/api/health")
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                headers = dict(response.getheaders())
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(response.status, 200)
            self.assertEqual(payload["product"], "O Alquimista")
            self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

    def test_server_rejects_non_local_bind_address(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(AdvisorUiError):
                serve_ui(
                    Path(temporary) / "advisor.sqlite3",
                    host="0.0.0.0",
                    open_browser=False,
                )


if __name__ == "__main__":
    unittest.main()
