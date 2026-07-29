"""Normalização read-only dos JSONs de um save."""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from .archive import ESSENTIAL_FILES, extracted_save
from .errors import IncompleteSaveError, InvalidArchiveError, SaveDataError
from .evidence import deterministic_id
from .identity import fingerprint_archive
from .json_codec import loads as json_loads
from .json_codec import to_finite_decimal
from .memory_models import ArchiveFingerprint
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
    OperationalContainer,
    OperationalObject,
    Product,
    ProductCatalog,
    Progression,
    Property,
    SectionAvailability,
    SectionAvailabilityState,
    UnknownField,
    Vehicle,
)


def load_json(path: Path) -> Any:
    """Lê JSON sem abrir o arquivo para escrita."""
    try:
        return json_loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise SaveDataError(f"Não foi possível ler {path.name}: {exc}") from exc


def decode_embedded_json(value: Any) -> Any:
    """Decodifica recursivamente strings JSON usadas dentro dos saves."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return decode_embedded_json(json_loads(stripped))
            except ValueError:
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


def _decimal_number(value: Any) -> Decimal:
    decimal = to_finite_decimal(value)
    return decimal if decimal is not None else Decimal("0")


def _optional_money(value: Any) -> Decimal | None:
    return to_finite_decimal(value)


def _metric_number(value: Any) -> int | float | None:
    """Conserva contagens inteiras e usa float apenas para métricas não monetárias."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, float):
        return value
    return None


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


def _availability(
    state: SectionAvailabilityState,
    *source_files: str,
    explanation: str,
) -> SectionAvailability:
    return SectionAvailability(
        state=state,
        source_files=tuple(source_files),
        explanation=explanation,
    )


_OBJECT_CATEGORY_BY_DATA_TYPE = {
    "PotData": "cultivation",
    "MixingStationData": "mixing",
    "PackagingStationData": "packaging",
    "PlaceableStorageData": "storage",
    "ToggleableItemData": "utility",
    "TrashContainerData": "waste",
    "GridItemData": "fixture",
    "ProceduralGridItemData": "fixture",
    "SurfaceItemData": "fixture",
}
_OBJECT_CONTAINER_FIELDS = (
    "Contents",
    "Inventory",
    "StorageContents",
    "MixerContents",
    "OutputContents",
    "ProductContents",
)


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
        quantity = _decimal_number(raw.get("Quantity"))
        if quantity <= 0:
            continue
        parsed.append(
            InventoryItem(
                item_id=str(raw["ID"]),
                quantity=quantity,
                cash_balance=_decimal_number(raw.get("CashBalance")),
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


def _object_item_id(payload: dict[str, Any]) -> str | None:
    item = payload.get("ItemString")
    if isinstance(item, dict) and item.get("ID") is not None:
        return str(item["ID"])
    if isinstance(item, str) and item:
        return item
    return None


def _operational_object(
    raw_object: dict[str, Any],
    *,
    relative_file: str,
    index: int,
) -> OperationalObject:
    base_data = raw_object.get("BaseData")
    payload = base_data if isinstance(base_data, dict) else raw_object
    payload_path = (
        f"Objects[{index}].BaseData"
        if isinstance(base_data, dict)
        else f"Objects[{index}]"
    )
    data_type_value = (
        raw_object.get("DataType")
        or raw_object.get("ObjectType")
        or payload.get("DataType")
    )
    data_type = str(data_type_value) if data_type_value is not None else None
    item_id = _object_item_id(payload)
    guid = payload.get("GUID")
    instance_id = deterministic_id(
        "object",
        str(guid) if guid is not None else relative_file,
        index if guid is None else None,
        data_type,
        item_id,
    )

    containers: list[OperationalContainer] = []
    for container_name in _OBJECT_CONTAINER_FIELDS:
        content = payload.get(container_name)
        if not isinstance(content, dict) or not isinstance(content.get("Items"), list):
            continue
        field_prefix = f"{payload_path}.{container_name}.Items"
        items = _parse_items(
            content["Items"],
            relative_file,
            field_prefix,
        )
        containers.append(
            OperationalContainer(
                name=container_name,
                slot_count=len(content["Items"]),
                occupied_slot_count=len(items),
                inventory=_summarize_items(items),
                origin=_origin(
                    relative_file,
                    f"{payload_path}.{container_name}",
                ),
            )
        )

    category = _OBJECT_CATEGORY_BY_DATA_TYPE.get(data_type or "", "unknown")
    operational_state = "unknown"
    state: dict[str, Any] = {}
    if data_type == "PotData":
        plant = payload.get("PlantData")
        has_plant = isinstance(plant, dict) and bool(plant.get("SeedID"))
        operational_state = "active" if has_plant else "idle"
        state["has_plant"] = has_plant
        state["growth_progress"] = (
            _metric_number(plant.get("GrowthProgress"))
            if isinstance(plant, dict)
            else None
        )
    elif data_type == "MixingStationData":
        operation = payload.get("CurrentMixOperation")
        has_operation = isinstance(operation, dict) and any(
            value not in (None, "", 0, False, [], {})
            for value in operation.values()
        )
        operational_state = "active" if has_operation else "idle"
        state["has_operation"] = has_operation
        state["operation"] = (
            {
                "ingredient_id": (
                    str(operation["IngredientID"])
                    if operation.get("IngredientID") not in (None, "")
                    else None
                ),
                "product_id": (
                    str(operation["ProductID"])
                    if operation.get("ProductID") not in (None, "")
                    else None
                ),
                "product_quality": _metric_number(
                    operation.get("ProductQuality")
                ),
                "quantity": to_finite_decimal(operation.get("Quantity")),
            }
            if isinstance(operation, dict)
            else None
        )
        state["current_mix_time"] = _metric_number(payload.get("CurrentMixTime"))
    elif data_type == "ToggleableItemData" and isinstance(
        payload.get("IsOn"),
        bool,
    ):
        operational_state = "active" if payload["IsOn"] else "idle"
        state["is_on"] = payload["IsOn"]

    object_origin = f"Objects[{index}]"
    return OperationalObject(
        instance_id=instance_id,
        item_id=item_id,
        data_type=data_type,
        category=category,
        operational_state=operational_state,
        containers=tuple(containers),
        state=state,
        origin=_origin(relative_file, object_origin),
        raw=raw_object,
        origins={
            "instance_id": _origin(relative_file, f"{payload_path}.GUID"),
            "item_id": _origin(
                relative_file,
                f"{payload_path}.ItemString.ID",
            ),
            "data_type": _origin(
                relative_file,
                (
                    f"{object_origin}.DataType"
                    if raw_object.get("DataType") is not None
                    else f"{object_origin}.ObjectType"
                ),
            ),
            "operational_state": _origin(
                relative_file,
                payload_path,
            ),
        },
        unknown=_unknown_fields(
            raw_object,
            {
                "AdditionalDatas",
                "BaseData",
                "DataType",
                "DataVersion",
                "GameVersion",
                "ObjectType",
            },
            relative_file,
        ),
    )


def _summarize_items(items: Iterable[InventoryItem]) -> Inventory:
    item_list = tuple(items)
    quantities: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    variants: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    cash = Decimal("0")
    origins: list[DataOrigin] = []
    for item in item_list:
        quantities[item.item_id] += item.quantity
        cash += item.cash_balance
        origins.append(item.origin)
        if item.quality or item.packaging_id:
            variant = f"{item.quality or 'unknown'} / {item.packaging_id or 'unknown'}"
            variants[item.item_id][variant] += item.quantity
    return Inventory(
        quantities=dict(
            sorted(
                quantities.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        cash=cash,
        variants={
            key: dict(sorted(value.items()))
            for key, value in sorted(variants.items())
        },
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
    operational_objects: list[OperationalObject] = []
    inventory_items: list[InventoryItem] = []
    for index, obj in enumerate(objects):
        if not isinstance(obj, dict):
            continue
        operational_object = _operational_object(
            obj,
            relative_file=relative,
            index=index,
        )
        operational_objects.append(operational_object)
        object_types[operational_object.data_type or "unknown"] += 1
        inventory_items.extend(
            item
            for container in operational_object.containers
            for item in container.inventory.items
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
                "Objects[].BaseData.*Contents.Items",
            ),
        },
        employees=employees,
        objects=tuple(operational_objects),
        unknown=_unknown_fields(data, known, relative),
    )


def _parse_property_section(
    save_root: Path,
    directory_name: str,
) -> tuple[tuple[Property, ...], SectionAvailability, set[Path]]:
    directory = save_root / directory_name
    if not directory.is_dir():
        return (
            (),
            _availability(
                "missing",
                directory_name,
                explanation=f"{directory_name}/ não foi encontrado no export.",
            ),
            set(),
        )
    paths = set(directory.glob("*.json"))
    parsed: list[Property] = []
    invalid_files: list[str] = []
    for path in sorted(paths):
        try:
            parsed.append(_property_summary(save_root, path))
        except SaveDataError:
            invalid_files.append(path.relative_to(save_root).as_posix())
    if invalid_files:
        return (
            tuple(parsed),
            _availability(
                "invalid",
                *sorted(invalid_files),
                explanation=(
                    f"{directory_name}/ contém arquivo(s) que não puderam ser "
                    "normalizados."
                ),
            ),
            paths,
        )
    return (
        tuple(parsed),
        _availability(
            "observed",
            directory_name,
            explanation=(
                f"Coleção {directory_name} observada; diretório vazio é "
                "uma observação válida."
            ),
        ),
        paths,
    )


def _parse_npcs(
    save_root: Path,
) -> tuple[NpcCollection, SectionAvailability]:
    path = save_root / "NPCs.json"
    if not path.is_file():
        return (
            NpcCollection(total=0, unlocked_relationships=0, entries=()),
            _availability(
                "missing",
                "NPCs.json",
                explanation="NPCs.json não foi encontrado no export.",
            ),
        )
    relative = "NPCs.json"
    try:
        data = _as_object(decode_embedded_json(load_json(path)), path)
    except SaveDataError as exc:
        return (
            NpcCollection(total=0, unlocked_relationships=0, entries=()),
            _availability(
                "invalid",
                relative,
                explanation=f"NPCs.json não pôde ser normalizado: {exc}",
            ),
        )
    if not isinstance(data.get("NPCs"), list):
        return (
            NpcCollection(
                total=0,
                unlocked_relationships=0,
                entries=(),
                unknown=_unknown_fields(data, set(), relative),
            ),
            _availability(
                "invalid",
                relative,
                explanation="NPCs.json não contém a coleção NPCs esperada.",
            ),
        )
    raw_npcs = data["NPCs"]
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
    return (
        NpcCollection(
            total=len(raw_npcs),
            unlocked_relationships=unlocked_count,
            entries=tuple(entries),
            origins={
                "total": _origin(relative, "NPCs"),
                "unlocked_relationships": _origin(
                    relative,
                    "NPCs[].AdditionalDatas[Relationship].Contents.Unlocked",
                ),
            },
            unknown=_unknown_fields(data, {"NPCs"}, relative),
        ),
        _availability(
            "observed",
            relative,
            explanation="Coleção NPCs observada em NPCs.json.",
        ),
    )


def _parse_vehicles(
    save_root: Path,
) -> tuple[
    tuple[Vehicle, ...],
    tuple[UnknownField, ...],
    SectionAvailability,
]:
    path = save_root / "Vehicles.json"
    if not path.is_file():
        return (
            (),
            (),
            _availability(
                "missing",
                "Vehicles.json",
                explanation="Vehicles.json não foi encontrado no export.",
            ),
        )
    relative = "Vehicles.json"
    try:
        data = decode_embedded_json(load_json(path))
    except SaveDataError as exc:
        return (
            (),
            (),
            _availability(
                "invalid",
                relative,
                explanation=f"Vehicles.json não pôde ser normalizado: {exc}",
            ),
        )
    if isinstance(data, dict):
        raw_vehicles = data.get("Vehicles")
        root_unknown = _unknown_fields(data, {"Vehicles"}, relative)
    else:
        raw_vehicles = data
        root_unknown = ()
    if not isinstance(raw_vehicles, list):
        return (
            (),
            root_unknown,
            _availability(
                "invalid",
                relative,
                explanation="Vehicles.json não contém uma coleção de veículos.",
            ),
        )
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
        _availability(
            "observed",
            relative,
            explanation="Coleção de veículos observada em Vehicles.json.",
        ),
    )


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
    archive_fingerprint: ArchiveFingerprint | None = None,
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
    inventory_source_count = 0
    inventory_invalid = False
    players_dir = save_root / "Players"
    players_availability = _availability(
        "missing",
        "Players",
        explanation="Players/ não foi encontrado no export.",
    )
    if players_dir.is_dir():
        players_availability = _availability(
            "observed",
            "Players",
            explanation="Diretório Players/ observado no export.",
        )
        for player_dir in sorted(path for path in players_dir.iterdir() if path.is_dir()):
            inventory_path = player_dir / "Inventory.json"
            if not inventory_path.is_file():
                continue
            inventory_source_count += 1
            relative = inventory_path.relative_to(save_root).as_posix()
            handled_files.add(inventory_path)
            try:
                inventory_data = _as_object(
                    load_json(inventory_path),
                    inventory_path,
                )
            except SaveDataError:
                inventory_invalid = True
                continue
            if not isinstance(inventory_data.get("Items"), list):
                inventory_invalid = True
                continue
            items = _parse_items(inventory_data["Items"], relative, "Items")
            all_items.extend(items)
            players.append(
                {
                    "player": player_dir.name,
                    "inventory": _summarize_items(items),
                    "origin": _origin(relative, "$"),
                    "unknown": _unknown_fields(inventory_data, {"Items"}, relative),
                }
            )

    world_entity_count: int | None = None
    world_path = save_root / "WorldStorageEntities.json"
    world_availability = _availability(
        "missing",
        "WorldStorageEntities.json",
        explanation="WorldStorageEntities.json não foi encontrado no export.",
    )
    if world_path.is_file():
        inventory_source_count += 1
        relative = "WorldStorageEntities.json"
        handled_files.add(world_path)
        try:
            world = _as_object(
                decode_embedded_json(load_json(world_path)),
                world_path,
            )
        except SaveDataError as exc:
            inventory_invalid = True
            world_availability = _availability(
                "invalid",
                relative,
                explanation=(
                    "WorldStorageEntities.json não pôde ser normalizado: "
                    f"{exc}"
                ),
            )
        else:
            entities = world.get("Entities")
            if not isinstance(entities, list):
                inventory_invalid = True
                world_availability = _availability(
                    "invalid",
                    relative,
                    explanation=(
                        "WorldStorageEntities.json não contém a coleção Entities."
                    ),
                )
            else:
                world_entity_count = len(entities)
                world_availability = _availability(
                    "observed",
                    relative,
                    explanation="Coleção de armazenamento mundial observada.",
                )
                for index, entity in enumerate(entities):
                    contents = (
                        entity.get("Contents")
                        if isinstance(entity, dict)
                        else None
                    )
                    if isinstance(contents, dict):
                        items = contents.get("Items")
                        if isinstance(items, list):
                            all_items.extend(
                                _parse_items(
                                    items,
                                    relative,
                                    f"Entities[{index}].Contents.Items",
                                )
                            )

    properties, properties_availability, property_paths = _parse_property_section(
        save_root,
        "Properties",
    )
    businesses, businesses_availability, business_paths = _parse_property_section(
        save_root,
        "Businesses",
    )
    handled_files.update(property_paths)
    handled_files.update(business_paths)

    npcs, npcs_availability = _parse_npcs(save_root)
    npc_path = save_root / "NPCs.json"
    if npc_path.is_file():
        handled_files.add(npc_path)
    vehicles, vehicle_root_unknown, vehicles_availability = _parse_vehicles(
        save_root
    )
    vehicle_path = save_root / "Vehicles.json"
    if vehicle_path.is_file():
        handled_files.add(vehicle_path)

    prices = {
        str(row["String"]): _optional_money(row.get("Int"))
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
            reference_price=prices[product_id],
            origin=_origin("Products.json", "$"),
            raw=None,
        )
        for product_id in product_ids
    )

    if inventory_invalid:
        inventory_availability = _availability(
            "invalid",
            "Players/*/Inventory.json",
            "WorldStorageEntities.json",
            explanation=(
                "Ao menos uma fonte de inventário estava ausente de sua coleção "
                "esperada ou não pôde ser normalizada."
            ),
        )
    elif inventory_source_count:
        inventory_availability = _availability(
            "observed",
            "Players/*/Inventory.json",
            "WorldStorageEntities.json",
            explanation="Ao menos uma fonte de inventário foi observada.",
        )
    else:
        inventory_availability = _availability(
            "missing",
            "Players/*/Inventory.json",
            "WorldStorageEntities.json",
            explanation="Nenhuma fonte de inventário foi encontrada no export.",
        )

    inventory = _summarize_items(all_items)
    market_value = (
        sum(
            (
                quantity * (prices.get(item_id) or Decimal("0"))
                for item_id, quantity in inventory.quantities.items()
            ),
            start=Decimal("0"),
        )
        if inventory_availability.state == "observed"
        else None
    )
    employees = tuple(
        employee
        for prop in (*properties, *businesses)
        for employee in prop.employees
    )
    property_states = {
        properties_availability.state,
        businesses_availability.state,
    }
    if "invalid" in property_states:
        employees_availability = _availability(
            "invalid",
            "Properties",
            "Businesses",
            explanation=(
                "Funcionários não são conclusivos porque uma fonte de "
                "propriedades ou negócios é inválida."
            ),
        )
    elif property_states == {"observed"}:
        employees_availability = _availability(
            "observed",
            "Properties",
            "Businesses",
            explanation="Coleções que contêm funcionários foram observadas.",
        )
    else:
        employees_availability = _availability(
            "missing",
            "Properties",
            "Businesses",
            explanation=(
                "Funcionários não são conclusivos porque uma fonte opcional "
                "não foi observada."
            ),
        )

    archive = source_archive.expanduser().resolve() if source_archive else None
    if archive is not None and archive_fingerprint is None:
        archive_fingerprint = fingerprint_archive(archive)
    version = money.get("GameVersion") or time_data.get("GameVersion")
    metadata = Metadata(
        product_name="O Alquimista",
        schema_version="1.0",
        imported_at=None,
        source_archive=archive.name if archive else None,
        archive_sha256=(
            archive_fingerprint.digest if archive_fingerprint is not None else None
        ),
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

    online_balance = _optional_money(money.get("OnlineBalance"))
    loose_cash = (
        inventory.cash
        if inventory_availability.state == "observed"
        else None
    )
    return NormalizedSnapshot(
        metadata=metadata,
        finance=Finance(
            online_balance=online_balance,
            loose_cash=loose_cash,
            liquid_cash_estimate=(
                online_balance + loose_cash
                if online_balance is not None and loose_cash is not None
                else None
            ),
            networth=_optional_money(money.get("Networth")),
            lifetime_earnings=_optional_money(money.get("LifetimeEarnings")),
            weekly_deposit_sum=_optional_money(money.get("WeeklyDepositSum")),
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
            elapsed_days=_metric_number(time_data.get("ElapsedDays")),
            time_of_day=(
                _metric_number(time_data.get("TimeOfDay"))
                if not isinstance(time_data.get("TimeOfDay"), str)
                else time_data.get("TimeOfDay")
            ),
            playtime_seconds=_metric_number(time_data.get("Playtime")),
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
            xp=_metric_number(rank.get("XP")),
            total_xp=_metric_number(rank.get("TotalXP")),
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
        availability={
            "finance": _availability(
                "observed",
                "Money.json",
                explanation="Money.json essencial foi observado.",
            ),
            "time": _availability(
                "observed",
                "Time.json",
                explanation="Time.json essencial foi observado.",
            ),
            "progression": _availability(
                "observed",
                "Rank.json",
                explanation="Rank.json essencial foi observado.",
            ),
            "products": _availability(
                "observed",
                "Products.json",
                explanation="Products.json essencial foi observado.",
            ),
            "players": players_availability,
            "inventory": inventory_availability,
            "world_storage": world_availability,
            "properties": properties_availability,
            "businesses": businesses_availability,
            "npcs": npcs_availability,
            "employees": employees_availability,
            "vehicles": vehicles_availability,
        },
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
    snapshot, _ = snapshot_and_fingerprint_from_zip(archive_path)
    return snapshot


def snapshot_and_fingerprint_from_zip(
    archive_path: Path,
) -> tuple[NormalizedSnapshot, ArchiveFingerprint]:
    """Lê o ZIP uma vez para identidade e uma vez para extração segura."""
    archive = archive_path.expanduser().resolve()
    fingerprint = fingerprint_archive(archive)
    try:
        with extracted_save(archive) as (save_root, archive_root):
            snapshot = read_save_model(
                save_root,
                source_archive=archive,
                archive_root=archive_root,
                archive_fingerprint=fingerprint,
            )
    finally:
        verified_fingerprint = fingerprint_archive(archive)
        if verified_fingerprint != fingerprint:
            raise InvalidArchiveError(
                "O ZIP foi alterado por outro processo durante a leitura."
            )
    return snapshot, fingerprint
