"""Modelos de domínio tipados do snapshot normalizado."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Literal, TypeAlias, Union

JsonValue: TypeAlias = Union[
    None,
    bool,
    int,
    float,
    Decimal,
    str,
    list["JsonValue"],
    dict[str, "JsonValue"],
]
SectionAvailabilityState = Literal[
    "observed",
    "missing",
    "invalid",
    "unsupported",
]


@dataclass(frozen=True, slots=True)
class DataOrigin:
    """Origem observável de um dado no save."""

    file: str
    field: str


@dataclass(frozen=True, slots=True)
class UnknownField:
    """Campo preservado sem atribuição de significado."""

    name: str
    raw: JsonValue
    origin: DataOrigin


@dataclass(frozen=True, slots=True)
class SectionAvailability:
    state: SectionAvailabilityState
    source_files: tuple[str, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class Metadata:
    product_name: str
    schema_version: str
    imported_at: str | None
    source_archive: str | None
    archive_sha256: str | None
    save_root: str
    game_version: str | None
    organisation_name: str | None
    origins: dict[str, DataOrigin] = field(default_factory=dict)
    unknown: tuple[UnknownField, ...] = ()


@dataclass(frozen=True, slots=True)
class Finance:
    online_balance: Decimal | None
    loose_cash: Decimal | None
    liquid_cash_estimate: Decimal | None
    networth: Decimal | None
    lifetime_earnings: Decimal | None
    weekly_deposit_sum: Decimal | None
    inventory_list_price_estimate: Decimal | None
    origins: dict[str, DataOrigin] = field(default_factory=dict)
    unknown: tuple[UnknownField, ...] = ()


@dataclass(frozen=True, slots=True)
class GameTime:
    elapsed_days: int | float | None
    time_of_day: int | float | str | None
    playtime_seconds: int | float | None
    origins: dict[str, DataOrigin] = field(default_factory=dict)
    unknown: tuple[UnknownField, ...] = ()


@dataclass(frozen=True, slots=True)
class Progression:
    rank: int | str | None
    tier: int | str | None
    xp: int | float | None
    total_xp: int | float | None
    unlocked_regions: tuple[JsonValue, ...]
    origins: dict[str, DataOrigin] = field(default_factory=dict)
    unknown: tuple[UnknownField, ...] = ()


@dataclass(frozen=True, slots=True)
class Product:
    product_id: str
    discovered: bool
    listed: bool
    reference_price: Decimal | None
    origin: DataOrigin
    raw: JsonValue = None


@dataclass(frozen=True, slots=True)
class ProductCatalog:
    discovered: tuple[str, ...]
    listed: tuple[str, ...]
    prices: dict[str, Decimal | None]
    mix_recipes: tuple[JsonValue, ...]
    active_mix: JsonValue
    entries: tuple[Product, ...]
    raw: JsonValue = None
    origins: dict[str, DataOrigin] = field(default_factory=dict)
    unknown: tuple[UnknownField, ...] = ()


@dataclass(frozen=True, slots=True)
class InventoryItem:
    item_id: str
    quantity: Decimal
    cash_balance: Decimal
    quality: str | None
    packaging_id: str | None
    origin: DataOrigin
    raw: JsonValue


@dataclass(frozen=True, slots=True)
class Inventory:
    quantities: dict[str, Decimal]
    cash: Decimal
    variants: dict[str, dict[str, Decimal]]
    items: tuple[InventoryItem, ...]
    origins: tuple[DataOrigin, ...] = ()
    unknown: tuple[UnknownField, ...] = ()


@dataclass(frozen=True, slots=True)
class Employee:
    employee_id: str | None
    property_name: str | None
    origin: DataOrigin
    raw: JsonValue
    unknown: tuple[UnknownField, ...] = ()


@dataclass(frozen=True, slots=True)
class Property:
    name: str
    code: str | None
    owned: bool
    employee_count: int
    object_count: int
    object_types: dict[str, int]
    inventory: Inventory
    origin: DataOrigin
    raw: JsonValue = None
    origins: dict[str, DataOrigin] = field(default_factory=dict)
    employees: tuple[Employee, ...] = ()
    unknown: tuple[UnknownField, ...] = ()


@dataclass(frozen=True, slots=True)
class Npc:
    npc_id: str | None
    relationship_unlocked: bool | None
    origin: DataOrigin
    raw: JsonValue
    unknown: tuple[UnknownField, ...] = ()


@dataclass(frozen=True, slots=True)
class NpcCollection:
    total: int
    unlocked_relationships: int
    entries: tuple[Npc, ...]
    origins: dict[str, DataOrigin] = field(default_factory=dict)
    unknown: tuple[UnknownField, ...] = ()


@dataclass(frozen=True, slots=True)
class Vehicle:
    vehicle_id: str | None
    origin: DataOrigin
    raw: JsonValue
    unknown: tuple[UnknownField, ...] = ()


MilestoneStatus = Literal["pending", "in_progress", "completed", "blocked"]
Priority = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class Milestone:
    id: str
    titulo: str
    descricao: str
    categoria: str
    prioridade: Priority | str
    progresso: float
    requisitos: tuple[str, ...]
    impacto_esperado: str
    status: MilestoneStatus | str
    evidencias: tuple[JsonValue, ...]


@dataclass(frozen=True, slots=True)
class Recommendation:
    id: str
    problema: str
    diagnostico: str
    acao_recomendada: str
    custo_estimado: float | str | None
    impacto_estimado: float | str | None
    confianca: float
    evidencias: tuple[JsonValue, ...]


@dataclass(frozen=True, slots=True)
class NormalizedSnapshot:
    metadata: Metadata
    finance: Finance
    time: GameTime
    progression: Progression
    products: ProductCatalog
    inventory: Inventory
    players: tuple[dict[str, JsonValue], ...]
    world_storage_entity_count: int | None
    properties: tuple[Property, ...]
    businesses: tuple[Property, ...]
    npcs: NpcCollection
    employees: tuple[Employee, ...]
    vehicles: tuple[Vehicle, ...]
    availability: dict[str, SectionAvailability]
    unknown: tuple[UnknownField, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serializa para JSON mantendo chaves legadas úteis a diff/report."""
        data = asdict(self)
        data["game"] = {
            "version": self.metadata.game_version,
            "organisation_name": self.metadata.organisation_name,
            "elapsed_days": self.time.elapsed_days,
            "time_of_day": self.time.time_of_day,
            "playtime_seconds": self.time.playtime_seconds,
            "origins": {
                **asdict(self.metadata)["origins"],
                **asdict(self.time)["origins"],
            },
        }
        return data
