"""Modelos imutáveis da memória analítica do Milestone 2."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

EvidenceCategory = Literal["observed", "derived", "inferred", "unavailable"]
ConfidenceLevel = Literal["high", "medium", "low", "unavailable"]
ChangeStatus = Literal[
    "added",
    "removed",
    "changed",
    "unchanged",
    "unknown",
    "not_comparable",
]
RecommendationPriority = Literal[
    "critical",
    "high",
    "medium",
    "low",
    "informational",
]


@dataclass(frozen=True, slots=True)
class ArchiveFingerprint:
    algorithm: Literal["sha256"]
    digest: str
    file_size: int
    archive_member_count: int

    @property
    def fingerprint_id(self) -> str:
        return f"archive-sha256-{self.digest}"


@dataclass(frozen=True, slots=True)
class Evidence:
    evidence_id: str
    category: EvidenceCategory
    source_file: str | None
    source_path: str | None
    field_name: str | None
    raw_value: Any
    normalized_value: Any
    calculation: str | None
    explanation: str
    confidence: ConfidenceLevel
    related_entity: str | None = None
    unknown_fields: tuple[str, ...] = ()
    supporting_evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CampaignIdentity:
    campaign_id: str
    strategy: str
    confidence: ConfidenceLevel
    evidence: tuple[Evidence, ...]
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    snapshot_id: str
    import_id: str
    campaign_id: str
    archive_hash: str
    observable_game_moment: dict[str, Any]
    chronological_order: int
    financial_summary: dict[str, Any]
    operational_summary: dict[str, Any]
    progression_summary: dict[str, Any]
    milestones: tuple[dict[str, Any], ...]
    primary_evidence: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: str
    status: ChangeStatus
    previous: Any
    current: Any
    absolute_change: str | None = None
    percentage_change: str | None = None
    explanation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SnapshotComparison:
    comparison_id: str
    campaign_id: str | None
    previous_snapshot_id: str
    current_snapshot_id: str
    cross_campaign_override: bool
    financial_changes: tuple[FieldChange, ...]
    operational_changes: dict[str, tuple[FieldChange, ...]]
    evidence: tuple[Evidence, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DetectedMilestone:
    milestone_id: str
    milestone_type: str
    title: str
    description: str
    evidence: tuple[Evidence, ...]
    confidence: ConfidenceLevel
    first_seen_snapshot_id: str
    previous_snapshot_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StrategicRecommendation:
    recommendation_id: str
    category: str
    title: str
    explanation: str
    priority: RecommendationPriority
    confidence: ConfidenceLevel
    supporting_evidence: tuple[Evidence, ...]
    contradictory_evidence: tuple[Evidence, ...]
    missing_information: tuple[str, ...]
    rule_id: str
    confidence_justification: str
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CampaignAnalysis:
    campaign_id: str
    facts: tuple[Evidence, ...]
    derived: tuple[Evidence, ...]
    inferences: tuple[Evidence, ...]
    milestones: tuple[DetectedMilestone, ...]
    recommendations: tuple[StrategicRecommendation, ...]
    limitations: tuple[str, ...]
    unavailable: tuple[Evidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
