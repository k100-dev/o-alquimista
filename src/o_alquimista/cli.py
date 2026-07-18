"""Interface de linha de comando do O Alquimista."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Sequence

from .database import AlquimistaDatabase
from .diff import diff_snapshots
from .errors import AlquimistaError, UnsafeArchiveError
from .parser import read_save_model, snapshot_from_zip
from .report import build_markdown


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alquimista",
        description="Companion estratégico read-only para Schedule I",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    import_command = subcommands.add_parser(
        "import",
        help="Importa um Export Save ZIP para o histórico SQLite",
    )
    import_command.add_argument("archive", type=Path, metavar="arquivo.zip")
    import_command.add_argument("--database", required=True, type=Path)

    snapshot_command = subcommands.add_parser(
        "snapshot",
        help="Gera snapshot JSON e relatório a partir de um ZIP",
    )
    snapshot_command.add_argument("source", type=Path, metavar="arquivo.zip")
    snapshot_command.add_argument("--out", type=Path, default=Path("output"))

    history_command = subcommands.add_parser(
        "history",
        help="Lista importações persistidas",
    )
    history_command.add_argument("--database", required=True, type=Path)

    diff_command = subcommands.add_parser(
        "diff",
        help="Compara dois snapshots (compatibilidade do protótipo)",
    )
    diff_command.add_argument("previous", type=Path)
    diff_command.add_argument("current", type=Path)
    diff_command.add_argument("--out", type=Path, default=Path("output/diff.json"))
    return parser


def _snapshot_from_source(source: Path) -> dict[str, object]:
    if source.is_dir():
        return read_save_model(source).to_dict()
    return snapshot_from_zip(source).to_dict()


def _ensure_snapshot_destination_is_safe(source: Path, output: Path) -> None:
    source_resolved = source.expanduser().resolve()
    output_resolved = output.expanduser().resolve()
    output_files = tuple(
        (output_resolved / filename).resolve()
        for filename in ("snapshot.json", "report.md")
    )
    if source_resolved.is_dir():
        unsafe_destinations = (output_resolved, *output_files)
        if any(
            destination == source_resolved
            or destination.is_relative_to(source_resolved)
            for destination in unsafe_destinations
        ):
            raise UnsafeArchiveError(
                "A saída do snapshot não pode ficar dentro da pasta de save."
            )
    if source_resolved.is_file():
        for output_file in output_files:
            if output_file == source_resolved:
                raise UnsafeArchiveError(
                    "A saída do snapshot não pode sobrescrever o ZIP original."
                )


def _ensure_database_does_not_replace_archive(
    archive: Path,
    database: Path,
) -> None:
    if archive.expanduser().resolve() == database.expanduser().resolve():
        raise UnsafeArchiveError(
            "O banco SQLite não pode usar o mesmo caminho do ZIP original."
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "snapshot":
            _ensure_snapshot_destination_is_safe(args.source, args.out)
            snapshot = _snapshot_from_source(args.source)
            args.out.mkdir(parents=True, exist_ok=True)
            snapshot_path = args.out / "snapshot.json"
            report_path = args.out / "report.md"
            write_json(snapshot_path, snapshot)
            report_path.write_text(build_markdown(snapshot), encoding="utf-8")
            print(f"Snapshot criado: {snapshot_path.name}")
            print(f"Relatório criado: {report_path.name}")
            return 0

        if args.command == "import":
            _ensure_database_does_not_replace_archive(args.archive, args.database)
            snapshot = snapshot_from_zip(args.archive)
            database = AlquimistaDatabase(args.database)
            persisted = database.persist_snapshot(
                snapshot,
                campaign_name=args.archive.stem,
            )
            print(f"Importação registrada: {persisted.import_id}")
            print(f"Snapshot registrado: {persisted.snapshot_id}")
            return 0

        if args.command == "history":
            rows = AlquimistaDatabase(args.database).history()
            if not rows:
                print("Nenhuma importação registrada.")
                return 0
            print(json.dumps(rows, indent=2, ensure_ascii=False))
            return 0

        if args.command == "diff":
            previous = json.loads(args.previous.read_text(encoding="utf-8"))
            current = json.loads(args.current.read_text(encoding="utf-8"))
            write_json(args.out, diff_snapshots(previous, current))
            print(f"Comparação criada: {args.out.name}")
            return 0
    except (
        AlquimistaError,
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
        sqlite3.Error,
    ) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
