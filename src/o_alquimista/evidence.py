"""Construção determinística de fatos, cálculos e indisponibilidades."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .memory_models import ConfidenceLevel, Evidence


def deterministic_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(
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
) -> Evidence:
    return Evidence(
        evidence_id=deterministic_id(
            "evidence",
            "derived",
            sources,
            field_name,
            value,
            calculation,
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
) -> Evidence:
    return Evidence(
        evidence_id=deterministic_id(
            "evidence",
            "unavailable",
            field_name,
            related_entity,
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
        missing_information=(field_name,),
    )


def snapshot_evidence(snapshot: dict[str, Any]) -> tuple[Evidence, ...]:
    """Extrai um conjunto pequeno e explicável de evidências principais."""
    evidence: list[Evidence] = []
    finance = snapshot.get("finance")
    if isinstance(finance, dict):
        for field_name, source_field in (
            ("online_balance", "OnlineBalance"),
            ("networth", "Networth"),
            ("lifetime_earnings", "LifetimeEarnings"),
        ):
            if field_name in finance and finance[field_name] is not None:
                evidence.append(
                    observed_evidence(
                        source_file="Money.json",
                        source_path=source_field,
                        field_name=field_name,
                        value=finance[field_name],
                        explanation=f"{field_name} observado diretamente no save.",
                        related_entity="finance",
                    )
                )
        if finance.get("liquid_cash_estimate") is not None:
            evidence.append(
                derived_evidence(
                    sources=("Money.json", "Players/*/Inventory.json"),
                    field_name="liquid_cash_estimate",
                    value=finance["liquid_cash_estimate"],
                    calculation="online_balance + dinheiro físico observado",
                    explanation="Estimativa derivada de dois valores observados.",
                    related_entity="finance",
                    confidence="medium",
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
    return tuple(sorted(evidence, key=lambda item: item.evidence_id))
