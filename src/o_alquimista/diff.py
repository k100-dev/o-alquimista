"""Comparação de snapshots normalizados (funcionalidade preservada)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .json_codec import to_finite_decimal


def _number_delta(current: Any, previous: Any) -> Decimal:
    current_decimal = to_finite_decimal(current) or Decimal("0")
    previous_decimal = to_finite_decimal(previous) or Decimal("0")
    return current_decimal - previous_decimal


def diff_snapshots(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    finance_keys = [
        "online_balance",
        "loose_cash",
        "liquid_cash_estimate",
        "networth",
        "lifetime_earnings",
        "inventory_list_price_estimate",
    ]
    finance = {
        key: _number_delta(
            current["finance"].get(key),
            previous["finance"].get(key),
        )
        for key in finance_keys
    }
    previous_items = previous.get("inventory", {}).get("quantities", {})
    current_items = current.get("inventory", {}).get("quantities", {})
    item_ids = sorted(set(previous_items) | set(current_items))
    inventory = {
        item_id: _number_delta(
            current_items.get(item_id),
            previous_items.get(item_id),
        )
        for item_id in item_ids
    }
    return {
        "from_day": previous.get("game", {}).get("elapsed_days"),
        "to_day": current.get("game", {}).get("elapsed_days"),
        "finance_delta": finance,
        "inventory_delta": {
            key: value for key, value in inventory.items() if value != 0
        },
        "new_discovered_products": sorted(
            set(current.get("products", {}).get("discovered", []))
            - set(previous.get("products", {}).get("discovered", []))
        ),
    }
