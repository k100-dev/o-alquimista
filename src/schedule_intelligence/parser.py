"""Compatibilidade para imports do protótipo."""

from o_alquimista.parser import (
    decode_embedded_json,
    load_json,
    read_save,
    read_save_model,
    snapshot_from_zip,
)

__all__ = [
    "decode_embedded_json",
    "load_json",
    "read_save",
    "read_save_model",
    "snapshot_from_zip",
]
