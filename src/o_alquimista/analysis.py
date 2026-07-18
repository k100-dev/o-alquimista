"""Comparação, timeline, marcos e recomendações determinísticas."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Iterable

from .errors import CampaignMismatchError
from .evidence import (
    derived_evidence,
    deterministic_id,
    inferred_evidence,
    observed_evidence,
    snapshot_evidence,
    unavailable_evidence,
)
from .json_codec import to_finite_decimal
from .memory_models import (
    CampaignAnalysis,
    ChangeStatus,
    ConfidenceLevel,
    DetectedMilestone,
    Evidence,
    FieldChange,
    RecommendationPriority,
    SnapshotComparison,
    StrategicRecommendation,
    TimelineEntry,
)


def _decimal(value: Any) -> Decimal | None:
    return to_finite_decimal(value)


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("Resultado decimal não finito.")
    return format(value, ".2f")


def _financial_change(
    field: str,
    previous: dict[str, Any],
    current: dict[str, Any],
) -> FieldChange:
    if field not in previous or field not in current:
        return FieldChange(
            field=field,
            status="unknown",
            previous=previous.get(field),
            current=current.get(field),
            explanation="Campo ausente em pelo menos um snapshot; ausência não é zero.",
        )
    previous_value = _decimal(previous.get(field))
    current_value = _decimal(current.get(field))
    if previous_value is None or current_value is None:
        return FieldChange(
            field=field,
            status="not_comparable",
            previous=previous.get(field),
            current=current.get(field),
            explanation="Valor não numérico ou indisponível.",
        )
    delta = current_value - previous_value
    percentage = None
    if previous_value != 0:
        percentage = _decimal_text((delta / previous_value) * Decimal("100"))
    return FieldChange(
        field=field,
        status="unchanged" if delta == 0 else "changed",
        previous=_decimal_text(previous_value),
        current=_decimal_text(current_value),
        absolute_change=_decimal_text(delta),
        percentage_change=percentage,
        explanation=(
            "Percentual indisponível porque a base anterior é zero."
            if previous_value == 0
            else None
        ),
    )


def _entity_map(
    snapshot: dict[str, Any],
    section: str,
) -> dict[str, Any] | None:
    if not _section_is_observed(snapshot, section):
        return None
    if section == "products":
        products = snapshot.get("products")
        if not isinstance(products, dict) or "discovered" not in products:
            return None
        return {str(value): {"discovered": True} for value in products["discovered"]}
    if section == "inventory":
        inventory = snapshot.get("inventory")
        if not isinstance(inventory, dict) or "quantities" not in inventory:
            return None
        quantities = inventory["quantities"]
        return dict(quantities) if isinstance(quantities, dict) else None
    if section in {"properties", "businesses"}:
        values = snapshot.get(section)
        if not isinstance(values, (list, tuple)):
            return None
        return {
            str(value.get("name")): {
                "owned": value.get("owned"),
                "employee_count": value.get("employee_count"),
                "object_count": value.get("object_count"),
            }
            for value in values
            if isinstance(value, dict) and value.get("name") is not None
        }
    if section in {"vehicles", "employees"}:
        values = snapshot.get(section)
        if not isinstance(values, (list, tuple)):
            return None
        id_field = "vehicle_id" if section == "vehicles" else "employee_id"
        return {
            str(value[id_field]): {id_field: value[id_field]}
            for value in values
            if isinstance(value, dict) and value.get(id_field) is not None
        }
    if section == "progression":
        progression = snapshot.get("progression")
        if not isinstance(progression, dict):
            return None
        return {
            field: progression.get(field)
            for field in ("rank", "tier", "xp", "total_xp", "unlocked_regions")
            if field in progression
        }
    return None


def _availability_state(
    snapshot: dict[str, Any],
    section: str,
) -> str | None:
    availability = snapshot.get("availability")
    if not isinstance(availability, dict):
        return None
    section_availability = availability.get(section)
    if not isinstance(section_availability, dict):
        return None
    state = section_availability.get("state")
    return str(state) if state is not None else None


def _section_is_observed(
    snapshot: dict[str, Any],
    section: str,
) -> bool:
    state = _availability_state(snapshot, section)
    if state is not None:
        return state == "observed"
    return section in snapshot


def _operational_changes(
    previous: dict[str, Any],
    current: dict[str, Any],
    section: str,
) -> tuple[FieldChange, ...]:
    previous_map = _entity_map(previous, section)
    current_map = _entity_map(current, section)
    if previous_map is None or current_map is None:
        return (
            FieldChange(
                field=section,
                status="unknown",
                previous=None if previous_map is None else "available",
                current=None if current_map is None else "available",
                explanation="Seção ausente; ausência não foi convertida em coleção vazia.",
            ),
        )
    changes: list[FieldChange] = []
    for entity_id in sorted(set(previous_map) | set(current_map)):
        status: ChangeStatus
        if entity_id not in previous_map:
            status = "added"
        elif entity_id not in current_map:
            status = "removed"
        elif previous_map[entity_id] == current_map[entity_id]:
            status = "unchanged"
        else:
            status = "changed"
        changes.append(
            FieldChange(
                field=entity_id,
                status=status,
                previous=previous_map.get(entity_id),
                current=current_map.get(entity_id),
            )
        )
    return tuple(changes)


def compare_snapshots(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    previous_snapshot_id: str,
    current_snapshot_id: str,
    previous_campaign_id: str,
    current_campaign_id: str,
    allow_cross_campaign: bool = False,
) -> SnapshotComparison:
    if previous_campaign_id != current_campaign_id and not allow_cross_campaign:
        raise CampaignMismatchError(
            "Os snapshots pertencem a campanhas diferentes. "
            "Use override explícito para comparar mesmo assim."
        )
    finance_previous = previous.get("finance")
    finance_current = current.get("finance")
    if (
        not _section_is_observed(previous, "finance")
        or not isinstance(finance_previous, dict)
    ):
        finance_previous = {}
    if (
        not _section_is_observed(current, "finance")
        or not isinstance(finance_current, dict)
    ):
        finance_current = {}
    financial_fields = (
        "online_balance",
        "loose_cash",
        "liquid_cash_estimate",
        "networth",
        "lifetime_earnings",
        "weekly_deposit_sum",
        "inventory_list_price_estimate",
        "expenses",
    )
    financial = tuple(
        _financial_change(field, finance_previous, finance_current)
        for field in financial_fields
    )
    operational_sections = (
        "properties",
        "businesses",
        "vehicles",
        "employees",
        "products",
        "inventory",
        "capacity",
        "suppliers",
        "customers",
        "activities",
        "progression",
    )
    operational = {
        section: _operational_changes(previous, current, section)
        for section in operational_sections
    }
    campaign_id = (
        previous_campaign_id
        if previous_campaign_id == current_campaign_id
        else None
    )
    comparison_id = deterministic_id(
        "comparison",
        previous_snapshot_id,
        current_snapshot_id,
        allow_cross_campaign,
    )
    evidence = (
        derived_evidence(
            sources=("snapshots",),
            field_name="snapshot_comparison",
            value=comparison_id,
            calculation="diferença determinística campo a campo",
            explanation="Comparação derivada de dois snapshots persistidos.",
            related_entity="comparison",
            confidence="medium" if allow_cross_campaign else "high",
        ),
    )
    limitations = [
        "Despesas, fornecedores, clientes, atividades e capacidade podem estar indisponíveis."
    ]
    if allow_cross_campaign:
        limitations.append("Comparação entre campanhas diferentes foi autorizada.")
    return SnapshotComparison(
        comparison_id=comparison_id,
        campaign_id=campaign_id,
        previous_snapshot_id=previous_snapshot_id,
        current_snapshot_id=current_snapshot_id,
        cross_campaign_override=allow_cross_campaign,
        financial_changes=financial,
        operational_changes=operational,
        evidence=evidence,
        limitations=tuple(limitations),
    )


def build_timeline_entry(
    snapshot: dict[str, Any],
    *,
    snapshot_id: str,
    import_id: str,
    campaign_id: str,
    archive_hash: str,
    chronological_order: int = 0,
    milestones: Iterable[DetectedMilestone] = (),
) -> TimelineEntry:
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    finance = (
        snapshot.get("finance") if isinstance(snapshot.get("finance"), dict) else {}
    )
    progression = (
        snapshot.get("progression")
        if isinstance(snapshot.get("progression"), dict)
        else {}
    )
    evidence = snapshot_evidence(snapshot)
    properties = snapshot.get("properties")
    businesses = snapshot.get("businesses")
    employees = snapshot.get("employees")
    vehicles = snapshot.get("vehicles")
    products = snapshot.get("products")
    availability = (
        snapshot.get("availability")
        if isinstance(snapshot.get("availability"), dict)
        else {}
    )
    return TimelineEntry(
        snapshot_id=snapshot_id,
        import_id=import_id,
        campaign_id=campaign_id,
        archive_hash=archive_hash,
        observable_game_moment={
            "elapsed_days": game.get("elapsed_days"),
            "time_of_day": game.get("time_of_day"),
            "playtime_seconds": game.get("playtime_seconds"),
        },
        chronological_order=chronological_order,
        financial_summary={
            key: finance.get(key)
            for key in (
                "online_balance",
                "liquid_cash_estimate",
                "networth",
                "lifetime_earnings",
            )
        },
        operational_summary={
            "properties": (
                len(properties)
                if _section_is_observed(snapshot, "properties")
                and isinstance(properties, (list, tuple))
                else None
            ),
            "businesses": (
                len(businesses)
                if _section_is_observed(snapshot, "businesses")
                and isinstance(businesses, (list, tuple))
                else None
            ),
            "employees": (
                len(employees)
                if _section_is_observed(snapshot, "employees")
                and isinstance(employees, (list, tuple))
                else None
            ),
            "vehicles": (
                len(vehicles)
                if _section_is_observed(snapshot, "vehicles")
                and isinstance(vehicles, (list, tuple))
                else None
            ),
            "products": (
                len(products.get("discovered", []))
                if _section_is_observed(snapshot, "products")
                and isinstance(products, dict)
                else None
            ),
        },
        progression_summary={
            key: progression.get(key)
            for key in ("rank", "tier", "xp", "total_xp")
        },
        availability={
            str(key): value
            for key, value in availability.items()
            if isinstance(value, dict)
        },
        milestones=tuple(item.to_dict() for item in milestones),
        primary_evidence=tuple(
            item.to_dict()
            for item in evidence
            if item.category in {"observed", "derived"}
        ),
    )


def _sortable_value(value: Any) -> tuple[bool, Decimal, str]:
    if value is None:
        return True, Decimal("0"), ""
    numeric = _decimal(value)
    if numeric is not None:
        return False, numeric, ""
    return False, Decimal("0"), str(value)


def timeline_sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    moment = entry.get("observable_game_moment", {})
    progression = entry.get("progression_summary", {})
    return (
        _sortable_value(moment.get("elapsed_days")),
        _sortable_value(moment.get("time_of_day")),
        _sortable_value(moment.get("playtime_seconds")),
        _sortable_value(progression.get("total_xp")),
        _sortable_value(progression.get("rank")),
        _sortable_value(progression.get("tier")),
        _sortable_value(progression.get("xp")),
        entry.get("snapshot_id", ""),
    )


def _count(snapshot: dict[str, Any], section: str) -> int | None:
    if not _section_is_observed(snapshot, section):
        return None
    value = snapshot.get(section)
    return len(value) if isinstance(value, (list, tuple)) else None


def _owned_property_count(snapshot: dict[str, Any]) -> int | None:
    if not _section_is_observed(snapshot, "properties"):
        return None
    values = snapshot.get("properties")
    if not isinstance(values, (list, tuple)):
        return None
    return sum(
        1 for value in values if isinstance(value, dict) and value.get("owned") is True
    )


def _discovered_product_count(snapshot: dict[str, Any]) -> int | None:
    if not _section_is_observed(snapshot, "products"):
        return None
    products = snapshot.get("products")
    if not isinstance(products, dict):
        return None
    discovered = products.get("discovered")
    return len(discovered) if isinstance(discovered, (list, tuple)) else None


def detect_milestones(
    history: Iterable[dict[str, Any]] | dict[str, Any] | None,
    current: dict[str, Any],
    *,
    campaign_id: str,
    current_snapshot_id: str,
    previous_snapshot_id: str | None,
) -> tuple[DetectedMilestone, ...]:
    if history is None:
        historical_snapshots: tuple[dict[str, Any], ...] = ()
    elif isinstance(history, dict):
        historical_snapshots = (history,)
    else:
        historical_snapshots = tuple(history)
    previous = historical_snapshots[-1] if historical_snapshots else None
    milestones: list[DetectedMilestone] = []

    def first_observed(
        milestone_type: str,
        title: str,
        description: str,
        current_count: int | None,
        historical_counts: Iterable[int | None],
        source_file: str,
        source_path: str,
    ) -> None:
        if current_count is None or current_count <= 0:
            return
        if any(
            count is not None and count > 0
            for count in historical_counts
        ):
            return
        evidence = observed_evidence(
            source_file=source_file,
            source_path=source_path,
            field_name=f"{milestone_type}_count",
            value=current_count,
            explanation=description,
            related_entity=milestone_type,
        )
        milestones.append(
            DetectedMilestone(
                milestone_id=deterministic_id(
                    "milestone", campaign_id, milestone_type, "first"
                ),
                milestone_type=milestone_type,
                title=title,
                description=description,
                evidence=(evidence,),
                confidence="high",
                first_seen_snapshot_id=current_snapshot_id,
                previous_snapshot_id=previous_snapshot_id,
            )
        )

    first_observed(
        "first_property",
        "Primeira propriedade observada",
        "Ao menos uma propriedade possuída foi observada.",
        _owned_property_count(current),
        (
            _owned_property_count(snapshot)
            for snapshot in historical_snapshots
        ),
        "Properties/*.json",
        "IsOwned",
    )
    first_observed(
        "first_vehicle",
        "Primeiro veículo observado",
        "Ao menos um veículo foi observado.",
        _count(current, "vehicles"),
        (
            _count(snapshot, "vehicles")
            for snapshot in historical_snapshots
        ),
        "Vehicles.json",
        "Vehicles",
    )
    first_observed(
        "first_employee",
        "Primeiro funcionário observado",
        "Ao menos um funcionário foi observado.",
        _count(current, "employees"),
        (
            _count(snapshot, "employees")
            for snapshot in historical_snapshots
        ),
        "Properties/*.json",
        "Employees",
    )
    first_observed(
        "first_product",
        "Primeiro produto observado",
        "Ao menos um produto descoberto foi observado.",
        _discovered_product_count(current),
        (
            _discovered_product_count(snapshot)
            for snapshot in historical_snapshots
        ),
        "Products.json",
        "DiscoveredProducts",
    )

    if previous is not None:
        previous_networth = _decimal(
            (previous.get("finance") or {}).get("networth")
            if isinstance(previous.get("finance"), dict)
            else None
        )
        current_networth = _decimal(
            (current.get("finance") or {}).get("networth")
            if isinstance(current.get("finance"), dict)
            else None
        )
        if (
            previous_networth is not None
            and current_networth is not None
            and previous_networth > 0
        ):
            delta = current_networth - previous_networth
            percentage = (delta / previous_networth) * Decimal("100")
            if delta >= Decimal("1000") and percentage >= Decimal("25"):
                evidence = derived_evidence(
                    sources=("Money.json:Networth",),
                    field_name="networth_growth",
                    value={
                        "absolute": _decimal_text(delta),
                        "percentage": _decimal_text(percentage),
                    },
                    calculation="patrimônio atual - patrimônio anterior",
                    explanation="Aumento relevante segundo regra determinística.",
                    related_entity="finance",
                )
                milestones.append(
                    DetectedMilestone(
                        milestone_id=deterministic_id(
                            "milestone",
                            campaign_id,
                            "networth_growth",
                            current_snapshot_id,
                        ),
                        milestone_type="networth_growth",
                        title="Aumento relevante de patrimônio",
                        description=(
                            "Patrimônio cresceu pelo menos 1.000 e 25% entre snapshots."
                        ),
                        evidence=(evidence,),
                        confidence="high",
                        first_seen_snapshot_id=current_snapshot_id,
                        previous_snapshot_id=previous_snapshot_id,
                    )
                )
    return tuple(sorted(milestones, key=lambda item: item.milestone_id))


@dataclass(frozen=True, slots=True)
class RecommendationContext:
    campaign_id: str
    snapshot_id: str
    snapshot: dict[str, Any]
    snapshot_count: int


@dataclass(frozen=True, slots=True)
class RecommendationRule:
    rule_id: str
    evaluator: Callable[[RecommendationContext], StrategicRecommendation | None]


def _recommendation(
    context: RecommendationContext,
    *,
    rule_id: str,
    category: str,
    title: str,
    explanation: str,
    priority: RecommendationPriority,
    confidence: ConfidenceLevel,
    evidence: tuple[Evidence, ...],
    missing: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
) -> StrategicRecommendation:
    return StrategicRecommendation(
        recommendation_id=deterministic_id(
            "recommendation",
            context.campaign_id,
            context.snapshot_id,
            rule_id,
        ),
        category=category,
        title=title,
        explanation=explanation,
        priority=priority,
        confidence=confidence,
        supporting_evidence=evidence,
        contradictory_evidence=(),
        missing_information=missing,
        rule_id=rule_id,
        confidence_justification=(
            "Regra determinística aplicada somente a campos observados."
        ),
        limitations=limitations,
    )


def _low_liquidity_rule(
    context: RecommendationContext,
) -> StrategicRecommendation | None:
    finance = context.snapshot.get("finance")
    if not isinstance(finance, dict):
        return None
    balance = _decimal(finance.get("liquid_cash_estimate"))
    if balance is None or balance >= Decimal("100"):
        return None
    evidence = derived_evidence(
        sources=("Money.json", "Players/*/Inventory.json"),
        field_name="liquid_cash_estimate",
        value=_decimal_text(balance),
        calculation="online_balance + dinheiro físico observado",
        explanation="Liquidez estimada abaixo do limiar conservador de 100.",
        related_entity="finance",
        confidence="medium",
    )
    return _recommendation(
        context,
        rule_id="liquidity.minimum-buffer.v1",
        category="liquidez",
        title="Preservar margem de liquidez",
        explanation=(
            "A liquidez observável está abaixo do limiar da regra; evite expansão "
            "até confirmar despesas e compromissos."
        ),
        priority="high",
        confidence="medium",
        evidence=(evidence,),
        missing=("despesas", "compromissos futuros"),
        limitations=("O limiar é uma heurística local, não uma regra do jogo.",),
    )


def _operational_dependency_rule(
    context: RecommendationContext,
) -> StrategicRecommendation | None:
    properties = _owned_property_count(context.snapshot)
    employees = _count(context.snapshot, "employees")
    if properties is None or employees is None or properties <= 0 or employees > 0:
        return None
    property_evidence = observed_evidence(
        source_file="Properties/*.json",
        source_path="IsOwned",
        field_name="owned_property_count",
        value=properties,
        explanation="Propriedade possuída observada.",
        related_entity="operations",
    )
    employee_evidence = observed_evidence(
        source_file="Properties/*.json",
        source_path="Employees",
        field_name="employee_count",
        value=employees,
        explanation="Nenhum funcionário observado nas propriedades normalizadas.",
        related_entity="operations",
    )
    return _recommendation(
        context,
        rule_id="operations.owner-dependency.v1",
        category="dependência operacional",
        title="Revisar dependência operacional",
        explanation=(
            "Há propriedade possuída sem funcionários observados; avalie se tarefas "
            "repetitivas estão concentradas no jogador."
        ),
        priority="medium",
        confidence="medium",
        evidence=(property_evidence, employee_evidence),
        missing=("funções dos objetos", "horas trabalhadas"),
    )


def _insufficient_history_rule(
    context: RecommendationContext,
) -> StrategicRecommendation | None:
    if context.snapshot_count >= 2:
        return None
    evidence = unavailable_evidence(
        field_name="previous_snapshot",
        explanation="A campanha possui menos de dois snapshots.",
        related_entity="timeline",
    )
    return _recommendation(
        context,
        rule_id="memory.collect-baseline.v1",
        category="progressão",
        title="Importar um novo momento da campanha",
        explanation=(
            "Uma segunda importação permitirá calcular variações e reduzir "
            "incerteza nas recomendações."
        ),
        priority="informational",
        confidence="high",
        evidence=(evidence,),
        missing=("snapshot anterior",),
    )


RECOMMENDATION_RULES: tuple[RecommendationRule, ...] = (
    RecommendationRule("liquidity.minimum-buffer.v1", _low_liquidity_rule),
    RecommendationRule(
        "operations.owner-dependency.v1",
        _operational_dependency_rule,
    ),
    RecommendationRule("memory.collect-baseline.v1", _insufficient_history_rule),
)


def generate_recommendations(
    context: RecommendationContext,
) -> tuple[StrategicRecommendation, ...]:
    recommendations = [
        result
        for rule in RECOMMENDATION_RULES
        if (result := rule.evaluator(context)) is not None
    ]
    return tuple(
        sorted(recommendations, key=lambda item: item.recommendation_id)
    )


def build_campaign_analysis(
    campaign_id: str,
    timeline: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    milestones: Iterable[DetectedMilestone],
) -> CampaignAnalysis:
    if not snapshots:
        return CampaignAnalysis(
            campaign_id=campaign_id,
            facts=(),
            derived=(),
            inferences=(),
            milestones=tuple(milestones),
            recommendations=(),
            limitations=("Campanha sem snapshots.",),
            unavailable=(
                unavailable_evidence(
                    field_name="snapshot",
                    explanation="Nenhum snapshot persistido para a campanha.",
                ),
            ),
        )
    latest = snapshots[-1]
    latest_id = timeline[-1]["snapshot_id"]
    evidence = snapshot_evidence(latest)
    recommendations = generate_recommendations(
        RecommendationContext(
            campaign_id=campaign_id,
            snapshot_id=latest_id,
            snapshot=latest,
            snapshot_count=len(snapshots),
        )
    )
    facts = tuple(item for item in evidence if item.category == "observed")
    derived = tuple(item for item in evidence if item.category == "derived")
    unavailable = tuple(item for item in evidence if item.category == "unavailable")
    inferences: tuple[Evidence, ...] = ()
    if len(timeline) >= 2:
        base = derived[0] if derived else facts[0] if facts else None
        if base is not None:
            inferences = (
                inferred_evidence(
                    evidence_ids=(base.evidence_id,),
                    field_name="campaign_has_history",
                    value=True,
                    calculation="contagem de snapshots >= 2",
                    explanation=(
                        "A campanha possui histórico suficiente para comparações; "
                        "isso não implica tendência econômica."
                    ),
                    confidence="high",
                    related_entity="timeline",
                ),
            )
    return CampaignAnalysis(
        campaign_id=campaign_id,
        facts=facts,
        derived=derived,
        inferences=inferences,
        milestones=tuple(milestones),
        recommendations=recommendations,
        limitations=(
            "Custos, despesas, fornecedores, clientes e capacidade podem estar ausentes.",
            "Recomendações são regras determinísticas locais, não fatos observados.",
        ),
        unavailable=unavailable,
    )
