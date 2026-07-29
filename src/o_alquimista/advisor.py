"""Projeções curadas para a experiência consultiva local."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .database import AlquimistaDatabase
from .json_codec import to_finite_decimal


def _decimal_text(value: Any) -> str | None:
    decimal = to_finite_decimal(value)
    return format(decimal, "f") if decimal is not None else None


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
        cards.append(
            {
                "name": prop.get("name"),
                "employee_count": prop.get("employee_count"),
                "object_count": prop.get("object_count"),
                "categories": dict(sorted(categories.items())),
                "slot_count": slot_count,
                "occupied_slot_count": occupied,
                "occupancy_percent": (
                    round((occupied / slot_count) * 100)
                    if slot_count
                    else None
                ),
            }
        )
    return cards


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

    return {
        "status": "ready",
        "campaigns": campaigns,
        "selected_campaign_id": selected_campaign_id,
        "campaign": next(
            (
                item
                for item in campaigns
                if str(item["campaign_id"]) == selected_campaign_id
            ),
            None,
        ),
        "snapshot": {
            "snapshot_id": snapshot_record["snapshot_id"],
            "game_version": (snapshot.get("metadata") or {}).get("game_version"),
            "elapsed_days": game.get("elapsed_days"),
            "time_of_day": game.get("time_of_day"),
        },
        "finance": {
            "online_balance": _decimal_text(finance.get("online_balance")),
            "liquid_cash_estimate": _decimal_text(
                finance.get("liquid_cash_estimate")
            ),
            "networth": _decimal_text(finance.get("networth")),
            "lifetime_earnings": _decimal_text(finance.get("lifetime_earnings")),
        },
        "operations": {
            "owned_property_count": len(_property_cards(snapshot)),
            "equipment_count": len(operational_rows),
            "active_count": active_count,
            "idle_count": idle_count,
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
        },
        "properties": _property_cards(snapshot),
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
