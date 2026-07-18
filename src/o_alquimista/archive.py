"""Importação temporária e segura de exports ZIP do Schedule I."""

from __future__ import annotations

import stat
import struct
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterator

from .errors import (
    AmbiguousSaveError,
    ArchiveLimitError,
    IncompleteSaveError,
    InvalidArchiveError,
    UnsafeArchiveError,
)

ESSENTIAL_FILES: tuple[str, ...] = (
    "Money.json",
    "Products.json",
    "Time.json",
    "Rank.json",
)

MAX_ARCHIVE_ENTRIES = 5_000
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_CENTRAL_DIRECTORY_BYTES = 16 * 1024 * 1024
MAX_MEMBER_NAME_LENGTH = 1_024
MAX_DIRECTORY_DEPTH = 16
MAX_MEMBER_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200.0
MIN_RATIO_CHECK_BYTES = 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024
EOCD_SIGNATURE = b"PK\x05\x06"
EOCD = struct.Struct("<4s4H2LH")
MAX_ZIP_COMMENT_BYTES = 65_535
WINDOWS_RESERVED_COMPONENTS = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)


def _preflight_central_directory(path: Path) -> None:
    """Lê o EOCD antes de permitir que ZipFile materialize todas as entradas."""
    tail_size = min(path.stat().st_size, EOCD.size + MAX_ZIP_COMMENT_BYTES)
    with path.open("rb") as source:
        source.seek(-tail_size, 2)
        tail = source.read(tail_size)

    search_end = len(tail)
    record: tuple[bytes, int, int, int, int, int, int, int] | None = None
    while search_end:
        offset = tail.rfind(EOCD_SIGNATURE, 0, search_end)
        if offset < 0:
            break
        if offset + EOCD.size <= len(tail):
            candidate = EOCD.unpack_from(tail, offset)
            comment_length = candidate[-1]
            if offset + EOCD.size + comment_length == len(tail):
                record = candidate
                break
        search_end = offset

    if record is None:
        raise InvalidArchiveError(f"O arquivo não é um ZIP válido: {path.name}")

    (
        _,
        disk_number,
        central_disk,
        entries_on_disk,
        total_entries,
        central_size,
        _,
        _,
    ) = record
    if disk_number != 0 or central_disk != 0 or entries_on_disk != total_entries:
        raise InvalidArchiveError("ZIPs divididos em múltiplos discos não são aceitos.")
    if total_entries == 0xFFFF or central_size == 0xFFFFFFFF:
        raise ArchiveLimitError("ZIP64 não é aceito para exports de save.")
    if total_entries > MAX_ARCHIVE_ENTRIES:
        raise ArchiveLimitError(
            f"O ZIP excede o limite de {MAX_ARCHIVE_ENTRIES} entradas."
        )
    if central_size > MAX_CENTRAL_DIRECTORY_BYTES:
        raise ArchiveLimitError("O diretório central do ZIP é excessivamente grande.")


def validate_archive(archive_path: Path) -> Path:
    """Valida sem modificar nem extrair o arquivo informado."""
    path = archive_path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Arquivo ZIP não encontrado: {archive_path.name}")
    if not path.is_file():
        raise InvalidArchiveError(f"O caminho não é um arquivo: {archive_path.name}")
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ArchiveLimitError(f"O ZIP excede {MAX_ARCHIVE_BYTES} bytes.")
    _preflight_central_directory(path)
    if not zipfile.is_zipfile(path):
        raise InvalidArchiveError(f"O arquivo não é um ZIP válido: {archive_path.name}")
    return path


def _is_windows_reserved_component(component: str) -> bool:
    normalized = component.rstrip(" .")
    base_name = normalized.split(".", 1)[0].rstrip(" .")
    return base_name.upper() in WINDOWS_RESERVED_COMPONENTS


def _safe_relative_path(info: zipfile.ZipInfo) -> Path:
    raw_name = info.filename.replace("\\", "/")
    if "\x00" in raw_name:
        raise UnsafeArchiveError("O ZIP contém um nome de arquivo inválido.")
    if len(raw_name) > MAX_MEMBER_NAME_LENGTH:
        raise ArchiveLimitError("O ZIP contém um nome de entrada excessivamente longo.")

    member = PurePosixPath(raw_name)
    if not member.parts:
        raise UnsafeArchiveError("O ZIP contém uma entrada sem nome.")
    if member.is_absolute() or member.anchor or any(":" in part for part in member.parts):
        raise UnsafeArchiveError(f"Entrada absoluta bloqueada: {info.filename!r}")
    if any(part in {"", ".", ".."} for part in member.parts):
        raise UnsafeArchiveError(f"Path traversal bloqueado: {info.filename!r}")
    reserved = next(
        (
            part
            for part in member.parts
            if _is_windows_reserved_component(part)
        ),
        None,
    )
    if reserved is not None:
        raise UnsafeArchiveError(
            f"Componente reservado do Windows bloqueado: {reserved!r}"
        )
    directory_depth = len(member.parts) if info.is_dir() else len(member.parts) - 1
    if directory_depth > MAX_DIRECTORY_DEPTH:
        raise ArchiveLimitError(
            f"Uma entrada excede a profundidade máxima {MAX_DIRECTORY_DEPTH}."
        )

    unix_mode = info.external_attr >> 16
    if stat.S_ISLNK(unix_mode):
        raise UnsafeArchiveError(f"Link simbólico bloqueado: {info.filename!r}")
    file_type = stat.S_IFMT(unix_mode)
    if file_type and not (stat.S_ISREG(unix_mode) or stat.S_ISDIR(unix_mode)):
        raise UnsafeArchiveError(f"Arquivo especial bloqueado: {info.filename!r}")
    return Path(*member.parts)


def _validate_resource_limits(members: list[zipfile.ZipInfo]) -> None:
    if len(members) > MAX_ARCHIVE_ENTRIES:
        raise ArchiveLimitError(
            f"O ZIP excede o limite de {MAX_ARCHIVE_ENTRIES} entradas."
        )

    total_uncompressed = 0
    for info in members:
        if info.is_dir():
            continue
        if info.file_size < 0 or info.compress_size < 0:
            raise ArchiveLimitError("O ZIP declara tamanhos de entrada inválidos.")
        if info.file_size > MAX_MEMBER_UNCOMPRESSED_BYTES:
            raise ArchiveLimitError(
                f"Uma entrada excede {MAX_MEMBER_UNCOMPRESSED_BYTES} bytes."
            )
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ArchiveLimitError(
                f"O ZIP excede {MAX_TOTAL_UNCOMPRESSED_BYTES} bytes descompactados."
            )
        if info.file_size >= MIN_RATIO_CHECK_BYTES:
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > MAX_COMPRESSION_RATIO:
                raise ArchiveLimitError(
                    f"Uma entrada excede a razão de compressão {MAX_COMPRESSION_RATIO:g}."
                )


def _copy_member_limited(
    source: zipfile.ZipExtFile,
    output: BinaryIO,
    *,
    total_written: int,
) -> tuple[int, int]:
    member_written = 0
    while True:
        chunk = source.read(COPY_CHUNK_BYTES)
        if not chunk:
            return member_written, total_written
        member_written += len(chunk)
        total_written += len(chunk)
        if member_written > MAX_MEMBER_UNCOMPRESSED_BYTES:
            raise ArchiveLimitError("Uma entrada excedeu o limite durante a extração.")
        if total_written > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ArchiveLimitError("O ZIP excedeu o limite total durante a extração.")
        output.write(chunk)


def extract_archive_safely(archive_path: Path, destination: Path) -> None:
    """Extrai membros individualmente após validar todos os caminhos."""
    destination = destination.resolve()
    with zipfile.ZipFile(archive_path, mode="r") as archive:
        members = archive.infolist()
        _validate_resource_limits(members)
        relative_paths = [_safe_relative_path(info) for info in members]
        normalized_names = [
            relative_path.as_posix().casefold()
            for relative_path in relative_paths
        ]
        if len(normalized_names) != len(set(normalized_names)):
            raise UnsafeArchiveError("O ZIP contém entradas duplicadas ou ambíguas.")
        total_written = 0

        for info, relative_path in zip(members, relative_paths, strict=True):
            target = (destination / relative_path).resolve()
            if not target.is_relative_to(destination):
                raise UnsafeArchiveError(
                    f"Entrada fora do diretório temporário bloqueada: {info.filename!r}"
                )
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, mode="r") as source, target.open("xb") as output:
                member_written, total_written = _copy_member_limited(
                    source,
                    output,
                    total_written=total_written,
                )
                if member_written != info.file_size:
                    raise InvalidArchiveError(
                        "O tamanho extraído não corresponde ao declarado pelo ZIP."
                    )


def detect_save_root(extracted_dir: Path) -> Path:
    """Localiza a pasta mais rasa que contém todos os JSONs essenciais."""
    extracted_dir = extracted_dir.resolve()
    candidates = {
        money_path.parent.resolve()
        for money_path in extracted_dir.rglob("Money.json")
        if all((money_path.parent / name).is_file() for name in ESSENTIAL_FILES)
    }
    if not candidates:
        missing = ", ".join(ESSENTIAL_FILES)
        raise IncompleteSaveError(
            f"Nenhuma raiz de save contém todos os arquivos essenciais: {missing}"
        )

    by_depth = sorted(
        candidates,
        key=lambda path: (len(path.relative_to(extracted_dir).parts), str(path).casefold()),
    )
    shallowest_depth = len(by_depth[0].relative_to(extracted_dir).parts)
    shallowest = [
        path
        for path in by_depth
        if len(path.relative_to(extracted_dir).parts) == shallowest_depth
    ]
    if len(shallowest) > 1:
        relative = ", ".join(
            str(path.relative_to(extracted_dir)) for path in shallowest
        )
        raise AmbiguousSaveError(f"Mais de uma raiz de save foi encontrada: {relative}")
    return shallowest[0]


def validate_extracted_scope(extracted_dir: Path, save_root: Path) -> None:
    """Rejeita arquivos que não pertençam à raiz lógica detectada."""
    extracted_dir = extracted_dir.resolve()
    save_root = save_root.resolve()
    for path in extracted_dir.rglob("*"):
        if path.is_file() and not path.resolve().is_relative_to(save_root):
            relative = path.relative_to(extracted_dir).as_posix()
            raise UnsafeArchiveError(
                f"Arquivo fora da raiz lógica do save bloqueado: {relative!r}"
            )


@contextmanager
def extracted_save(archive_path: Path) -> Iterator[tuple[Path, str]]:
    """Disponibiliza uma raiz de save temporária e a remove ao sair do contexto."""
    archive = validate_archive(archive_path)
    with tempfile.TemporaryDirectory(prefix="o-alquimista-") as temporary:
        temporary_dir = Path(temporary).resolve()
        extract_archive_safely(archive, temporary_dir)
        root = detect_save_root(temporary_dir)
        validate_extracted_scope(temporary_dir, root)
        relative_root = root.relative_to(temporary_dir).as_posix()
        yield root, relative_root
