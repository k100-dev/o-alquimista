"""Relatórios Markdown da memória de campanha."""

from __future__ import annotations

from typing import Any

from .memory_models import CampaignAnalysis, SnapshotComparison


def build_comparison_markdown(comparison: SnapshotComparison) -> str:
    lines = [
        "# O Alquimista — Comparação",
        "",
        "## Fatos observados",
        "",
        f"- Snapshot anterior: `{comparison.previous_snapshot_id}`",
        f"- Snapshot atual: `{comparison.current_snapshot_id}`",
        "",
        "## Cálculos derivados",
        "",
        "| Campo | Estado | Anterior | Atual | Variação | Variação % |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for change in comparison.financial_changes:
        lines.append(
            f"| `{change.field}` | {change.status} | "
            f"{change.previous if change.previous is not None else 'indisponível'} | "
            f"{change.current if change.current is not None else 'indisponível'} | "
            f"{change.absolute_change or 'n/a'} | "
            f"{change.percentage_change or 'n/a'} |"
        )
    lines += ["", "## Inferências", "", "- Nenhuma inferência narrativa foi gerada."]
    lines += ["", "## Recomendações", "", "- Nenhuma recomendação é derivada apenas desta comparação."]
    lines += ["", "## Limitações", ""]
    lines.extend(f"- {item}" for item in comparison.limitations)
    lines += ["", "## Dados indisponíveis", ""]
    unavailable = [
        change.field
        for change in comparison.financial_changes
        if change.status in {"unknown", "not_comparable"}
    ]
    lines.append(
        f"- {', '.join(unavailable)}" if unavailable else "- Nenhum entre os campos financeiros comparados."
    )
    return "\n".join(lines) + "\n"


def build_timeline_markdown(
    campaign_id: str,
    entries: list[dict[str, Any]],
) -> str:
    lines = [
        "# O Alquimista — Linha do tempo",
        "",
        f"Campanha: `{campaign_id}`",
        "",
        "## Fatos observados",
        "",
    ]
    if not entries:
        lines.append("- Nenhum snapshot.")
    for entry in entries:
        moment = entry.get("observable_game_moment", {})
        finance = entry.get("financial_summary", {})
        unavailable = [
            f"{section}={value.get('state')}"
            for section, value in sorted(
                (entry.get("availability") or {}).items()
            )
            if isinstance(value, dict) and value.get("state") != "observed"
        ]
        lines += [
            f"### {entry.get('chronological_order')}. `{entry.get('snapshot_id')}`",
            "",
            f"- Dia interno: {moment.get('elapsed_days', 'indisponível')}",
            f"- Tempo de jogo: {moment.get('playtime_seconds', 'indisponível')}",
            f"- Patrimônio: {finance.get('networth', 'indisponível')}",
            f"- Marcos: {len(entry.get('milestones', []))}",
            (
                "- Seções indisponíveis: "
                f"{', '.join(unavailable) if unavailable else 'nenhuma'}"
            ),
            "",
        ]
    lines += [
        "## Cálculos derivados",
        "",
        "- A ordem usa tempo interno, progressão, importação e ID como desempate.",
        "",
        "## Inferências",
        "",
        "- A ordem temporal não implica causalidade.",
        "",
        "## Recomendações",
        "",
        "- Execute `alquimista analyze` para regras estratégicas.",
        "",
        "## Limitações",
        "",
        "- Campos ausentes permanecem indisponíveis.",
        "",
        "## Dados indisponíveis",
        "",
        "- Dependem do conteúdo de cada snapshot.",
    ]
    return "\n".join(lines) + "\n"


def build_analysis_markdown(analysis: CampaignAnalysis) -> str:
    lines = [
        "# O Alquimista — Análise de campanha",
        "",
        f"Campanha: `{analysis.campaign_id}`",
        "",
        "## Fatos observados",
        "",
    ]
    lines.extend(
        f"- `{item.field_name}`: {item.normalized_value} — {item.explanation}"
        for item in analysis.facts
    )
    if not analysis.facts:
        lines.append("- Nenhum fato normalizado.")
    lines += ["", "## Cálculos derivados", ""]
    lines.extend(
        f"- `{item.field_name}`: {item.normalized_value} — {item.calculation}"
        for item in analysis.derived
    )
    if not analysis.derived:
        lines.append("- Nenhum cálculo derivado.")
    lines += ["", "## Inferências", ""]
    lines.extend(
        f"- {item.explanation} (confiança: {item.confidence})"
        for item in analysis.inferences
    )
    if not analysis.inferences:
        lines.append("- Nenhuma inferência.")
    lines += ["", "## Recomendações", ""]
    for recommendation in analysis.recommendations:
        lines += [
            f"### {recommendation.title}",
            "",
            f"- Prioridade: **{recommendation.priority}**",
            f"- Confiança: **{recommendation.confidence}**",
            f"- Regra: `{recommendation.rule_id}`",
            f"- {recommendation.explanation}",
            "",
        ]
    if not analysis.recommendations:
        lines.append("- Nenhuma regra acionada.")
    lines += ["", "## Marcos", ""]
    lines.extend(
        f"- **{milestone.title}** — {milestone.description} "
        f"(primeiro snapshot: `{milestone.first_seen_snapshot_id}`)"
        for milestone in analysis.milestones
    )
    if not analysis.milestones:
        lines.append("- Nenhum marco detectado.")
    lines += ["", "## Limitações", ""]
    lines.extend(f"- {item}" for item in analysis.limitations)
    lines += ["", "## Dados indisponíveis", ""]
    lines.extend(f"- {item.explanation}" for item in analysis.unavailable)
    if not analysis.unavailable:
        lines.append("- Nenhum dado obrigatório marcado como indisponível.")
    return "\n".join(lines) + "\n"
