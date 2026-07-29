"""Relatório Markdown conciso a partir de um snapshot."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .json_codec import decimal_text, to_finite_decimal


def money(value: Any) -> str:
    decimal = to_finite_decimal(value)
    if decimal is None:
        return "indisponível"
    return f"${decimal:,.2f}"


def build_markdown(snapshot: dict[str, Any]) -> str:
    game = snapshot["game"]
    finance = snapshot["finance"]
    inventory = snapshot["inventory"]
    lines = [
        "# O Alquimista — Snapshot",
        "",
        f"- Versão do jogo: `{game.get('version')}`",
        f"- Organização: `{game.get('organisation_name') or 'não informada'}`",
        f"- Dia no jogo: **{game.get('elapsed_days')}**",
        (
            "- Tempo jogado: **indisponível**"
            if game.get("playtime_seconds") is None
            else (
                "- Tempo jogado: "
                f"**{round(float(game['playtime_seconds']) / 3600, 2)} h**"
            )
        ),
        "",
        "## Financeiro",
        "",
        f"- Saldo online: **{money(finance['online_balance'])}**",
        f"- Dinheiro físico observado: **{money(finance['loose_cash'])}**",
        f"- Liquidez estimada: **{money(finance['liquid_cash_estimate'])}**",
        f"- Patrimônio líquido: **{money(finance['networth'])}**",
        f"- Ganhos acumulados: **{money(finance['lifetime_earnings'])}**",
        (
            "- Estoque a preços de referência: "
            f"**{money(finance['inventory_list_price_estimate'])}**"
        ),
        "",
        "## Produtos",
        "",
        (
            "Descobertos: "
            f"{', '.join(snapshot['products']['discovered']) or 'nenhum'}"
        ),
        "",
        "| Item | Quantidade | Preço de referência | Valor estimado |",
        "|---|---:|---:|---:|",
    ]
    prices = snapshot["products"]["prices"]
    for item_id, quantity in inventory["quantities"].items():
        price = to_finite_decimal(prices.get(item_id)) or Decimal("0")
        quantity_decimal = to_finite_decimal(quantity) or Decimal("0")
        lines.append(
            f"| `{item_id}` | {decimal_text(quantity_decimal)} | {money(price)} | "
            f"{money(quantity_decimal * price)} |"
        )

    lines += [
        "",
        "## Propriedades",
        "",
        "| Propriedade | Possuída | Funcionários | Objetos |",
        "|---|:---:|---:|---:|",
    ]
    for prop in snapshot["properties"]:
        lines.append(
            f"| {prop['name']} | {'Sim' if prop['owned'] else 'Não'} | "
            f"{prop['employee_count']} | {prop['object_count']} |"
        )

    lines += ["", "## Observações", ""]
    owned = [prop for prop in snapshot["properties"] if prop["owned"]]
    staffed = [prop for prop in owned if prop["employee_count"] > 0]
    lines.append(f"- Propriedades possuídas observadas: **{len(owned)}**.")
    lines.append(
        f"- Propriedades possuídas com funcionários observados: **{len(staffed)}**."
    )
    if finance["inventory_list_price_estimate"] == 0:
        lines.append(
            "- Nenhum estoque precificável foi observado no escopo normalizado."
        )
    lines.append(
        "- Inferências econômicas exigem evidência adicional; este relatório "
        "não atribui significado a campos desconhecidos."
    )
    availability = snapshot.get("availability")
    if isinstance(availability, dict):
        unavailable = [
            (section, value)
            for section, value in sorted(availability.items())
            if isinstance(value, dict) and value.get("state") != "observed"
        ]
        if unavailable:
            lines += ["", "## Disponibilidade", ""]
            lines.extend(
                f"- `{section}`: **{value.get('state')}** — "
                f"{value.get('explanation')}"
                for section, value in unavailable
            )
    return "\n".join(lines) + "\n"
