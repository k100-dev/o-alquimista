"""Interface de linha de comando do O Alquimista."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

from .analysis import compare_snapshots
from .database import AlquimistaDatabase
from .diff import diff_snapshots
from .errors import AlquimistaError, UnsafeArchiveError
from .identity import resolve_campaign_identity
from .memory_reports import (
    build_analysis_markdown,
    build_comparison_markdown,
    build_timeline_markdown,
)
from .parser import (
    read_save_model,
    snapshot_and_fingerprint_from_zip,
    snapshot_from_zip,
)
from .report import build_markdown


def _json_text(data: object) -> str:
    return json.dumps(
        data,
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_text(data), encoding="utf-8")


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        dest="output_format",
    )
    parser.add_argument("--out", type=Path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alquimista",
        description="Companion estratégico read-only para Schedule I",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    import_command = subcommands.add_parser(
        "import",
        help="Importa um Export Save ZIP de forma idempotente",
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
        help="Compara arquivos snapshot JSON (compatibilidade)",
    )
    diff_command.add_argument("previous", type=Path)
    diff_command.add_argument("current", type=Path)
    diff_command.add_argument("--out", type=Path, default=Path("output/diff.json"))

    campaign_command = subcommands.add_parser(
        "campaign",
        help="Consulta campanhas persistidas",
    )
    campaign_subcommands = campaign_command.add_subparsers(
        dest="campaign_command",
        required=True,
    )
    campaign_list = campaign_subcommands.add_parser("list", help="Lista campanhas")
    campaign_list.add_argument("--database", required=True, type=Path)
    campaign_history = campaign_subcommands.add_parser(
        "history",
        help="Exibe o histórico de uma campanha",
    )
    campaign_history.add_argument("campaign_id")
    campaign_history.add_argument("--database", required=True, type=Path)
    _add_output_options(campaign_history)

    compare_command = subcommands.add_parser(
        "compare",
        help="Compara dois snapshots persistidos",
    )
    compare_command.add_argument("snapshot_a")
    compare_command.add_argument("snapshot_b")
    compare_command.add_argument("--database", required=True, type=Path)
    compare_command.add_argument("--allow-cross-campaign", action="store_true")
    _add_output_options(compare_command)

    timeline_command = subcommands.add_parser(
        "timeline",
        help="Exibe a linha do tempo de uma campanha",
    )
    timeline_command.add_argument("campaign_id")
    timeline_command.add_argument("--database", required=True, type=Path)
    _add_output_options(timeline_command)

    analyze_command = subcommands.add_parser(
        "analyze",
        help="Gera análise determinística de uma campanha",
    )
    analyze_command.add_argument("campaign_id")
    analyze_command.add_argument("--database", required=True, type=Path)
    _add_output_options(analyze_command)
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
    if source_resolved.is_file() and any(
        output_file == source_resolved for output_file in output_files
    ):
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


def _ensure_analytical_output_is_safe(
    output: Path | None,
    database: Path,
) -> None:
    if output is None:
        return
    output_resolved = output.expanduser().resolve()
    if output_resolved.suffix.casefold() == ".zip":
        raise UnsafeArchiveError("Relatórios não podem sobrescrever arquivos ZIP.")
    if output_resolved == database.expanduser().resolve():
        raise UnsafeArchiveError("O relatório não pode sobrescrever o banco SQLite.")


def _emit(
    data: object,
    *,
    markdown: str,
    output_format: str,
    output_path: Path | None,
) -> None:
    content = markdown if output_format == "markdown" else _json_text(data)
    if output_path is None:
        print(content)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"Arquivo criado: {output_path.name}")


def _compare_command(args: argparse.Namespace) -> None:
    _ensure_analytical_output_is_safe(args.out, args.database)
    database = AlquimistaDatabase(args.database)
    previous = database.snapshot_record(args.snapshot_a)
    current = database.snapshot_record(args.snapshot_b)
    comparison = compare_snapshots(
        previous["snapshot"],
        current["snapshot"],
        previous_snapshot_id=previous["snapshot_id"],
        current_snapshot_id=current["snapshot_id"],
        previous_campaign_id=previous["campaign_id"],
        current_campaign_id=current["campaign_id"],
        allow_cross_campaign=args.allow_cross_campaign,
    )
    _emit(
        comparison.to_dict(),
        markdown=build_comparison_markdown(comparison),
        output_format=args.output_format,
        output_path=args.out,
    )


def _timeline_command(args: argparse.Namespace) -> None:
    _ensure_analytical_output_is_safe(args.out, args.database)
    entries = AlquimistaDatabase(args.database).campaign_history(args.campaign_id)
    _emit(
        {
            "campaign_id": args.campaign_id,
            "timeline": entries,
        },
        markdown=build_timeline_markdown(args.campaign_id, entries),
        output_format=args.output_format,
        output_path=args.out,
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
            snapshot, fingerprint = snapshot_and_fingerprint_from_zip(args.archive)
            identity = resolve_campaign_identity(snapshot, fingerprint)
            persisted = AlquimistaDatabase(args.database).persist_import(
                snapshot,
                fingerprint,
                identity,
            )
            if persisted.deduplicated:
                print(
                    "Arquivo já importado; importação original: "
                    f"{persisted.import_id}"
                )
            else:
                print(f"Importação registrada: {persisted.import_id}")
                print(f"Snapshot registrado: {persisted.snapshot_id}")
                print(f"Campanha: {persisted.campaign_id}")
            return 0

        if args.command == "history":
            rows = AlquimistaDatabase(args.database).history()
            print(_json_text(rows) if rows else "Nenhuma importação registrada.")
            return 0

        if args.command == "diff":
            previous = json.loads(args.previous.read_text(encoding="utf-8"))
            current = json.loads(args.current.read_text(encoding="utf-8"))
            write_json(args.out, diff_snapshots(previous, current))
            print(f"Comparação criada: {args.out.name}")
            return 0

        if args.command == "campaign":
            database = AlquimistaDatabase(args.database)
            if args.campaign_command == "list":
                print(_json_text(database.campaign_list()))
                return 0
            if args.campaign_command == "history":
                _timeline_command(args)
                return 0

        if args.command == "compare":
            _compare_command(args)
            return 0

        if args.command == "timeline":
            _timeline_command(args)
            return 0

        if args.command == "analyze":
            _ensure_analytical_output_is_safe(args.out, args.database)
            analysis = AlquimistaDatabase(args.database).analyze_and_persist(
                args.campaign_id
            )
            _emit(
                analysis.to_dict(),
                markdown=build_analysis_markdown(analysis),
                output_format=args.output_format,
                output_path=args.out,
            )
            return 0
    except (
        AlquimistaError,
        FileNotFoundError,
        ValueError,
        json.JSONDecodeError,
        OSError,
        sqlite3.Error,
    ) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
