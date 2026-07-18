"""Construção determinística de fatos, cálculos e indisponibilidades."""

from __future__ import annotations

import hashlib
from typing import Any

from .json_codec import dumps as json_dumps
from .memory_models import ConfidenceLevel, Evidence


def deterministic_id(prefix: str, *parts: Any) -> str:
    payload = json_dumps(
        parts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:24]}"


def observed_evidence(
    *,
    source_file: str,
    source_path: str,
    field_name: str,
    value: Any,
    explanation: str,
    related_entity: str | None = None,
    confidence: ConfidenceLevel = "high",
) -> Evidence:
    return Evidence(
        evidence_id=deterministic_id(
            "evidence",
            "observed",
            source_file,
            source_path,
            field_name,
            value,
        ),
        category="observed",
        source_file=source_file,
        source_path=source_path,
        field_name=field_name,
        raw_value=value,
        normalized_value=value,
        calculation=None,
        explanation=explanation,
        confidence=confidence,
        related_entity=related_entity,
    )


def derived_evidence(
    *,
    sources: tuple[str, ...],
    field_name: str,
    value: Any,
    calculation: str,
    explanation: str,
    related_entity: str | None = None,
    confidence: ConfidenceLevel = "high",
    supporting_evidence_ids: tuple[str, ...] = (),
) -> Evidence:
    return Evidence(
        evidence_id=deterministic_id(
            "evidence",
            "derived",
            sources,
            field_name,
            value,
            calculation,
            supporting_evidence_ids,
        ),
        category="derived",
        source_file=";".join(sources),
        source_path=None,
        field_name=field_name,
        raw_value=None,
        normalized_value=value,
        calculation=calculation,
        explanation=explanation,
        confidence=confidence,
        related_entity=related_entity,
        supporting_evidence_ids=supporting_evidence_ids,
    )


def inferred_evidence(
    *,
    evidence_ids: tuple[str, ...],
    field_name: str,
    value: Any,
    calculation: str,
    explanation: str,
    confidence: ConfidenceLevel,
    related_entity: str | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=deterministic_id(
            "evidence",
            "inferred",
            evidence_ids,
            field_name,
            value,
        ),
        category="inferred",
        source_file=None,
        source_path=None,
        field_name=field_name,
        raw_value=None,
        normalized_value=value,
        calculation=calculation,
        explanation=explanation,
        confidence=confidence,
        related_entity=related_entity,
        supporting_evidence_ids=evidence_ids,
        limitations=(
            "Inferência válida somente para as evidências e regra declaradas.",
        ),
    )


def unavailable_evidence(
    *,
    field_name: str,
    explanation: str,
    related_entity: str | None = None,
    supporting_evidence_ids: tuple[str, ...] = (),
) -> Evidence:
    return Evidence(
        evidence_id=deterministic_id(
            "evidence",
            "unavailable",
            field_name,
            related_entity,
            supporting_evidence_ids,
        ),
        category="unavailable",
        source_file=None,
        source_path=None,
        field_name=field_name,
        raw_value=None,
        normalized_value=None,
        calculation=None,
        explanation=explanation,
        confidence="unavailable",
        related_entity=related_entity,
        supporting_evidence_ids=supporting_evidence_ids,
        missing_information=(field_name,),
    )


def snapshot_count_evidence(
    *,
    campaign_id: str,
    snapshot_count: int,
) -> Evidence:
    """Registra a contagem persistida que sustenta conclusões sobre histórico."""
    return Evidence(
        evidence_id=deterministic_id(
            "evidence",
            "derived",
            campaign_id,
            "snapshot_count",
            snapshot_count,
        ),
        category="derived",
        source_file="<database>",
        source_path="timeline_entries.campaign_id",
        field_name="snapshot_count",
        raw_value=None,
        normalized_value=snapshot_count,
        calculation="contagem de snapshots ordenados da campanha",
        explanation=(
            "Quantidade de snapshots pertencentes à timeline desta campanha."
        ),
        confidence="high",
        related_entity=campaign_id,
    )


def _origin_files(value: Any) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ()
    origins = value.get("origins")
    if not isinstance(origins, (list, tuple)):
        return ()
    return tuple(
        sorted(
            {
                str(origin["file"])
                for origin in origins
                if isinstance(origin, dict)
                and isinstance(origin.get("file"), str)
                and origin["file"]
            }
        )
    )


def snapshot_evidence(snapshot: dict[str, Any]) -> tuple[Evidence, ...]:
    """Extrai um conjunto pequeno e explicável de evidências principais."""
    evidence: list[Evidence] = []
    finance = snapshot.get("finance")
    if isinstance(finance, dict):
        by_field: dict[str, Evidence] = {}
        for field_name, source_field in (
            ("online_balance", "OnlineBalance"),
            ("networth", "Networth"),
            ("lifetime_earnings", "LifetimeEarnings"),
        ):
            if field_name in finance and finance[field_name] is not None:
                item = observed_evidence(
                    source_file="Money.json",
                    source_path=source_field,
                    field_name=field_name,
                    value=finance[field_name],
                    explanation=f"{field_name} observado diretamente no save.",
                    related_entity="finance",
                )
                evidence.append(item)
                by_field[field_name] = item
        inventory_sources = _origin_files(snapshot.get("inventory"))
        if finance.get("loose_cash") is not None:
            loose_sources = inventory_sources or ("<normalized>/inventory",)
            loose_cash = derived_evidence(
                sources=loose_sources,
                field_name="loose_cash",
                value=finance["loose_cash"],
                calculation="soma de CashBalance dos itens de inventário observados",
                explanation=(
                    "Dinheiro físico agregado somente das fontes de inventário "
                    "registradas no snapshot."
                ),
                related_entity="finance",
                confidence="medium",
            )
            evidence.append(loose_cash)
            by_field["loose_cash"] = loose_cash
        if finance.get("liquid_cash_estimate") is not None:
            supporting_ids = tuple(
                item.evidence_id
                for field_name in ("online_balance", "loose_cash")
                if (item := by_field.get(field_name)) is not None
            )
            liquidity_sources = tuple(
                sorted(
                    {
                        "Money.json",
                        *(inventory_sources or ("<normalized>/inventory",)),
                    }
                )
            )
            evidence.append(
                derived_evidence(
                    sources=liquidity_sources,
                    field_name="liquid_cash_estimate",
                    value=finance["liquid_cash_estimate"],
                    calculation="online_balance + dinheiro físico observado",
                    explanation=(
                        "Estimativa derivada do saldo online e do dinheiro físico, "
                        "com as fontes reais do inventário preservadas."
                    ),
                    related_entity="finance",
                    confidence="medium",
                    supporting_evidence_ids=supporting_ids,
                )
            )

    game = snapshot.get("game")
    if isinstance(game, dict) and game.get("elapsed_days") is not None:
        evidence.append(
            observed_evidence(
                source_file="Time.json",
                source_path="ElapsedDays",
                field_name="elapsed_days",
                value=game["elapsed_days"],
                explanation="Dia interno observado no save.",
                related_entity="timeline",
            )
        )

    for field_name, explanation in (
        ("expenses", "Despesas não são normalizadas no schema atual."),
        ("suppliers", "Fornecedores não são normalizados no schema atual."),
        ("customers", "Clientes não são normalizados no schema atual."),
        ("capacity", "Capacidade produtiva não possui métrica comprovada."),
    ):
        evidence.append(
            unavailable_evidence(
                field_name=field_name,
                explanation=explanation,
            )
        )
    availability = snapshot.get("availability")
    if isinstance(availability, dict):
        for section, value in sorted(availability.items()):
            if not isinstance(value, dict):
                continue
            state = value.get("state")
            if state is None:
                continue
            source_files = value.get("source_files")
            sources = tuple(
                sorted(
                    str(source)
                    for source in source_files
                    if isinstance(source, str)
                )
            ) if isinstance(source_files, (list, tuple)) else ()
            if state == "observed":
                evidence.append(
                    derived_evidence(
                        sources=sources or (f"<normalized>/{section}",),
                        field_name=f"{section}_availability",
                        value="observed",
                        calculation="validação de presença e estrutura da seção",
                        explanation=(
                            f"A seção {section} foi validada como disponível; "
                            "coleções vazias continuam observadas."
                        ),
                        related_entity=str(section),
                    )
                )
                continue
            evidence.append(
                unavailable_evidence(
                    field_name=str(section),
                    explanation=(
                        f"Seção {section} está {state}: "
                        f"{value.get('explanation', 'sem detalhe adicional')}"
                    ),
                    related_entity=str(section),
                )
            )
    return tuple(sorted(evidence, key=lambda item: item.evidence_id))
