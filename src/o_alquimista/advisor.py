"""Projeções curadas para a experiência consultiva local."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
import unicodedata
from typing import Any

from .analysis import compare_snapshots
from .database import AlquimistaDatabase
from .json_codec import to_finite_decimal

PRODUCT_LABELS = {
    "granddaddypurple": "Granddaddy Purple",
    "greencrack": "Green Crack",
    "ogkush": "OG Kush",
    "sourdiesel": "Sour Diesel",
    "superfilds": "Super Filds",
    "shinyfuel": "Shiny Fuel",
    "shinyshart": "Shiny Shart",
    "slimyfruit": "Slimy Fruit",
    "strawberrydiamond": "Strawberry Diamond",
    "purplecake": "Purple Cake",
    "thicksplooge": "Thick Splooge",
}
PRODUCTIVE_CATEGORIES = {
    "cultivation",
    "mixing",
    "processing",
    "packaging",
}


def _decimal_text(value: Any) -> str | None:
    decimal = to_finite_decimal(value)
    return format(decimal, "f") if decimal is not None else None


def _item_label(value: Any) -> str:
    item_id = str(value or "item desconhecido")
    if item_id in PRODUCT_LABELS:
        return PRODUCT_LABELS[item_id]
    return item_id.replace("_", " ").replace("-", " ").strip().title()


def _percentage(part: int, total: int) -> int | None:
    return round((part / total) * 100) if total else None


def _tone(score: int | None, *, reverse: bool = False) -> str:
    if score is None:
        return "neutral"
    normalized = 100 - score if reverse else score
    if normalized >= 75:
        return "good"
    if normalized >= 45:
        return "attention"
    return "risk"


def _game_moment(snapshot: dict[str, Any]) -> dict[str, Any]:
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    value = game.get("time_of_day")
    time_label = None
    if isinstance(value, (int, float)):
        integer = int(value)
        hours, minutes = divmod(integer, 100)
        if 0 <= hours <= 23 and 0 <= minutes <= 59:
            time_label = f"{hours:02d}:{minutes:02d}"
    return {
        "elapsed_days": game.get("elapsed_days"),
        "time_of_day": value,
        "time_label": time_label,
        "playtime_seconds": game.get("playtime_seconds"),
    }


def _employee_role(employee: dict[str, Any]) -> str | None:
    if employee.get("role"):
        return str(employee["role"])
    raw = employee.get("raw")
    if not isinstance(raw, dict):
        return None
    base = raw.get("BaseData") if isinstance(raw.get("BaseData"), dict) else raw
    data_type = str(base.get("DataType") or raw.get("DataType") or "")
    return {
        "BotanistData": "botanist",
        "ChemistData": "chemist",
        "PackagerData": "packager",
        "HandlerData": "handler",
        "CleanerData": "cleaner",
    }.get(data_type)


def _employee_station_count(employee: dict[str, Any]) -> int | None:
    value = employee.get("assigned_station_count")
    if isinstance(value, int):
        return value
    raw = employee.get("raw")
    if not isinstance(raw, dict):
        return None
    total = 0
    observed = False
    for entry in raw.get("AdditionalDatas") or ():
        if not isinstance(entry, dict):
            continue
        contents = entry.get("Contents")
        stations = contents.get("Stations") if isinstance(contents, dict) else None
        identifiers = (
            stations.get("ObjectGUIDs")
            if isinstance(stations, dict)
            else None
        )
        if isinstance(identifiers, list):
            observed = True
            total += len(identifiers)
    return total if observed else None


def _operational_objects(
    snapshot: dict[str, Any],
    *,
    owned_only: bool = True,
) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    properties = snapshot.get("properties")
    if not isinstance(properties, (list, tuple)):
        return rows
    for prop in properties:
        if not isinstance(prop, dict):
            continue
        if owned_only and prop.get("owned") is not True:
            continue
        objects = prop.get("objects")
        if not isinstance(objects, (list, tuple)):
            continue
        rows.extend(
            (str(prop.get("name") or "Propriedade"), operational_object)
            for operational_object in objects
            if isinstance(operational_object, dict)
        )
    return rows


def _property_cards(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    properties = snapshot.get("properties")
    if not isinstance(properties, (list, tuple)):
        return cards
    for prop in properties:
        if not isinstance(prop, dict) or prop.get("owned") is not True:
            continue
        objects = (
            prop.get("objects")
            if isinstance(prop.get("objects"), (list, tuple))
            else ()
        )
        categories = Counter(
            str(item.get("category") or "unknown")
            for item in objects
            if isinstance(item, dict)
        )
        containers = [
            container
            for item in objects
            if isinstance(item, dict)
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
        active = sum(
            1
            for item in objects
            if isinstance(item, dict)
            and item.get("operational_state") == "active"
        )
        idle = sum(
            1
            for item in objects
            if isinstance(item, dict)
            and item.get("operational_state") == "idle"
        )
        productive_count = sum(
            count
            for category, count in categories.items()
            if category in PRODUCTIVE_CATEGORIES
        )
        employees = [
            item
            for item in prop.get("employees") or ()
            if isinstance(item, dict)
        ]
        roles = Counter(
            role
            for employee in employees
            if (role := _employee_role(employee))
        )
        assigned_stations = sum(
            count
            for employee in employees
            if (count := _employee_station_count(employee)) is not None
        )
        profile_parts = [
            label
            for category, label in (
                ("cultivation", "cultivo"),
                ("mixing", "mistura"),
                ("processing", "processamento"),
                ("packaging", "embalagem"),
            )
            if categories.get(category)
        ]
        cards.append(
            {
                "name": prop.get("name"),
                "employee_count": prop.get("employee_count"),
                "object_count": prop.get("object_count"),
                "productive_count": productive_count,
                "storage_count": categories.get("storage", 0),
                "support_count": sum(
                    categories.get(category, 0)
                    for category in ("fixture", "utility", "waste")
                ),
                "active_count": active,
                "idle_count": idle,
                "trackable_state_count": active + idle,
                "categories": dict(sorted(categories.items())),
                "profile": (
                    "Base de " + ", ".join(profile_parts)
                    if profile_parts
                    else "Base de apoio e armazenamento"
                ),
                "employee_roles": dict(sorted(roles.items())),
                "assigned_station_count": assigned_stations,
                "slot_count": slot_count,
                "occupied_slot_count": occupied,
                "occupancy_percent": (
                    round((occupied / slot_count) * 100)
                    if slot_count
                    else None
                ),
            }
        )
    return sorted(
        cards,
        key=lambda item: (
            -int(item["productive_count"]),
            str(item["name"]),
        ),
    )


def _advisor_message(recommendations: list[dict[str, Any]]) -> dict[str, str]:
    if recommendations:
        first = recommendations[0]
        return {
            "eyebrow": "Conselho prioritário",
            "title": str(first.get("title") or "Observe antes de expandir"),
            "body": str(
                first.get("explanation")
                or "Ainda faltam evidências para uma decisão segura."
            ),
        }
    return {
        "eyebrow": "Operação estável",
        "title": "O ouro está nos próximos dados",
        "body": (
            "Nenhuma regra crítica foi acionada. Importe outro momento da "
            "campanha antes de realizar uma expansão cara."
        ),
    }


def _campaign_summary(campaign: dict[str, Any]) -> dict[str, Any]:
    return {
        "campaign_id": campaign.get("campaign_id"),
        "display_name": campaign.get("display_name"),
        "resolution_state": campaign.get("resolution_state"),
        "confidence": campaign.get("confidence"),
        "import_count": campaign.get("import_count"),
        "snapshot_count": campaign.get("snapshot_count"),
        "candidate_association_count": campaign.get(
            "candidate_association_count"
        ),
    }


def _recommendation_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "recommendation_id": item.get("recommendation_id"),
        "rule_id": item.get("rule_id"),
        "title": item.get("title"),
        "category": item.get("category"),
        "priority": item.get("priority"),
        "confidence": item.get("confidence"),
        "explanation": item.get("explanation"),
        "limitations": list(item.get("limitations") or ()),
        "missing_information": list(item.get("missing_information") or ()),
    }


def _milestone_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "milestone_id": item.get("milestone_id"),
        "milestone_type": item.get("milestone_type"),
        "title": item.get("title"),
        "description": item.get("description"),
        "confidence": item.get("confidence"),
        "first_seen_snapshot_id": item.get("first_seen_snapshot_id"),
    }


def _timeline_summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_id": entry.get("snapshot_id"),
        "chronological_order": entry.get("chronological_order"),
        "observable_game_moment": dict(
            entry.get("observable_game_moment") or {}
        ),
        "financial_summary": dict(entry.get("financial_summary") or {}),
        "progression_summary": dict(entry.get("progression_summary") or {}),
        "operational_summary": dict(entry.get("operational_summary") or {}),
        "milestones": [
            _milestone_summary(item)
            for item in entry.get("milestones") or ()
            if isinstance(item, dict)
        ],
    }


def _portfolio_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    products = (
        snapshot.get("products")
        if isinstance(snapshot.get("products"), dict)
        else {}
    )
    inventory = (
        snapshot.get("inventory")
        if isinstance(snapshot.get("inventory"), dict)
        else {}
    )
    finance = (
        snapshot.get("finance")
        if isinstance(snapshot.get("finance"), dict)
        else {}
    )
    discovered = [
        str(item)
        for item in products.get("discovered") or ()
        if item not in (None, "")
    ]
    prices = {
        str(key): decimal
        for key, value in (products.get("prices") or {}).items()
        if (decimal := to_finite_decimal(value)) is not None
    }
    quantities = {
        str(key): decimal
        for key, value in (inventory.get("quantities") or {}).items()
        if (decimal := to_finite_decimal(value)) is not None
        and decimal > 0
    }
    sellable = [
        {
            "product_id": product_id,
            "label": _item_label(product_id),
            "quantity": _decimal_text(quantity),
            "reference_price": _decimal_text(prices[product_id]),
            "reference_value": _decimal_text(quantity * prices[product_id]),
        }
        for product_id, quantity in quantities.items()
        if product_id in prices
    ]
    sellable.sort(
        key=lambda item: (
            -(
                to_finite_decimal(item["reference_value"])
                or Decimal("0")
            ),
            str(item["label"]),
        )
    )
    discovered_prices = [
        (product_id, prices[product_id])
        for product_id in discovered
        if product_id in prices
    ]
    highest = (
        max(discovered_prices, key=lambda item: (item[1], item[0]))
        if discovered_prices
        else None
    )
    active_mix = products.get("active_mix")
    active_mix_detected = (
        isinstance(active_mix, dict)
        and any(value not in (None, "", 0, False, [], {}) for value in active_mix.values())
    )
    return {
        "discovered_count": len(discovered),
        "listed_count": len(products.get("listed") or ()),
        "recipe_count": len(products.get("mix_recipes") or ()),
        "active_mix_detected": active_mix_detected,
        "inventory_reference_value": _decimal_text(
            finance.get("inventory_list_price_estimate")
        ),
        "sellable_product_count": len(sellable),
        "top_inventory": sellable[:5],
        "highest_reference_price": (
            {
                "product_id": highest[0],
                "label": _item_label(highest[0]),
                "value": _decimal_text(highest[1]),
            }
            if highest
            else None
        ),
        "discovered": [
            {"product_id": item, "label": _item_label(item)}
            for item in discovered
        ],
        "note": (
            "Valores são preços de referência do save, não lucro nem demanda "
            "garantida."
        ),
    }


def _workforce_summary(
    snapshot: dict[str, Any],
    property_cards: list[dict[str, Any]],
) -> dict[str, Any]:
    employees = [
        item
        for item in snapshot.get("employees") or ()
        if isinstance(item, dict)
    ]
    roles = Counter(
        role
        for employee in employees
        if (role := _employee_role(employee))
    )
    assigned_station_count = sum(
        count
        for employee in employees
        if (count := _employee_station_count(employee)) is not None
    )
    productive_properties = [
        item for item in property_cards if item["productive_count"] > 0
    ]
    unstaffed = [
        item["name"]
        for item in productive_properties
        if not item.get("employee_count")
    ]
    staffed = len(productive_properties) - len(unstaffed)
    return {
        "employee_count": len(employees),
        "roles": dict(sorted(roles.items())),
        "assigned_station_count": assigned_station_count,
        "productive_property_count": len(productive_properties),
        "staffed_productive_property_count": staffed,
        "unstaffed_productive_properties": unstaffed,
        "coverage_percent": _percentage(staffed, len(productive_properties)),
        "note": (
            "Equipe observada não mede produtividade individual. Uma propriedade "
            "sem funcionário pode estar sendo operada manualmente."
        ),
    }


def _availability_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    availability = (
        snapshot.get("availability")
        if isinstance(snapshot.get("availability"), dict)
        else {}
    )
    rows = [
        {
            "section": str(name),
            "state": (
                str(value.get("state") or "unknown")
                if isinstance(value, dict)
                else "unknown"
            ),
            "explanation": (
                str(value.get("explanation") or "")
                if isinstance(value, dict)
                else ""
            ),
        }
        for name, value in sorted(availability.items())
    ]
    observed = sum(1 for item in rows if item["state"] == "observed")
    return {
        "observed_count": observed,
        "total_count": len(rows),
        "coverage_percent": _percentage(observed, len(rows)),
        "sections": rows,
    }


def _diagnostic_summary(
    *,
    campaign: dict[str, Any],
    availability: dict[str, Any],
    operations: dict[str, Any],
    workforce: dict[str, Any],
) -> dict[str, Any]:
    coverage = int(availability.get("coverage_percent") or 0)
    visibility = int(
        _percentage(
            int(operations["trackable_state_count"]),
            int(operations["productive_count"]),
        )
        or 0
    )
    headroom = (
        100 - int(operations["occupancy_percent"])
        if operations.get("occupancy_percent") is not None
        else None
    )
    delegation = workforce.get("coverage_percent")
    history = min(int(campaign.get("snapshot_count") or 0) * 34, 100)
    identity = {
        "high": 100,
        "medium": 70,
        "low": 35,
        "unavailable": 15,
    }.get(str(campaign.get("confidence")), 15)
    decision_score = round(
        (coverage * 0.45)
        + (visibility * 0.20)
        + (history * 0.20)
        + (identity * 0.15)
    )
    level = (
        "forte"
        if decision_score >= 80
        else "boa"
        if decision_score >= 60
        else "parcial"
        if decision_score >= 40
        else "inicial"
    )
    return {
        "decision_readiness_score": decision_score,
        "level": level,
        "title": f"Leitura {level} da campanha",
        "explanation": (
            "Este índice mede quanto o Alquimista consegue sustentar decisões "
            "com os dados disponíveis; não é uma nota de desempenho do jogador."
        ),
        "pillars": [
            {
                "id": "coverage",
                "label": "Dados compreendidos",
                "score": coverage,
                "tone": _tone(coverage),
                "summary": (
                    f"{availability['observed_count']} de "
                    f"{availability['total_count']} áreas do save foram observadas."
                ),
                "meaning": (
                    "Quanto maior, menos decisões dependem de informações ausentes."
                ),
            },
            {
                "id": "visibility",
                "label": "Atividade legível",
                "score": visibility,
                "tone": _tone(visibility),
                "summary": (
                    f"{operations['trackable_state_count']} de "
                    f"{operations['productive_count']} equipamentos produtivos "
                    "expõem estado ativo ou ocioso."
                ),
                "meaning": (
                    "Os demais equipamentos são reconhecidos, mas o save ainda não "
                    "permite afirmar se estão trabalhando."
                ),
            },
            {
                "id": "storage",
                "label": "Folga de armazenamento",
                "score": headroom,
                "tone": _tone(headroom),
                "summary": (
                    f"{headroom}% dos compartimentos observados estão livres."
                    if headroom is not None
                    else "Não há compartimentos suficientes para medir a folga."
                ),
                "meaning": (
                    "Folga baixa aumenta o risco de interromper produção por falta "
                    "de espaço; não representa capacidade por hora."
                ),
            },
            {
                "id": "delegation",
                "label": "Cobertura de equipe",
                "score": delegation,
                "tone": _tone(delegation),
                "summary": (
                    f"{workforce['staffed_productive_property_count']} de "
                    f"{workforce['productive_property_count']} bases produtivas "
                    "possuem ao menos um funcionário observado."
                ),
                "meaning": workforce["note"],
            },
        ],
    }


def _action_plan(
    recommendations: list[dict[str, Any]],
    *,
    workforce: dict[str, Any],
    portfolio: dict[str, Any],
    related_count: int,
) -> list[dict[str, Any]]:
    rule_guidance = {
        "operations.idle-cultivation.v1": {
            "action": (
                "Escolha quais vasos entram no próximo ciclo e abasteça primeiro "
                "a estrutura que já existe."
            ),
            "success": (
                "Os vasos planejados deixam de aparecer ociosos no próximo export, "
                "ou ficam explicitamente reservados por decisão sua."
            ),
            "impact": "Evita investimento prematuro e usa capacidade já comprada.",
        },
        "operations.storage-pressure.v1": {
            "action": (
                "Venda, transfira ou reorganize o estoque antes de iniciar outro lote."
            ),
            "success": "A ocupação observada volta a ficar abaixo de 80%.",
            "impact": "Reduz o risco de produção parar por falta de compartimentos.",
        },
        "operations.owner-dependency.v1": {
            "action": (
                "Liste as tarefas que ainda dependem de você e delegue primeiro a "
                "etapa repetitiva que limita o fluxo."
            ),
            "success": "Ao menos uma base produtiva ganha cobertura de equipe.",
            "impact": "Libera seu tempo para venda, expansão e decisões.",
        },
        "liquidity.minimum-buffer.v1": {
            "action": "Adie compras não essenciais e preserve o caixa disponível.",
            "success": "O próximo investimento não compromete toda a liquidez.",
            "impact": "Reduz o risco de expansão sem capital de giro.",
        },
        "memory.collect-baseline.v1": {
            "action": (
                "Use a comparação exploratória com um export relacionado para "
                "entender o que mudou."
            ),
            "success": "Uma variação financeira e operacional fica explicada.",
            "impact": "Transforma uma foto isolada em decisão baseada em tendência.",
        },
    }
    actions: list[dict[str, Any]] = []
    for recommendation in recommendations:
        guidance = rule_guidance.get(str(recommendation.get("rule_id")))
        if guidance is None:
            continue
        actions.append(
            {
                "rank": len(actions) + 1,
                "title": recommendation.get("title"),
                "why": recommendation.get("explanation"),
                "confidence": recommendation.get("confidence"),
                "source": recommendation.get("rule_id"),
                **guidance,
            }
        )
        if len(actions) == 3:
            return actions
    if workforce["unstaffed_productive_properties"] and len(actions) < 3:
        property_names = ", ".join(workforce["unstaffed_productive_properties"])
        actions.append(
            {
                "rank": len(actions) + 1,
                "title": "Definir o papel das bases sem equipe",
                "action": (
                    "Defina se estas bases serão operadas manualmente, usadas como "
                    f"reserva ou receberão funcionários: {property_names}."
                ),
                "why": (
                    "Essas propriedades possuem estrutura produtiva, mas nenhum "
                    "funcionário foi observado."
                ),
                "success": "Cada base tem um propósito operacional claro.",
                "impact": "Evita espaço e equipamentos sem responsabilidade definida.",
                "confidence": "medium",
                "source": "advisor.workforce-coverage.v1",
            }
        )
    if portfolio["sellable_product_count"] and len(actions) < 3:
        actions.append(
            {
                "rank": len(actions) + 1,
                "title": "Converter estoque vendável em caixa",
                "action": (
                    "Revise os produtos com preço de referência e priorize a saída "
                    "do estoque já acabado antes de produzir por impulso."
                ),
                "why": (
                    f"Foram encontrados {portfolio['sellable_product_count']} "
                    "produtos em estoque com preço de referência conhecido."
                ),
                "success": "O valor de tabela do estoque cai sem reduzir a liquidez.",
                "impact": "Libera capital e espaço; demanda real ainda precisa ser confirmada.",
                "confidence": "medium",
                "source": "advisor.inventory-conversion.v1",
            }
        )
    if related_count and len(actions) < 3:
        actions.append(
            {
                "rank": len(actions) + 1,
                "title": "Ler a evolução entre exports",
                "action": "Abra a Transmutação Temporal e escolha um export anterior.",
                "why": f"Há {related_count} exports relacionados por sinais locais.",
                "success": "As mudanças principais entre dois momentos ficam visíveis.",
                "impact": "Revela tendência sem unir campanhas automaticamente.",
                "confidence": "low",
                "source": "advisor.related-export-comparison.v1",
            }
        )
    return actions[:3]


def _related_exports(
    database: AlquimistaDatabase,
    campaign_id: str,
    campaigns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    campaign_lookup = {
        str(item["campaign_id"]): item
        for item in campaigns
    }
    related: list[dict[str, Any]] = []
    for association in database.campaign_associations(campaign_id):
        candidate_id = str(association.get("candidate_campaign_id") or "")
        candidate = campaign_lookup.get(candidate_id)
        if candidate is None:
            continue
        timeline = database.campaign_history(candidate_id)
        if not timeline:
            continue
        record = database.snapshot_record(timeline[-1]["snapshot_id"])
        snapshot = record["snapshot"]
        finance = (
            snapshot.get("finance")
            if isinstance(snapshot.get("finance"), dict)
            else {}
        )
        evidence = association.get("evidence")
        shared_signals = (
            evidence.get("shared_signals")
            if isinstance(evidence, dict)
            else ()
        )
        related.append(
            {
                **candidate,
                "snapshot_id": record["snapshot_id"],
                "moment": _game_moment(snapshot),
                "networth": _decimal_text(finance.get("networth")),
                "shared_signal_count": len(shared_signals or ()),
                "relation": "candidate",
            }
        )
    return sorted(
        related,
        key=lambda item: (
            item["moment"].get("elapsed_days") or -1,
            item["moment"].get("time_of_day") or -1,
            str(item["campaign_id"]),
        ),
        reverse=True,
    )


def _campaign_story(
    snapshot: dict[str, Any],
    *,
    operations: dict[str, Any],
    workforce: dict[str, Any],
    portfolio: dict[str, Any],
    campaign: dict[str, Any],
) -> dict[str, Any]:
    """Cria uma camada narrativa sem confundi-la com o rank oficial do jogo."""

    progression = (
        snapshot.get("progression")
        if isinstance(snapshot.get("progression"), dict)
        else {}
    )
    property_count = int(operations.get("owned_property_count") or 0)
    productive_count = int(operations.get("productive_count") or 0)
    employee_count = int(workforce.get("employee_count") or 0)
    product_count = int(portfolio.get("discovered_count") or 0)
    stages = [
        {
            "id": "awakening",
            "roman": "I",
            "title": "O Despertar",
            "description": "O primeiro núcleo da operação ganha forma.",
            "unlocked": property_count >= 1,
        },
        {
            "id": "transmutation",
            "roman": "II",
            "title": "A Transmutação",
            "description": "Produtos e equipamentos passam a formar um sistema.",
            "unlocked": productive_count >= 1 and product_count >= 3,
        },
        {
            "id": "delegation",
            "roman": "III",
            "title": "O Círculo",
            "description": "A operação deixa de depender apenas do jogador.",
            "unlocked": employee_count >= 1,
        },
        {
            "id": "ascension",
            "roman": "IV",
            "title": "A Ascensão",
            "description": "Múltiplas bases e um portfólio amplo exigem estratégia.",
            "unlocked": property_count >= 3 and product_count >= 8,
        },
    ]
    current_index = max(
        (
            index
            for index, stage in enumerate(stages)
            if stage["unlocked"]
        ),
        default=0,
    )
    for index, stage in enumerate(stages):
        stage["current"] = index == current_index
        stage["completed"] = index < current_index
    current = stages[current_index]
    narrative = {
        "awakening": (
            "Toda grande fórmula começa pequena. Seu primeiro desafio é dar "
            "função clara ao que já foi instalado."
        ),
        "transmutation": (
            "A oficina já produz, mas ainda falta ritmo. O próximo salto vem de "
            "usar melhor o que você possui antes de comprar mais."
        ),
        "delegation": (
            "A equipe entrou no círculo. Agora cada base precisa de um papel e "
            "cada tarefa repetitiva deve encontrar um responsável."
        ),
        "ascension": (
            "Seu império já possui escala. O perigo agora não é a falta de "
            "recursos, mas crescer sem saber qual engrenagem realmente limita o fluxo."
        ),
    }[current["id"]]
    unlocked_count = sum(bool(stage["unlocked"]) for stage in stages)
    return {
        "chapter_number": current["roman"],
        "chapter_id": current["id"],
        "chapter_title": current["title"],
        "narrative": narrative,
        "path": stages,
        "path_progress_percent": round((unlocked_count / len(stages)) * 100),
        "game_rank": progression.get("rank"),
        "game_tier": progression.get("tier"),
        "companion_note": (
            "Os capítulos pertencem ao companion e não substituem o rank oficial do jogo."
        ),
        "next_unlock": (
            "Vincular dois momentos confirmados da mesma campanha."
            if int(campaign.get("snapshot_count") or 0) < 2
            else "Concluir a missão ativa e validar o resultado no próximo export."
        ),
    }


def _quest_board(action_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rewards = {
        "operations.idle-cultivation.v1": {
            "label": "Capacidade desperta",
            "icon": "✦",
        },
        "operations.storage-pressure.v1": {
            "label": "Fluxo desobstruído",
            "icon": "◇",
        },
        "operations.owner-dependency.v1": {
            "label": "Tempo recuperado",
            "icon": "◷",
        },
        "liquidity.minimum-buffer.v1": {
            "label": "Caixa protegido",
            "icon": "◆",
        },
        "memory.collect-baseline.v1": {
            "label": "Memória ampliada",
            "icon": "◈",
        },
        "advisor.workforce-coverage.v1": {
            "label": "Papéis definidos",
            "icon": "⌂",
        },
        "advisor.inventory-conversion.v1": {
            "label": "Capital liberado",
            "icon": "$",
        },
        "advisor.related-export-comparison.v1": {
            "label": "Tendência revelada",
            "icon": "⇄",
        },
    }
    return [
        {
            "quest_id": str(item.get("source") or f"quest-{index}"),
            "rank": item.get("rank"),
            "title": item.get("title"),
            "briefing": item.get("why"),
            "objective": item.get("action"),
            "success": item.get("success"),
            "impact": item.get("impact"),
            "confidence": item.get("confidence"),
            "reward": rewards.get(
                str(item.get("source")),
                {"label": "Conhecimento conquistado", "icon": "Δ"},
            ),
            "ritual": [
                "Assuma a missão na Câmara.",
                "Execute a ação durante a sessão de jogo.",
                "Importe um novo save para o Alquimista verificar o resultado.",
            ],
        }
        for index, item in enumerate(action_plan, start=1)
    ]


def _achievements(
    *,
    operations: dict[str, Any],
    workforce: dict[str, Any],
    portfolio: dict[str, Any],
) -> list[dict[str, Any]]:
    definitions = [
        (
            operations.get("owned_property_count", 0) >= 1,
            "first-sanctum",
            "Primeiro Santuário",
            "Uma propriedade sob seu comando.",
            "⌂",
        ),
        (
            portfolio.get("recipe_count", 0) >= 5,
            "expanded-grimoire",
            "Grimório Expandido",
            "Cinco ou mais receitas observadas.",
            "◇",
        ),
        (
            workforce.get("employee_count", 0) >= 1,
            "first-circle",
            "O Primeiro Círculo",
            "A primeira equipe foi formada.",
            "◈",
        ),
        (
            operations.get("owned_property_count", 0) >= 3,
            "three-sanctums",
            "Três Santuários",
            "Três propriedades sob seu comando.",
            "△",
        ),
    ]
    return [
        {
            "achievement_id": identifier,
            "title": title,
            "description": description,
            "icon": icon,
        }
        for unlocked, identifier, title, description, icon in definitions
        if unlocked
    ]


FINANCIAL_LABELS = {
    "online_balance": "Saldo online",
    "loose_cash": "Dinheiro físico",
    "liquid_cash_estimate": "Liquidez observada",
    "networth": "Patrimônio",
    "lifetime_earnings": "Ganhos acumulados",
    "inventory_list_price_estimate": "Valor de referência do estoque",
    "weekly_deposit_sum": "Depósitos observados",
    "expenses": "Despesas observadas",
}

OPERATIONAL_LABELS = {
    "properties": "Propriedades",
    "equipment": "Equipamentos",
    "businesses": "Negócios",
    "vehicles": "Veículos",
    "employees": "Equipe",
    "products": "Produtos",
    "inventory": "Estoque",
    "capacity": "Capacidade",
    "suppliers": "Fornecedores",
    "customers": "Rede de clientes",
    "activities": "Atividades",
    "progression": "Progressão",
}


def _campaign_latest_snapshot(
    database: AlquimistaDatabase,
    campaign_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    timeline = database.campaign_history(campaign_id)
    if not timeline:
        raise ValueError("A campanha selecionada ainda não possui snapshots.")
    record = database.snapshot_record(timeline[-1]["snapshot_id"])
    return record, record["snapshot"]


def _campaign_snapshot(
    database: AlquimistaDatabase,
    *,
    campaign_id: str,
    snapshot_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if snapshot_id is None:
        return _campaign_latest_snapshot(database, campaign_id)
    record = database.snapshot_record(snapshot_id)
    if str(record.get("campaign_id")) != campaign_id:
        raise ValueError("O snapshot selecionado não pertence a esta campanha.")
    return record, record["snapshot"]


def _comparison_verdict(
    financial_changes: list[dict[str, Any]],
    operational_sections: list[dict[str, Any]],
) -> dict[str, str]:
    networth = next(
        (
            item
            for item in financial_changes
            if item["field"] == "networth" and item["status"] == "changed"
        ),
        None,
    )
    changed_sections = sum(item["changed_count"] for item in operational_sections)
    if networth and (to_finite_decimal(networth["absolute_change"]) or 0) > 0:
        return {
            "tone": "good",
            "title": "O patrimônio avançou entre estes dois momentos",
            "body": (
                "Use as mudanças operacionais abaixo para descobrir o que acompanhou "
                "esse avanço. A comparação mostra correlação, não prova causalidade."
            ),
        }
    if networth and (to_finite_decimal(networth["absolute_change"]) or 0) < 0:
        return {
            "tone": "attention",
            "title": "O patrimônio recuou entre estes dois momentos",
            "body": (
                "Revise compras, estoque e mudanças de estrutura antes de repetir "
                "a mesma sequência. Um recuo pode representar investimento, não perda."
            ),
        }
    if changed_sections:
        return {
            "tone": "neutral",
            "title": "A operação mudou, mas o efeito financeiro não está claro",
            "body": (
                "As diferenças abaixo ajudam a reconstruir a sessão sem transformar "
                "uma hipótese em fato."
            ),
        }
    return {
        "tone": "neutral",
        "title": "Pouca mudança foi observada",
        "body": "Os dois exports são semelhantes nas áreas que o Alquimista compreende.",
    }


def build_advisor_comparison(
    database: AlquimistaDatabase,
    *,
    current_campaign_id: str,
    baseline_campaign_id: str,
    current_snapshot_id: str | None = None,
    baseline_snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Projeta uma comparação exploratória segura para a interface local."""

    campaigns = {
        str(item["campaign_id"]): _campaign_summary(item)
        for item in database.campaign_list()
    }
    if current_campaign_id not in campaigns or baseline_campaign_id not in campaigns:
        raise ValueError("Uma das campanhas selecionadas não existe.")
    current_record, current = _campaign_snapshot(
        database,
        campaign_id=current_campaign_id,
        snapshot_id=current_snapshot_id,
    )
    baseline_record, baseline = _campaign_snapshot(
        database,
        campaign_id=baseline_campaign_id,
        snapshot_id=baseline_snapshot_id,
    )
    comparison = compare_snapshots(
        baseline,
        current,
        previous_snapshot_id=baseline_record["snapshot_id"],
        current_snapshot_id=current_record["snapshot_id"],
        previous_campaign_id=baseline_campaign_id,
        current_campaign_id=current_campaign_id,
        allow_cross_campaign=True,
    ).to_dict()
    financial = [
        {
            "field": item["field"],
            "label": FINANCIAL_LABELS.get(item["field"], item["field"]),
            "status": item["status"],
            "previous": _decimal_text(item.get("previous")),
            "current": _decimal_text(item.get("current")),
            "absolute_change": _decimal_text(item.get("absolute_change")),
            "percentage_change": _decimal_text(item.get("percentage_change")),
            "explanation": item.get("explanation"),
        }
        for item in comparison["financial_changes"]
        if item["status"] in {"changed", "unknown", "not_comparable"}
    ]
    sections: list[dict[str, Any]] = []
    for section, changes in comparison["operational_changes"].items():
        meaningful = [
            item
            for item in changes
            if item["status"] in {"added", "removed", "changed"}
        ]
        if not meaningful:
            continue
        sections.append(
            {
                "section": section,
                "label": OPERATIONAL_LABELS.get(section, section),
                "changed_count": len(meaningful),
                "added_count": sum(
                    item["status"] == "added" for item in meaningful
                ),
                "removed_count": sum(
                    item["status"] == "removed" for item in meaningful
                ),
                "updated_count": sum(
                    item["status"] == "changed" for item in meaningful
                ),
            }
        )
    candidate_ids = {
        str(item.get("candidate_campaign_id") or "")
        for item in database.campaign_associations(current_campaign_id)
    }
    relation = (
        "same_campaign"
        if current_campaign_id == baseline_campaign_id
        else "candidate"
        if baseline_campaign_id in candidate_ids
        else "independent"
    )
    return {
        "status": "ready",
        "relation": relation,
        "caution": (
            "Comparação exploratória: sinais locais relacionam os exports, mas eles "
            "não são unidos automaticamente como a mesma campanha."
            if relation == "candidate"
            else "Comparação entre snapshots confirmados da mesma campanha."
            if relation == "same_campaign"
            else (
                "Comparação exploratória entre campanhas sem relação confirmada. "
                "Use apenas para contraste, não para avaliar evolução."
            )
        ),
        "baseline": {
            "campaign": campaigns[baseline_campaign_id],
            "moment": _game_moment(baseline),
        },
        "current": {
            "campaign": campaigns[current_campaign_id],
            "moment": _game_moment(current),
        },
        "financial_changes": financial,
        "operational_sections": sections,
        "verdict": _comparison_verdict(financial, sections),
        "limitations": list(comparison["limitations"]),
    }


def build_dashboard(
    database: AlquimistaDatabase,
    *,
    campaign_id: str | None = None,
) -> dict[str, Any]:
    campaigns = [
        _campaign_summary(item)
        for item in database.campaign_list()
    ]
    imports = database.history()
    if not campaigns or not imports:
        return {
            "status": "empty",
            "campaigns": campaigns,
            "selected_campaign_id": None,
            "message": {
                "eyebrow": "A Câmara está vazia",
                "title": "Importe um export do Schedule I",
                "body": (
                    "O ZIP será analisado localmente e descartado após a "
                    "importação. Nenhum dado é enviado para a internet."
                ),
            },
        }

    available_ids = {str(item["campaign_id"]) for item in campaigns}
    selected_campaign_id = (
        campaign_id if campaign_id in available_ids else str(imports[0]["campaign_id"])
    )
    timeline = database.campaign_history(selected_campaign_id)
    if not timeline:
        return {
            "status": "empty_campaign",
            "campaigns": campaigns,
            "selected_campaign_id": selected_campaign_id,
        }
    latest_timeline = timeline[-1]
    snapshot_record = database.snapshot_record(latest_timeline["snapshot_id"])
    snapshot = snapshot_record["snapshot"]
    analysis = database.campaign_analysis(selected_campaign_id)
    analysis_data = analysis.to_dict()
    recommendations = [
        _recommendation_summary(item)
        for item in analysis_data["recommendations"]
    ]
    priority_order = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
        "informational": 4,
    }
    recommendations.sort(
        key=lambda item: (
            priority_order.get(str(item.get("priority")), 99),
            str(item.get("recommendation_id")),
        )
    )

    finance = snapshot.get("finance") if isinstance(snapshot.get("finance"), dict) else {}
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    operational_rows = _operational_objects(snapshot)
    operational_categories = Counter(
        str(item.get("category") or "unknown")
        for _, item in operational_rows
    )
    active_count = sum(
        1
        for _, item in operational_rows
        if item.get("operational_state") == "active"
    )
    idle_count = sum(
        1
        for _, item in operational_rows
        if item.get("operational_state") == "idle"
    )
    observed_slots = sum(
        int(container.get("slot_count", 0))
        for _, item in operational_rows
        for container in (
            item.get("containers")
            if isinstance(item.get("containers"), (list, tuple))
            else ()
        )
        if isinstance(container, dict)
    )
    occupied_slots = sum(
        int(container.get("occupied_slot_count", 0))
        for _, item in operational_rows
        for container in (
            item.get("containers")
            if isinstance(item.get("containers"), (list, tuple))
            else ()
        )
        if isinstance(container, dict)
    )

    productive_count = sum(
        count
        for category, count in operational_categories.items()
        if category in PRODUCTIVE_CATEGORIES
    )
    storage_count = operational_categories.get("storage", 0)
    support_count = sum(
        operational_categories.get(category, 0)
        for category in ("fixture", "utility", "waste")
    )
    unclassified_count = operational_categories.get("unknown", 0)
    properties = _property_cards(snapshot)
    operations = {
        "owned_property_count": len(properties),
        "equipment_count": len(operational_rows),
        "productive_count": productive_count,
        "storage_count": storage_count,
        "support_count": support_count,
        "unclassified_count": unclassified_count,
        "active_count": active_count,
        "idle_count": idle_count,
        "trackable_state_count": active_count + idle_count,
        "unknown_state_count": (
            len(operational_rows) - active_count - idle_count
        ),
        "categories": dict(sorted(operational_categories.items())),
        "observed_slots": observed_slots,
        "occupied_slots": occupied_slots,
        "occupancy_percent": (
            round((occupied_slots / observed_slots) * 100)
            if observed_slots
            else None
        ),
    }
    portfolio = _portfolio_summary(snapshot)
    workforce = _workforce_summary(snapshot, properties)
    availability = _availability_summary(snapshot)
    related_exports = _related_exports(
        database,
        selected_campaign_id,
        campaigns,
    )
    campaign = next(
        (
            item
            for item in campaigns
            if str(item["campaign_id"]) == selected_campaign_id
        ),
        None,
    )
    diagnostic = _diagnostic_summary(
        campaign=campaign or {},
        availability=availability,
        operations=operations,
        workforce=workforce,
    )
    action_plan = _action_plan(
        recommendations,
        workforce=workforce,
        portfolio=portfolio,
        related_count=len(related_exports),
    )
    story = _campaign_story(
        snapshot,
        operations=operations,
        workforce=workforce,
        portfolio=portfolio,
        campaign=campaign or {},
    )
    quests = _quest_board(action_plan)
    achievements = _achievements(
        operations=operations,
        workforce=workforce,
        portfolio=portfolio,
    )

    return {
        "status": "ready",
        "campaigns": campaigns,
        "selected_campaign_id": selected_campaign_id,
        "campaign": campaign,
        "snapshot": {
            "snapshot_id": snapshot_record["snapshot_id"],
            "game_version": (snapshot.get("metadata") or {}).get("game_version"),
            "elapsed_days": game.get("elapsed_days"),
            "time_of_day": game.get("time_of_day"),
            "moment": _game_moment(snapshot),
            "kind": "snapshot",
            "explanation": (
                "Esta tela é uma fotografia do último export, não uma leitura em tempo real."
            ),
        },
        "finance": {
            "online_balance": _decimal_text(finance.get("online_balance")),
            "liquid_cash_estimate": _decimal_text(
                finance.get("liquid_cash_estimate")
            ),
            "networth": _decimal_text(finance.get("networth")),
            "lifetime_earnings": _decimal_text(finance.get("lifetime_earnings")),
        },
        "operations": operations,
        "properties": properties,
        "portfolio": portfolio,
        "workforce": workforce,
        "availability": availability,
        "diagnostic": diagnostic,
        "action_plan": action_plan,
        "story": story,
        "quests": quests,
        "achievements": achievements,
        "related_exports": related_exports,
        "network": {
            "npc_count": len(snapshot.get("npcs") or ()),
            "business_count": len(snapshot.get("businesses") or ()),
            "vehicle_count": len(snapshot.get("vehicles") or ()),
        },
        "progression": dict(
            snapshot.get("progression")
            if isinstance(snapshot.get("progression"), dict)
            else {}
        ),
        "recommendations": recommendations,
        "milestones": [
            _milestone_summary(item)
            for item in analysis_data["milestones"]
        ],
        "timeline": [_timeline_summary(entry) for entry in timeline],
        "limitations": list(analysis_data["limitations"]),
        "unavailable": [
            {
                "field_name": item.get("field_name"),
                "explanation": item.get("explanation"),
            }
            for item in analysis_data["unavailable"]
        ],
        "message": _advisor_message(recommendations),
    }


def _normalized_question(question: str) -> str:
    normalized = unicodedata.normalize("NFKD", question.casefold())
    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )


def answer_mentor_question(
    database: AlquimistaDatabase,
    *,
    campaign_id: str,
    question: str,
) -> dict[str, Any]:
    """Responde localmente com uma leitura determinística e rastreável."""

    cleaned = " ".join(question.split())
    if not cleaned:
        raise ValueError("Escreva uma pergunta para o Alquimista.")
    if len(cleaned) > 500:
        raise ValueError("A pergunta deve ter no máximo 500 caracteres.")

    dashboard = build_dashboard(database, campaign_id=campaign_id)
    if dashboard.get("status") != "ready":
        raise ValueError("Importe um save antes de consultar o Alquimista.")

    normalized = _normalized_question(cleaned)
    finance = dashboard["finance"]
    operations = dashboard["operations"]
    workforce = dashboard["workforce"]
    portfolio = dashboard["portfolio"]
    campaign = dashboard.get("campaign") or {}
    quests = dashboard.get("quests") or []
    first_quest = quests[0] if quests else None
    evidence: list[dict[str, Any]] = []
    follow_up = [
        "O que devo fazer agora?",
        "Posso expandir com segurança?",
        "O que o próximo export vai provar?",
    ]
    confidence = "medium"
    caution = (
        "Esta resposta usa apenas o último export. Ela não inventa lucro por hora, "
        "demanda ou ROI quando o save não oferece esses dados."
    )

    if any(
        word in normalized
        for word in ("expandir", "expansao", "comprar", "investir", "propriedade")
    ):
        topic = "expansion"
        title = "Expanda somente depois de provar que a base atual pede espaço"
        unstaffed = workforce.get("unstaffed_productive_properties") or []
        headroom = (
            None
            if operations.get("occupancy_percent") is None
            else 100 - int(operations["occupancy_percent"])
        )
        evidence.extend(
            [
                {
                    "label": "Liquidez observada",
                    "value": finance.get("liquid_cash_estimate"),
                    "format": "money",
                },
                {
                    "label": "Folga de armazenamento",
                    "value": headroom,
                    "format": "percent",
                },
                {
                    "label": "Bases produtivas sem equipe",
                    "value": len(unstaffed),
                    "format": "number",
                },
            ]
        )
        if unstaffed:
            answer = (
                "Eu não compraria outra base agora. Há estrutura produtiva sem equipe "
                "observada; primeiro defina responsáveis e me traga outro export para "
                "confirmar se o fluxo melhorou."
            )
        elif headroom is not None and headroom < 20:
            answer = (
                "Há pressão de armazenamento, mas isso ainda não prova falta de "
                "propriedade. Libere espaço e compare o próximo export antes de assumir "
                "um custo permanente."
            )
        else:
            answer = (
                "O save não demonstra um bloqueio de espaço que justifique expansão. "
                "Diga qual compra você considera e use um novo export como linha de base "
                "antes de executá-la."
            )
        action = (
            first_quest["objective"]
            if first_quest
            else "Colete outro momento da campanha antes de realizar uma compra cara."
        )
        follow_up = [
            "Qual risco vem antes da expansão?",
            "Como está minha equipe?",
            "Qual missão devo assumir?",
        ]
    elif any(word in normalized for word in ("caixa", "dinheiro", "saldo", "liquidez")):
        topic = "finance"
        title = "Seu caixa é uma reserva observada, não uma medida de lucro"
        evidence.extend(
            [
                {
                    "label": "Liquidez observada",
                    "value": finance.get("liquid_cash_estimate"),
                    "format": "money",
                },
                {
                    "label": "Saldo online",
                    "value": finance.get("online_balance"),
                    "format": "money",
                },
                {
                    "label": "Patrimônio",
                    "value": finance.get("networth"),
                    "format": "money",
                },
            ]
        )
        answer = (
            "O export mostra quanto está disponível e o patrimônio informado pelo jogo, "
            "mas uma fotografia isolada não separa receita, investimento e consumo. "
            "Preserve uma reserva e compare o próximo momento antes de chamar crescimento "
            "de lucro."
        )
        action = "Importe outro export depois da próxima sessão para medir a direção do caixa."
        confidence = "high"
        follow_up = [
            "Posso expandir com segurança?",
            "Meu estoque está prendendo capital?",
            "O que mudou desde o export anterior?",
        ]
    elif any(
        word in normalized
        for word in ("gargalo", "travando", "problema", "limitando", "ocios")
    ):
        topic = "bottleneck"
        title = "O maior risco observável vem antes da próxima compra"
        headroom = (
            None
            if operations.get("occupancy_percent") is None
            else 100 - int(operations["occupancy_percent"])
        )
        evidence.extend(
            [
                {
                    "label": "Equipamentos ociosos observados",
                    "value": operations.get("idle_count"),
                    "format": "number",
                },
                {
                    "label": "Folga de armazenamento",
                    "value": headroom,
                    "format": "percent",
                },
                {
                    "label": "Bases produtivas sem equipe",
                    "value": len(
                        workforce.get("unstaffed_productive_properties") or []
                    ),
                    "format": "number",
                },
            ]
        )
        if operations.get("idle_count"):
            answer = (
                "Há capacidade instalada aparecendo ociosa. Use ou reserve conscientemente "
                "essa estrutura antes de aumentar a operação."
            )
        elif workforce.get("unstaffed_productive_properties"):
            answer = (
                "A cobertura de equipe é o sinal mais claro: existem bases produtivas sem "
                "funcionários observados. Delegação deve vir antes de escala."
            )
        elif headroom is not None and headroom < 20:
            answer = (
                "A folga de armazenamento está curta. O fluxo pode travar na saída, mesmo "
                "que a produção pareça saudável."
            )
        else:
            answer = (
                "O save não expõe um gargalo inequívoco. A missão prioritária é o melhor "
                "experimento disponível para produzir evidência no próximo export."
            )
        action = (
            first_quest["objective"]
            if first_quest
            else "Execute uma mudança por vez e importe novamente para isolar o efeito."
        )
        follow_up = [
            "Qual missão devo assumir?",
            "Como está minha equipe?",
            "O que o próximo export vai provar?",
        ]
    elif any(
        word in normalized
        for word in ("equipe", "funcionario", "delegar", "automacao", "trabalho manual")
    ):
        topic = "workforce"
        title = "Delegação transforma estrutura comprada em tempo recuperado"
        evidence.extend(
            [
                {
                    "label": "Funcionários observados",
                    "value": workforce.get("employee_count"),
                    "format": "number",
                },
                {
                    "label": "Bases produtivas com equipe",
                    "value": workforce.get("staffed_productive_property_count"),
                    "format": "number",
                },
                {
                    "label": "Bases produtivas sem equipe",
                    "value": len(
                        workforce.get("unstaffed_productive_properties") or []
                    ),
                    "format": "number",
                },
            ]
        )
        gaps = workforce.get("unstaffed_productive_properties") or []
        answer = (
            (
                "Ainda existem bases produtivas sem equipe observada: "
                + ", ".join(str(item) for item in gaps)
                + ". Defina se cada uma será manual, reserva ou automatizada."
            )
            if gaps
            else (
                "As bases produtivas observadas possuem cobertura de equipe. O próximo "
                "passo é confirmar, por dois exports, se essa delegação reduz ociosidade "
                "ou melhora o fluxo."
            )
        )
        action = (
            "Escolha uma tarefa repetitiva para delegar e registre o resultado no próximo export."
        )
        follow_up = [
            "Onde está o gargalo?",
            "Posso expandir?",
            "O que devo medir depois de contratar?",
        ]
    elif any(
        word in normalized
        for word in ("estoque", "produto", "vender", "receita", "portfolio")
    ):
        topic = "portfolio"
        title = "Produto acabado só vira progresso quando encontra saída"
        evidence.extend(
            [
                {
                    "label": "Produtos descobertos",
                    "value": portfolio.get("discovered_count"),
                    "format": "number",
                },
                {
                    "label": "Receitas conhecidas",
                    "value": portfolio.get("recipe_count"),
                    "format": "number",
                },
                {
                    "label": "Produtos vendáveis em estoque",
                    "value": portfolio.get("sellable_product_count"),
                    "format": "number",
                },
                {
                    "label": "Valor de referência do estoque",
                    "value": portfolio.get("inventory_reference_value"),
                    "format": "money",
                },
            ]
        )
        answer = (
            "Há um valor de referência para o estoque reconhecido, mas o save não prova "
            "demanda nem velocidade de venda. Priorize saída do produto acabado antes de "
            "produzir por impulso e use o próximo export para conferir caixa e estoque."
        )
        action = "Venda uma parte controlada do estoque e importe novamente antes de ampliar o lote."
        follow_up = [
            "Meu estoque está prendendo capital?",
            "Como está meu caixa?",
            "Qual produto devo acompanhar?",
        ]
    elif any(
        word in normalized
        for word in ("export", "proximo save", "provar", "medir", "historico", "evolucao")
    ):
        topic = "memory"
        title = "O próximo export transforma conselho em aprendizado"
        evidence.extend(
            [
                {
                    "label": "Momentos confirmados nesta campanha",
                    "value": campaign.get("snapshot_count"),
                    "format": "number",
                },
                {
                    "label": "Exports relacionados",
                    "value": len(dashboard.get("related_exports") or []),
                    "format": "number",
                },
                {
                    "label": "Missões disponíveis",
                    "value": len(quests),
                    "format": "number",
                },
            ]
        )
        answer = (
            "Antes de jogar, escolha uma missão e faça apenas a mudança principal. "
            "Depois exporte novamente: eu compararei caixa, patrimônio e mudanças "
            "operacionais para dizer se a hipótese ganhou ou perdeu força."
        )
        action = (
            first_quest["objective"]
            if first_quest
            else "Jogue uma sessão curta, salve e retorne com o novo ZIP."
        )
        confidence = "high"
        follow_up = [
            "Qual missão devo assumir?",
            "O que mudou desde o export anterior?",
            "Como saber se a decisão funcionou?",
        ]
    else:
        topic = "strategy"
        title = (
            first_quest["title"]
            if first_quest
            else "Faça uma mudança mensurável antes de expandir"
        )
        evidence.extend(
            [
                {
                    "label": "Capítulo da jornada",
                    "value": dashboard["story"]["chapter_title"],
                    "format": "text",
                },
                {
                    "label": "Qualidade do diagnóstico",
                    "value": dashboard["diagnostic"]["decision_readiness_score"],
                    "format": "score",
                },
                {
                    "label": "Missões disponíveis",
                    "value": len(quests),
                    "format": "number",
                },
            ]
        )
        answer = (
            first_quest["briefing"]
            if first_quest
            else (
                "Nenhuma regra crítica foi acionada. Colete outro momento antes de "
                "tomar uma decisão cara."
            )
        )
        action = (
            first_quest["objective"]
            if first_quest
            else "Importe outro export após uma sessão curta e controlada."
        )

    return {
        "topic": topic,
        "title": title,
        "answer": answer,
        "evidence": evidence,
        "action": action,
        "confidence": confidence,
        "caution": caution,
        "follow_up": follow_up,
        "snapshot_id": dashboard["snapshot"]["snapshot_id"],
    }
