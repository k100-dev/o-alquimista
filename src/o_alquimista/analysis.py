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
    snapshot_count_evidence,
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
    availability_section = "properties" if section == "equipment" else section
    if not _section_is_observed(snapshot, availability_section):
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
    if section == "equipment":
        if not _section_is_observed(snapshot, "properties"):
            return None
        properties = snapshot.get("properties")
        if not isinstance(properties, (list, tuple)):
            return None
        if not any(
            isinstance(prop, dict) and "objects" in prop
            for prop in properties
        ):
            return None
        equipment: dict[str, Any] = {}
        for prop in properties:
            if not isinstance(prop, dict):
                continue
            objects = prop.get("objects")
            if not isinstance(objects, (list, tuple)):
                continue
            for operational_object in objects:
                if not isinstance(operational_object, dict):
                    continue
                instance_id = operational_object.get("instance_id")
                if instance_id is None:
                    continue
                containers = operational_object.get("containers")
                container_values = (
                    containers if isinstance(containers, (list, tuple)) else ()
                )
                equipment[str(instance_id)] = {
                    "property": prop.get("name"),
                    "item_id": operational_object.get("item_id"),
                    "data_type": operational_object.get("data_type"),
                    "category": operational_object.get("category"),
                    "operational_state": operational_object.get(
                        "operational_state"
                    ),
                    "state": operational_object.get("state"),
                    "slot_count": sum(
                        int(container.get("slot_count", 0))
                        for container in container_values
                        if isinstance(container, dict)
                    ),
                    "occupied_slot_count": sum(
                        int(container.get("occupied_slot_count", 0))
                        for container in container_values
                        if isinstance(container, dict)
                    ),
                }
        return equipment
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
        "equipment",
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
    operational_objects = [
        operational_object
        for prop in properties or ()
        if isinstance(prop, dict)
        for operational_object in (
            prop.get("objects")
            if isinstance(prop.get("objects"), (list, tuple))
            else ()
        )
        if isinstance(operational_object, dict)
    ]
    operational_containers = [
        container
        for operational_object in operational_objects
        for container in (
            operational_object.get("containers")
            if isinstance(
                operational_object.get("containers"),
                (list, tuple),
            )
            else ()
        )
        if isinstance(container, dict)
    ]
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
            "equipment": (
                len(operational_objects)
                if _section_is_observed(snapshot, "properties")
                and isinstance(properties, (list, tuple))
                and any(
                    isinstance(prop, dict) and "objects" in prop
                    for prop in properties
                )
                else None
            ),
            "active_equipment": sum(
                1
                for operational_object in operational_objects
                if operational_object.get("operational_state") == "active"
            ),
            "observed_slots": sum(
                int(container.get("slot_count", 0))
                for container in operational_containers
            ),
            "occupied_slots": sum(
                int(container.get("occupied_slot_count", 0))
                for container in operational_containers
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
                    sources=("Money.json",),
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


def _owned_operational_objects(
    snapshot: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    properties = snapshot.get("properties")
    if (
        not _section_is_observed(snapshot, "properties")
        or not isinstance(properties, (list, tuple))
    ):
        return ()
    return tuple(
        operational_object
        for prop in properties
        if isinstance(prop, dict) and prop.get("owned") is True
        for operational_object in (
            prop.get("objects")
            if isinstance(prop.get("objects"), (list, tuple))
            else ()
        )
        if isinstance(operational_object, dict)
    )


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
    confidence_justification: str,
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
        confidence_justification=confidence_justification,
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
    evidence = next(
        (
            item
            for item in snapshot_evidence(context.snapshot)
            if item.field_name == "liquid_cash_estimate"
            and item.category == "derived"
        ),
        None,
    )
    if evidence is None:
        return None
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
        confidence_justification=(
            "A regra compara uma estimativa derivada de liquidez com o limiar "
            "declarado; despesas futuras continuam indisponíveis."
        ),
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
        confidence_justification=(
            "A regra combina a contagem observada de propriedades possuídas com "
            "a contagem observada de funcionários."
        ),
        missing=("funções dos objetos", "horas trabalhadas"),
    )


def _insufficient_history_rule(
    context: RecommendationContext,
) -> StrategicRecommendation | None:
    if context.snapshot_count >= 2:
        return None
    evidence = snapshot_count_evidence(
        campaign_id=context.campaign_id,
        snapshot_count=context.snapshot_count,
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
        confidence_justification=(
            "A recomendação decorre exclusivamente da contagem persistida de "
            "snapshots da campanha."
        ),
        missing=("snapshot anterior",),
    )


def _idle_cultivation_rule(
    context: RecommendationContext,
) -> StrategicRecommendation | None:
    cultivation = tuple(
        item
        for item in _owned_operational_objects(context.snapshot)
        if item.get("category") == "cultivation"
    )
    idle = tuple(
        item
        for item in cultivation
        if item.get("operational_state") == "idle"
    )
    if not idle:
        return None
    evidence = derived_evidence(
        sources=("Properties/*.json",),
        field_name="idle_cultivation_count",
        value={"idle": len(idle), "observed": len(cultivation)},
        calculation=(
            "contagem de objetos de cultivo com operational_state igual a idle"
        ),
        explanation=(
            "Vasos observados sem planta foram contabilizados nas propriedades "
            "possuídas."
        ),
        related_entity="cultivation",
    )
    return _recommendation(
        context,
        rule_id="operations.idle-cultivation.v1",
        category="cultivo",
        title="Usar a estrutura de cultivo já instalada",
        explanation=(
            f"{len(idle)} de {len(cultivation)} vasos observados estão sem planta. "
            "Antes de comprar novos vasos, confirme se os atuais devem entrar no "
            "próximo ciclo."
        ),
        priority="medium",
        confidence="medium",
        evidence=(evidence,),
        confidence_justification=(
            "A ausência de planta é observável, mas demanda, sementes e intenção "
            "do jogador não estão completamente disponíveis."
        ),
        missing=("demanda por produto", "estoque de sementes utilizável"),
        limitations=(
            "Vaso vazio pode ser uma escolha deliberada de reserva operacional.",
        ),
    )


def _storage_pressure_rule(
    context: RecommendationContext,
) -> StrategicRecommendation | None:
    containers = [
        container
        for item in _owned_operational_objects(context.snapshot)
        if item.get("category") == "storage"
        for container in (
            item.get("containers")
            if isinstance(item.get("containers"), (list, tuple))
            else ()
        )
        if isinstance(container, dict)
    ]
    slot_count = sum(int(item.get("slot_count", 0)) for item in containers)
    occupied = sum(
        int(item.get("occupied_slot_count", 0)) for item in containers
    )
    if slot_count < 4:
        return None
    occupancy = (Decimal(occupied) / Decimal(slot_count)) * Decimal("100")
    if occupancy < Decimal("80"):
        return None
    evidence = derived_evidence(
        sources=("Properties/*.json",),
        field_name="storage_occupancy",
        value={
            "occupied_slots": occupied,
            "observed_slots": slot_count,
            "percentage": _decimal_text(occupancy),
        },
        calculation="slots ocupados / slots observados * 100",
        explanation="Ocupação derivada apenas de recipientes de armazenamento.",
        related_entity="storage",
    )
    return _recommendation(
        context,
        rule_id="operations.storage-pressure.v1",
        category="armazenamento",
        title="Liberar espaço antes do próximo lote",
        explanation=(
            f"{occupied} de {slot_count} slots de armazenamento estão ocupados. "
            "Realoque ou venda estoque antes de ampliar a produção."
        ),
        priority="high" if occupied == slot_count else "medium",
        confidence="medium",
        evidence=(evidence,),
        confidence_justification=(
            "Slots e ocupação são observados, mas o volume físico e a demanda "
            "futura não estão disponíveis."
        ),
        missing=("volume por item", "demanda futura"),
        limitations=(
            "A regra não inclui recipientes internos de estações produtivas.",
        ),
    )


RECOMMENDATION_RULES: tuple[RecommendationRule, ...] = (
    RecommendationRule("liquidity.minimum-buffer.v1", _low_liquidity_rule),
    RecommendationRule(
        "operations.owner-dependency.v1",
        _operational_dependency_rule,
    ),
    RecommendationRule(
        "operations.idle-cultivation.v1",
        _idle_cultivation_rule,
    ),
    RecommendationRule(
        "operations.storage-pressure.v1",
        _storage_pressure_rule,
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
    count_evidence = snapshot_count_evidence(
        campaign_id=campaign_id,
        snapshot_count=len(timeline),
    )
    recommendations = generate_recommendations(
        RecommendationContext(
            campaign_id=campaign_id,
            snapshot_id=latest_id,
            snapshot=latest,
            snapshot_count=len(snapshots),
        )
    )
    facts = tuple(item for item in evidence if item.category == "observed")
    derived = tuple(
        sorted(
            (
                *(item for item in evidence if item.category == "derived"),
                count_evidence,
            ),
            key=lambda item: item.evidence_id,
        )
    )
    unavailable = tuple(item for item in evidence if item.category == "unavailable")
    inferences: tuple[Evidence, ...] = ()
    if len(timeline) >= 2:
        inferences = (
            inferred_evidence(
                evidence_ids=(count_evidence.evidence_id,),
                field_name="campaign_has_history",
                value=True,
                calculation="snapshot_count >= 2",
                explanation=(
                    "A contagem da timeline demonstra histórico suficiente para "
                    "comparações; isso não implica tendência econômica."
                ),
                confidence="high",
                related_entity=campaign_id,
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
