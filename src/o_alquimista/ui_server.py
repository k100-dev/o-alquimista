"""Servidor HTTP local da interface consultiva."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import webbrowser
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .advisor import build_advisor_comparison, build_dashboard
from .database import AlquimistaDatabase
from .errors import AdvisorUiError, AlquimistaError
from .identity import resolve_campaign_identity
from .json_codec import dumps as json_dumps
from .parser import snapshot_and_fingerprint_from_zip

MAX_UPLOAD_BYTES = 64 * 1024 * 1024
UI_ROOT = Path(__file__).with_name("ui")
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _json_bytes(value: object) -> bytes:
    return json_dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _uploaded_archive(
    content_type: str,
    body: bytes,
) -> tuple[str, bytes]:
    if "multipart/form-data" not in content_type.casefold():
        raise AdvisorUiError("Envie o save como formulário multipart.")
    message = BytesParser(policy=policy.default).parsebytes(
        (
            f"Content-Type: {content_type}\r\n"
            "MIME-Version: 1.0\r\n\r\n"
        ).encode("utf-8")
        + body
    )
    if not message.is_multipart():
        raise AdvisorUiError("O formulário de upload é inválido.")
    for part in message.iter_parts():
        if (
            part.get_param("name", header="content-disposition")
            != "archive"
        ):
            continue
        filename = Path(part.get_filename() or "export.zip").name
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or not payload:
            raise AdvisorUiError("O arquivo enviado está vazio.")
        if Path(filename).suffix.casefold() != ".zip":
            raise AdvisorUiError("Selecione um arquivo ZIP exportado pelo jogo.")
        return filename, payload
    raise AdvisorUiError("Nenhum arquivo foi selecionado.")


class AdvisorRequestHandler(BaseHTTPRequestHandler):
    """Handler configurado por `handler_factory` com um banco local."""

    database_path: Path

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            (
                "default-src 'self'; "
                "style-src 'self'; "
                "script-src 'self'; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "object-src 'none'; "
                "base-uri 'none'; "
                "frame-ancestors 'none'"
            ),
        )

    def _send_bytes(
        self,
        status: HTTPStatus,
        content_type: str,
        body: bytes,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_json(
        self,
        value: object,
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self._send_bytes(
            status,
            "application/json; charset=utf-8",
            _json_bytes(value),
        )

    def _local_request(self) -> bool:
        return self.client_address[0] in {"127.0.0.1", "::1"}

    def do_GET(self) -> None:  # noqa: N802 - API de BaseHTTPRequestHandler
        target = urlsplit(self.path)
        if target.path == "/api/health":
            self._send_json({"status": "ok", "product": "O Alquimista"})
            return
        if target.path == "/api/dashboard":
            query = parse_qs(target.query)
            campaign_id = query.get("campaign_id", [None])[0]
            try:
                payload = build_dashboard(
                    AlquimistaDatabase(self.database_path),
                    campaign_id=campaign_id,
                )
            except (AlquimistaError, sqlite3.Error, ValueError) as exc:
                self._send_json(
                    {"error": str(exc)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self._send_json(payload)
            return
        if target.path == "/api/comparison":
            query = parse_qs(target.query)
            current_campaign_id = query.get("current_campaign_id", [None])[0]
            baseline_campaign_id = query.get(
                "baseline_campaign_id",
                [None],
            )[0]
            if not current_campaign_id or not baseline_campaign_id:
                self._send_json(
                    {"error": "Selecione os dois momentos para comparar."},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                payload = build_advisor_comparison(
                    AlquimistaDatabase(self.database_path),
                    current_campaign_id=current_campaign_id,
                    baseline_campaign_id=baseline_campaign_id,
                )
            except (AlquimistaError, sqlite3.Error, ValueError) as exc:
                self._send_json(
                    {"error": str(exc)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self._send_json(payload)
            return
        static = STATIC_FILES.get(target.path)
        if static is None:
            self._send_json(
                {"error": "Recurso não encontrado."},
                status=HTTPStatus.NOT_FOUND,
            )
            return
        filename, content_type = static
        try:
            body = (UI_ROOT / filename).read_bytes()
        except OSError:
            self._send_json(
                {"error": "A interface não está instalada corretamente."},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        self._send_bytes(HTTPStatus.OK, content_type, body)

    def do_POST(self) -> None:  # noqa: N802 - API de BaseHTTPRequestHandler
        target = urlsplit(self.path)
        if target.path != "/api/import":
            self._send_json(
                {"error": "Recurso não encontrado."},
                status=HTTPStatus.NOT_FOUND,
            )
            return
        if not self._local_request():
            self._send_json(
                {"error": "A interface aceita somente conexões locais."},
                status=HTTPStatus.FORBIDDEN,
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            self._send_json(
                {"error": "O upload está vazio ou excede 64 MB."},
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return
        try:
            filename, payload = _uploaded_archive(
                self.headers.get("Content-Type", ""),
                self.rfile.read(length),
            )
            with tempfile.TemporaryDirectory(prefix="o-alquimista-ui-") as temporary:
                archive = Path(temporary) / filename
                archive.write_bytes(payload)
                snapshot, fingerprint = snapshot_and_fingerprint_from_zip(archive)
                identity = resolve_campaign_identity(snapshot, fingerprint)
                persisted = AlquimistaDatabase(
                    self.database_path
                ).persist_import(
                    snapshot,
                    fingerprint,
                    identity,
                )
            dashboard = build_dashboard(
                AlquimistaDatabase(self.database_path),
                campaign_id=persisted.campaign_id,
            )
        except (AlquimistaError, OSError, sqlite3.Error, ValueError) as exc:
            self._send_json(
                {"error": str(exc)},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        self._send_json(
            {
                "import": {
                    "campaign_id": persisted.campaign_id,
                    "import_id": persisted.import_id,
                    "snapshot_id": persisted.snapshot_id,
                    "deduplicated": persisted.deduplicated,
                },
                "dashboard": dashboard,
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        return


def handler_factory(database_path: Path) -> type[AdvisorRequestHandler]:
    class ConfiguredAdvisorHandler(AdvisorRequestHandler):
        pass

    ConfiguredAdvisorHandler.database_path = database_path
    return ConfiguredAdvisorHandler


def serve_ui(
    database_path: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    if host not in LOCAL_HOSTS:
        raise AdvisorUiError(
            "A interface local só pode escutar em 127.0.0.1, localhost ou ::1."
        )
    server = ThreadingHTTPServer(
        (host, port),
        handler_factory(database_path.expanduser().resolve()),
    )
    url = f"http://{host}:{server.server_port}/"
    print(f"Câmara do Alquimista disponível em {url}")
    print("Pressione Ctrl+C para encerrar.")
    if open_browser:
        threading.Timer(0.35, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
