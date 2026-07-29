"""Codec JSON determinístico com suporte centralizado a valores decimais."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any


def _reject_non_finite(token: str) -> None:
    raise ValueError(f"Número JSON não finito não é aceito: {token}")


def to_finite_decimal(value: Any) -> Decimal | None:
    """Converte um valor numérico sem aceitar booleanos ou não finitos."""
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return decimal if decimal.is_finite() else None


def decimal_text(value: Decimal) -> str:
    """Representação decimal exata, independente de locale e sem expoente."""
    if not value.is_finite():
        raise ValueError("Decimal não finito não pode ser serializado.")
    text = format(value, "f")
    if value.is_zero() and text.startswith("-"):
        return text[1:]
    return text


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return decimal_text(value)
    raise TypeError(
        f"Objeto do tipo {type(value).__name__} não é serializável como JSON."
    )


def loads(content: str | bytes | bytearray) -> Any:
    """Lê JSON preservando frações em Decimal e inteiros como int."""
    return json.loads(
        content,
        parse_float=Decimal,
        parse_int=int,
        parse_constant=_reject_non_finite,
    )


def dumps(value: object, **options: Any) -> str:
    """Serializa Decimal como string canônica e rejeita floats não finitos."""
    return json.dumps(
        value,
        default=_json_default,
        allow_nan=False,
        **options,
    )


def _restore_decimal(mapping: dict[str, Any], key: str) -> None:
    if key not in mapping or mapping[key] is None:
        return
    restored = to_finite_decimal(mapping[key])
    if restored is not None:
        mapping[key] = restored


def _restore_inventory(inventory: Any) -> None:
    if not isinstance(inventory, dict):
        return
    _restore_decimal(inventory, "cash")
    quantities = inventory.get("quantities")
    if isinstance(quantities, dict):
        for key in quantities:
            _restore_decimal(quantities, key)
    variants = inventory.get("variants")
    if isinstance(variants, dict):
        for values in variants.values():
            if isinstance(values, dict):
                for key in values:
                    _restore_decimal(values, key)
    items = inventory.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                _restore_decimal(item, "quantity")
                _restore_decimal(item, "cash_balance")


def restore_snapshot_decimals(snapshot: Any) -> Any:
    """Restaura dinheiro e quantidades de snapshots persistidos como strings."""
    if not isinstance(snapshot, dict):
        return snapshot
    finance = snapshot.get("finance")
    if isinstance(finance, dict):
        for key in (
            "online_balance",
            "loose_cash",
            "liquid_cash_estimate",
            "networth",
            "lifetime_earnings",
            "weekly_deposit_sum",
            "inventory_list_price_estimate",
            "expenses",
        ):
            _restore_decimal(finance, key)

    products = snapshot.get("products")
    if isinstance(products, dict):
        prices = products.get("prices")
        if isinstance(prices, dict):
            for key in prices:
                _restore_decimal(prices, key)
        entries = products.get("entries")
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    _restore_decimal(entry, "reference_price")

    _restore_inventory(snapshot.get("inventory"))
    players = snapshot.get("players")
    if isinstance(players, list):
        for player in players:
            if isinstance(player, dict):
                _restore_inventory(player.get("inventory"))
    for section in ("properties", "businesses"):
        values = snapshot.get(section)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict):
                    _restore_inventory(value.get("inventory"))
    return snapshot


def loads_snapshot(content: str | bytes | bytearray) -> dict[str, Any]:
    """Lê um snapshot e restaura os tipos decimais conhecidos."""
    value = restore_snapshot_decimals(loads(content))
    if not isinstance(value, dict):
        raise ValueError("O snapshot JSON deve conter um objeto na raiz.")
    return value
