"""Validação de caminhos lógicos preservados como proveniência."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from .errors import UnsafeProvenanceError

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_PROVENANCE_KEYS = frozenset(
    {
        "file",
        "source_file",
        "source_files",
        "source_archive",
        "save_root",
    }
)


def _logical_path_is_safe(value: str) -> bool:
    if "\x00" in value or not value.strip():
        return False
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or _WINDOWS_DRIVE.match(normalized):
        return False
    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        return False
    if any(":" in part for part in parts):
        return False
    return True


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _strings(child)
    elif (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
    ):
        for child in value:
            yield from _strings(child)
    elif isinstance(value, str):
        yield value


def _looks_absolute(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return normalized.startswith("/") or bool(_WINDOWS_DRIVE.match(normalized))


def _provenance_values(
    value: Any,
    *,
    parent_key: str | None = None,
) -> Iterator[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key)
            yield from _provenance_values(child, parent_key=name)
        return
    if (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
    ):
        for child in value:
            yield from _provenance_values(child, parent_key=parent_key)
        return
    if parent_key in _PROVENANCE_KEYS and isinstance(value, str):
        yield parent_key, value


def validate_snapshot_provenance(snapshot: Mapping[str, Any]) -> None:
    """Rejeita proveniência que revele ou escape para caminhos locais reais."""
    if any(_looks_absolute(value) for value in _strings(snapshot)):
        raise UnsafeProvenanceError(
            "O snapshot contém caminho absoluto; use somente proveniência lógica."
        )
    for field_name, value in _provenance_values(snapshot):
        if not _logical_path_is_safe(value):
            raise UnsafeProvenanceError(
                f"Proveniência insegura no campo {field_name}; "
                "use somente caminho lógico relativo."
            )
