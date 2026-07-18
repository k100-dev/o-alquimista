"""Normalização read-only dos JSONs de um save."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from .archive import ESSENTIAL_FILES, extracted_save
from .errors import IncompleteSaveError, SaveDataError
from .models import (
    DataOrigin,
    Employee,
    Finance,
    GameTime,
    Inventory,
    InventoryItem,
    Metadata,
    NormalizedSnapshot,
    Npc,
    NpcCollection,
    Product,
    ProductCatalog,
    Progression,
    Property,
    UnknownField,
    Vehicle,
)


def load_json(path: Path) -> Any:
    """Lê JSON sem abrir o arquivo para escrita."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SaveDataError(f"Não foi possível ler {path.name}: {exc}") from exc


def decode_embedded_json(value: Any) -> Any:
    """Decodifica recursivamente strings JSON usadas dentro dos saves."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return decode_embedded_json(json.loads(stripped))
            except json.JSONDecodeError:
                return value
        return value
    if isinstance(value, list):
        return [decode_embedded_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): decode_embedded_json(item) for key, item in value.items()}
    return value


def _as_object(value: Any, path: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SaveDataError(f"{path.name} deve conter um objeto JSON na raiz.")
    return value


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _unknown_fields(
    data: dict[str, Any],
    known: set[str],
    relative_file: str,
) -> tuple[UnknownField, ...]:
    return tuple(
        UnknownField(
            name=key,
            raw=value,
            origin=DataOrigin(file=relative_file, field=key),
        )
        for key, value in data.items()
        if key not in known
    )


def _origin(file: str, field: str) -> DataOrigin:
    return DataOrigin(file=file, field=field)


def _parse_items(
    values: list[Any] | None,
    relative_file: str,
    field_prefix: str,
) -> list[InventoryItem]:
    parsed: list[InventoryItem] = []
    for index, undecoded in enumerate(values or []):
        raw = decode_embedded_json(undecoded)
        if not isinstance(raw, dict) or not raw.get("ID"):
            continue
        quantity = _number(raw.get("Quantity"))
        if quantity <= 0:
            continue
        parsed.append(
            InventoryItem(
                item_id=str(raw["ID"]),
                quantity=quantity,
                cash_balance=_number(raw.get("CashBalance")),
                quality=str(raw["Quality"]) if raw.get("Quality") is not None else None,
                packaging_id=(
                    str(raw["PackagingID"])
                    if raw.get("PackagingID") is not None
                    else None
                ),
                origin=_origin(relative_file, f"{field_prefix}[{index}]"),
                raw=raw,
            )
        )
    return parsed


def _summarize_items(items: Iterable[InventoryItem]) -> Inventory:
    item_list = tuple(items)
    quantities: Counter[str] = Counter()
    variants: dict[str, Counter[str]] = defaultdict(Counter)
    cash = 0.0
    origins: list[DataOrigin] = []
    for item in item_list:
        quantities[item.item_id] += item.quantity
        cash += item.cash_balance
        origins.append(item.origin)
        if item.quality or item.packaging_id:
            variant = f"{item.quality or 'unknown'} / {item.packaging_id or 'unknown'}"
            variants[item.item_id][variant] += item.quantity
    return Inventory(
        quantities=dict(quantities.most_common()),
        cash=round(cash, 2),
        variants={key: dict(value) for key, value in variants.items()},
        items=item_list,
        origins=tuple(origins),
    )


def _property_summary(save_root: Path, path: Path) -> Property:
    relative = path.relative_to(save_root).as_posix()
    data = _as_object(decode_embedded_json(load_json(path)), path)
    objects = data.get("Objects") if isinstance(data.get("Objects"), list) else []
    employee_values = (
        data.get("Employees") if isinstance(data.get("Employees"), list) else []
    )
    object_types: Counter[str] = Counter()
    inventory_items: list[InventoryItem] = []
    for index, obj in enumerate(objects):
        if not isinstance(obj, dict):
            continue
        object_types[str(obj.get("ObjectType", obj.get("DataType", "unknown")))] += 1
        for key in ("Contents", "Inventory", "StorageContents"):
            content = obj.get(key)
            if isinstance(content, dict) and isinstance(content.get("Items"), list):
                inventory_items.extend(
                    _parse_items(
                        content["Items"],
                        relative,
                        f"Objects[{index}].{key}.Items",
                    )
                )

    employees = tuple(
        Employee(
            employee_id=(
                str(raw.get("ID")) if isinstance(raw, dict) and raw.get("ID") else None
            ),
            property_name=path.stem,
            origin=_origin(relative, f"Employees[{index}]"),
            raw=raw,
            unknown=(
                _unknown_fields(raw, {"ID"}, relative)
                if isinstance(raw, dict)
                else ()
            ),
        )
        for index, raw in enumerate(employee_values)
    )
    known = {"PropertyCode", "IsOwned", "Employees", "Objects"}
    return Property(
        name=path.stem,
        code=str(data["PropertyCode"]) if data.get("PropertyCode") is not None else None,
        owned=bool(data.get("IsOwned")),
        employee_count=len(employee_values),
        object_count=len(objects),
        object_types=dict(object_types.most_common()),
        inventory=_summarize_items(inventory_items),
        origin=_origin(relative, "$"),
        raw=data,
        origins={
            "name": _origin(relative, "$filename"),
            "code": _origin(relative, "PropertyCode"),
            "owned": _origin(relative, "IsOwned"),
            "employee_count": _origin(relative, "Employees"),
            "object_count": _origin(relative, "Objects"),
            "object_types": _origin(
                relative, "Objects[].ObjectType|Objects[].DataType"
            ),
            "inventory": _origin(
                relative,
                "Objects[].Contents|Inventory|StorageContents.Items",
            ),
        },
        employees=employees,
        unknown=_unknown_fields(data, known, relative),
    )


def _parse_npcs(save_root: Path) -> NpcCollection:
    path = save_root / "NPCs.json"
    if not path.is_file():
        return NpcCollection(total=0, unlocked_relationships=0, entries=())
    relative = "NPCs.json"
    data = _as_object(decode_embedded_json(load_json(path)), path)
    raw_npcs = data.get("NPCs") if isinstance(data.get("NPCs"), list) else []
    entries: list[Npc] = []
    unlocked_count = 0
    for index, raw in enumerate(raw_npcs):
        relationship_unlocked: bool | None = None
        npc_id: str | None = None
        unknown: tuple[UnknownField, ...] = ()
        if isinstance(raw, dict):
            npc_id = str(raw["ID"]) if raw.get("ID") is not None else None
            additional = (
                raw.get("AdditionalDatas")
                if isinstance(raw.get("AdditionalDatas"), list)
                else []
            )
            for extra_index, extra in enumerate(additional):
                if not isinstance(extra, dict) or extra.get("Name") != "Relationship":
                    continue
                contents = decode_embedded_json(extra.get("Contents"))
                if isinstance(contents, dict) and "Unlocked" in contents:
                    relationship_unlocked = bool(contents["Unlocked"])
                    if relationship_unlocked:
                        unlocked_count += 1
            unknown = _unknown_fields(raw, {"ID", "AdditionalDatas"}, relative)
        entries.append(
            Npc(
                npc_id=npc_id,
                relationship_unlocked=relationship_unlocked,
                origin=_origin(relative, f"NPCs[{index}]"),
                raw=raw,
                unknown=unknown,
            )
        )
    return NpcCollection(
        total=len(raw_npcs),
        unlocked_relationships=unlocked_count,
        entries=tuple(entries),
        origins={
            "total": _origin(relative, "NPCs"),
            "unlocked_relationships": _origin(
                relative, "NPCs[].AdditionalDatas[Relationship].Contents.Unlocked"
            ),
        },
        unknown=_unknown_fields(data, {"NPCs"}, relative),
    )


def _parse_vehicles(
    save_root: Path,
) -> tuple[tuple[Vehicle, ...], tuple[UnknownField, ...]]:
    path = save_root / "Vehicles.json"
    if not path.is_file():
        return (), ()
    relative = "Vehicles.json"
    data = decode_embedded_json(load_json(path))
    if isinstance(data, dict):
        raw_vehicles = data.get("Vehicles", [])
        root_unknown = _unknown_fields(data, {"Vehicles"}, relative)
    else:
        raw_vehicles = data
        root_unknown = ()
    if not isinstance(raw_vehicles, list):
        return (), root_unknown
    return (
        tuple(
            Vehicle(
                vehicle_id=(
                    str(raw.get("ID"))
                    if isinstance(raw, dict) and raw.get("ID")
                    else None
                ),
                origin=_origin(relative, f"Vehicles[{index}]"),
                raw=raw,
                unknown=(
                    _unknown_fields(raw, {"ID"}, relative)
                    if isinstance(raw, dict)
                    else ()
                ),
            )
            for index, raw in enumerate(raw_vehicles)
        ),
        root_unknown,
    )


def _archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_unmapped_files(
    save_root: Path,
    handled_files: set[Path],
) -> tuple[UnknownField, ...]:
    unknown: list[UnknownField] = []
    handled = {path.resolve() for path in handled_files}
    for path in sorted(save_root.rglob("*.json")):
        if path.resolve() in handled:
            continue
        relative = path.relative_to(save_root).as_posix()
        unknown.append(
            UnknownField(
                name=relative,
                raw=decode_embedded_json(load_json(path)),
                origin=_origin(relative, "$"),
            )
        )
    return tuple(unknown)


def read_save_model(
    save_root: Path,
    *,
    source_archive: Path | None = None,
    archive_root: str | None = None,
) -> NormalizedSnapshot:
    """Lê uma raiz já validada sem realizar nenhuma escrita nela."""
    save_root = save_root.expanduser().resolve()
    missing = [name for name in ESSENTIAL_FILES if not (save_root / name).is_file()]
    if missing:
        raise IncompleteSaveError(
            f"Save incompleto; arquivos essenciais ausentes: {', '.join(missing)}"
        )

    money_path = save_root / "Money.json"
    products_path = save_root / "Products.json"
    time_path = save_root / "Time.json"
    rank_path = save_root / "Rank.json"
    money = _as_object(load_json(money_path), money_path)
    products = _as_object(decode_embedded_json(load_json(products_path)), products_path)
    time_data = _as_object(load_json(time_path), time_path)
    rank = _as_object(load_json(rank_path), rank_path)
    handled_files = {money_path, products_path, time_path, rank_path}

    game_path = save_root / "Game.json"
    game: dict[str, Any] = {}
    if game_path.is_file():
        game = _as_object(load_json(game_path), game_path)
        handled_files.add(game_path)

    all_items: list[InventoryItem] = []
    players: list[dict[str, Any]] = []
    players_dir = save_root / "Players"
    if players_dir.is_dir():
        for player_dir in sorted(path for path in players_dir.iterdir() if path.is_dir()):
            inventory_path = player_dir / "Inventory.json"
            if not inventory_path.is_file():
                continue
            relative = inventory_path.relative_to(save_root).as_posix()
            inventory_data = _as_object(load_json(inventory_path), inventory_path)
            items = _parse_items(inventory_data.get("Items"), relative, "Items")
            all_items.extend(items)
            handled_files.add(inventory_path)
            players.append(
                {
                    "player": player_dir.name,
                    "inventory": _summarize_items(items),
                    "origin": _origin(relative, "$"),
                    "unknown": _unknown_fields(inventory_data, {"Items"}, relative),
                }
            )

    world_entity_count = 0
    world_path = save_root / "WorldStorageEntities.json"
    if world_path.is_file():
        relative = "WorldStorageEntities.json"
        world = _as_object(decode_embedded_json(load_json(world_path)), world_path)
        entities = world.get("Entities") if isinstance(world.get("Entities"), list) else []
        world_entity_count = len(entities)
        for index, entity in enumerate(entities):
            contents = entity.get("Contents") if isinstance(entity, dict) else None
            if isinstance(contents, dict):
                all_items.extend(
                    _parse_items(
                        contents.get("Items"),
                        relative,
                        f"Entities[{index}].Contents.Items",
                    )
                )

    properties = tuple(
        _property_summary(save_root, path)
        for path in sorted((save_root / "Properties").glob("*.json"))
    ) if (save_root / "Properties").is_dir() else ()
    businesses = tuple(
        _property_summary(save_root, path)
        for path in sorted((save_root / "Businesses").glob("*.json"))
    ) if (save_root / "Businesses").is_dir() else ()
    handled_files.update(save_root / "Properties" / f"{prop.name}.json" for prop in properties)
    handled_files.update(save_root / "Businesses" / f"{prop.name}.json" for prop in businesses)

    npcs = _parse_npcs(save_root)
    npc_path = save_root / "NPCs.json"
    if npc_path.is_file():
        handled_files.add(npc_path)
    vehicles, vehicle_root_unknown = _parse_vehicles(save_root)
    vehicle_path = save_root / "Vehicles.json"
    if vehicle_path.is_file():
        handled_files.add(vehicle_path)

    prices = {
        str(row["String"]): row.get("Int")
        for row in products.get("ProductPrices", [])
        if isinstance(row, dict) and row.get("String") is not None
    }
    discovered = tuple(str(value) for value in products.get("DiscoveredProducts", []))
    listed = tuple(str(value) for value in products.get("ListedProducts", []))
    product_ids = sorted(set(discovered) | set(listed) | set(prices))
    product_entries = tuple(
        Product(
            product_id=product_id,
            discovered=product_id in discovered,
            listed=product_id in listed,
            reference_price=(
                _number(prices[product_id]) if prices.get(product_id) is not None else None
            ),
            origin=_origin("Products.json", "$"),
            raw=None,
        )
        for product_id in product_ids
    )

    inventory = _summarize_items(all_items)
    market_value = round(
        sum(
            quantity * _number(prices.get(item_id))
            for item_id, quantity in inventory.quantities.items()
        ),
        2,
    )
    employees = tuple(
        employee
        for prop in (*properties, *businesses)
        for employee in prop.employees
    )

    archive = source_archive.expanduser().resolve() if source_archive else None
    version = money.get("GameVersion") or time_data.get("GameVersion")
    metadata = Metadata(
        product_name="O Alquimista",
        schema_version="1.0",
        imported_at=None,
        source_archive=archive.name if archive else None,
        archive_sha256=_archive_sha256(archive) if archive else None,
        save_root=archive_root if archive_root is not None else save_root.name,
        game_version=str(version) if version is not None else None,
        organisation_name=(
            str(game["OrganisationName"])
            if game.get("OrganisationName") is not None
            else None
        ),
        origins={
            "product_name": _origin("<generated>", "product_name"),
            "schema_version": _origin("<generated>", "schema_version"),
            "imported_at": _origin("<database>", "imported_at"),
            "source_archive": _origin("<archive>", "$filename"),
            "archive_sha256": _origin("<archive>", "$bytes"),
            "save_root": _origin("<archive>", "$detected_root"),
            "game_version": _origin(
                "Money.json" if money.get("GameVersion") else "Time.json",
                "GameVersion",
            ),
            "organisation_name": _origin("Game.json", "OrganisationName"),
        },
        unknown=_unknown_fields(game, {"OrganisationName"}, "Game.json"),
    )

    return NormalizedSnapshot(
        metadata=metadata,
        finance=Finance(
            online_balance=round(_number(money.get("OnlineBalance")), 2),
            loose_cash=inventory.cash,
            liquid_cash_estimate=round(
                _number(money.get("OnlineBalance")) + inventory.cash, 2
            ),
            networth=round(_number(money.get("Networth")), 2),
            lifetime_earnings=round(_number(money.get("LifetimeEarnings")), 2),
            weekly_deposit_sum=round(_number(money.get("WeeklyDepositSum")), 2),
            inventory_list_price_estimate=market_value,
            origins={
                "online_balance": _origin("Money.json", "OnlineBalance"),
                "loose_cash": _origin("Players/*/Inventory.json", "Items[].CashBalance"),
                "liquid_cash_estimate": _origin("Money.json", "OnlineBalance"),
                "networth": _origin("Money.json", "Networth"),
                "lifetime_earnings": _origin("Money.json", "LifetimeEarnings"),
                "weekly_deposit_sum": _origin("Money.json", "WeeklyDepositSum"),
                "inventory_list_price_estimate": _origin(
                    "Products.json", "ProductPrices"
                ),
            },
            unknown=_unknown_fields(
                money,
                {
                    "GameVersion",
                    "OnlineBalance",
                    "Networth",
                    "LifetimeEarnings",
                    "WeeklyDepositSum",
                },
                "Money.json",
            ),
        ),
        time=GameTime(
            elapsed_days=time_data.get("ElapsedDays"),
            time_of_day=time_data.get("TimeOfDay"),
            playtime_seconds=time_data.get("Playtime"),
            origins={
                "elapsed_days": _origin("Time.json", "ElapsedDays"),
                "time_of_day": _origin("Time.json", "TimeOfDay"),
                "playtime_seconds": _origin("Time.json", "Playtime"),
            },
            unknown=_unknown_fields(
                time_data,
                {"GameVersion", "ElapsedDays", "TimeOfDay", "Playtime"},
                "Time.json",
            ),
        ),
        progression=Progression(
            rank=rank.get("Rank"),
            tier=rank.get("Tier"),
            xp=rank.get("XP"),
            total_xp=rank.get("TotalXP"),
            unlocked_regions=tuple(rank.get("UnlockedRegions", [])),
            origins={
                "rank": _origin("Rank.json", "Rank"),
                "tier": _origin("Rank.json", "Tier"),
                "xp": _origin("Rank.json", "XP"),
                "total_xp": _origin("Rank.json", "TotalXP"),
                "unlocked_regions": _origin("Rank.json", "UnlockedRegions"),
            },
            unknown=_unknown_fields(
                rank,
                {"Rank", "Tier", "XP", "TotalXP", "UnlockedRegions"},
                "Rank.json",
            ),
        ),
        products=ProductCatalog(
            discovered=discovered,
            listed=listed,
            prices=prices,
            mix_recipes=tuple(products.get("MixRecipes", [])),
            active_mix=products.get("ActiveMixOperation", {}),
            entries=product_entries,
            raw=products,
            origins={
                "discovered": _origin("Products.json", "DiscoveredProducts"),
                "listed": _origin("Products.json", "ListedProducts"),
                "prices": _origin("Products.json", "ProductPrices"),
                "mix_recipes": _origin("Products.json", "MixRecipes"),
                "active_mix": _origin("Products.json", "ActiveMixOperation"),
            },
            unknown=_unknown_fields(
                products,
                {
                    "DiscoveredProducts",
                    "ListedProducts",
                    "ProductPrices",
                    "MixRecipes",
                    "ActiveMixOperation",
                },
                "Products.json",
            ),
        ),
        inventory=inventory,
        players=tuple(players),
        world_storage_entity_count=world_entity_count,
        properties=properties,
        businesses=businesses,
        npcs=npcs,
        employees=employees,
        vehicles=vehicles,
        unknown=(
            *vehicle_root_unknown,
            *_collect_unmapped_files(save_root, handled_files),
        ),
    )


def read_save(save_root: Path) -> dict[str, Any]:
    """API compatível para leitura direta de diretório."""
    return read_save_model(save_root).to_dict()


def snapshot_from_zip(archive_path: Path) -> NormalizedSnapshot:
    """Importa um ZIP em área temporária e devolve o snapshot em memória."""
    archive = archive_path.expanduser().resolve()
    with extracted_save(archive) as (save_root, archive_root):
        return read_save_model(
            save_root,
            source_archive=archive,
            archive_root=archive_root,
        )
