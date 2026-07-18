"""Identidade criptográfica de arquivos e resolução conservadora de campanhas."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .archive import validate_archive
from .memory_models import (
    ArchiveFingerprint,
    CampaignAssociationSignal,
    CampaignIdentity,
    ConfidenceLevel,
    Evidence,
)
from .models import NormalizedSnapshot, UnknownField

HASH_CHUNK_BYTES = 1024 * 1024
NATIVE_CAMPAIGN_FIELDS: dict[str, ConfidenceLevel] = {
    "campaignid": "high",
    "campaign_id": "high",
    "gameid": "medium",
    "game_id": "medium",
    "saveid": "medium",
    "save_id": "medium",
}


def _stable_digest(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _evidence_id(prefix: str, payload: Any) -> str:
    return f"{prefix}-{_stable_digest(payload)[:24]}"


def fingerprint_archive(archive_path: Path) -> ArchiveFingerprint:
    """Calcula SHA-256 em blocos sem extrair ou modificar o ZIP."""
    path = validate_archive(archive_path)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    with zipfile.ZipFile(path, mode="r") as archive:
        member_count = len(archive.infolist())
    return ArchiveFingerprint(
        algorithm="sha256",
        digest=digest.hexdigest().lower(),
        file_size=path.stat().st_size,
        archive_member_count=member_count,
    )


def _iter_unknown_fields(snapshot: NormalizedSnapshot) -> Iterable[UnknownField]:
    yield from snapshot.metadata.unknown
    yield from snapshot.finance.unknown
    yield from snapshot.time.unknown
    yield from snapshot.progression.unknown
    yield from snapshot.products.unknown
    yield from snapshot.npcs.unknown
    for prop in (*snapshot.properties, *snapshot.businesses):
        yield from prop.unknown
        for employee in prop.employees:
            yield from employee.unknown
    for npc in snapshot.npcs.entries:
        yield from npc.unknown
    for vehicle in snapshot.vehicles:
        yield from vehicle.unknown
    yield from snapshot.unknown


def _association_signals(
    snapshot: NormalizedSnapshot,
) -> tuple[CampaignAssociationSignal, ...]:
    signals: list[CampaignAssociationSignal] = []
    organisation = snapshot.metadata.organisation_name
    if organisation:
        signals.append(
            CampaignAssociationSignal(
                kind="organisation",
                digest=_stable_digest(organisation),
                source_file="Game.json",
                source_path="OrganisationName",
            )
        )
    for player_id in sorted(
        str(player.get("player"))
        for player in snapshot.players
        if player.get("player")
    ):
        signals.append(
            CampaignAssociationSignal(
                kind="player",
                digest=_stable_digest(player_id),
                source_file="Players/*",
                source_path="$directory",
            )
        )
    return tuple(
        sorted(signals, key=lambda signal: (signal.kind, signal.digest))
    )


def _provisional_campaign_id() -> str:
    """Cria identidade local sem depender de ZIP, caminho, nome ou horário."""
    return f"campaign-{uuid4().hex}"


def _native_identity(
    snapshot: NormalizedSnapshot,
    association_signals: tuple[CampaignAssociationSignal, ...],
) -> CampaignIdentity | None:
    candidates = sorted(
        (
            field
            for field in _iter_unknown_fields(snapshot)
            if field.origin.file.casefold() == "game.json"
            and field.name.casefold() in NATIVE_CAMPAIGN_FIELDS
            and isinstance(field.raw, (str, int))
            and str(field.raw).strip()
        ),
        key=lambda field: (
            field.origin.file.casefold(),
            field.origin.field.casefold(),
        ),
    )
    if not candidates:
        return None
    selected = candidates[0]
    confidence = NATIVE_CAMPAIGN_FIELDS[selected.name.casefold()]
    protected_digest = _stable_digest(
        {
            "field": selected.name.casefold(),
            "value": str(selected.raw),
        }
    )
    evidence = Evidence(
        evidence_id=_evidence_id("evidence", protected_digest),
        category="observed",
        source_file=selected.origin.file,
        source_path=selected.origin.field,
        field_name=selected.name,
        raw_value=None,
        normalized_value=f"sha256:{protected_digest}",
        calculation="SHA-256 do identificador nativo; valor bruto não persistido.",
        explanation="Identificador nativo de campanha observado no save.",
        confidence=confidence,
        related_entity="campaign",
    )
    if confidence == "high":
        return CampaignIdentity(
            campaign_id=f"campaign-{protected_digest[:32]}",
            resolution_state="resolved",
            strategy="native_campaign_identifier",
            confidence="high",
            evidence=(evidence,),
            association_signals=association_signals,
            explanation=(
                "Identidade resolvida por CampaignId observado em Game.json; "
                "o valor original foi protegido por hash."
            ),
        )
    native_signal = CampaignAssociationSignal(
        kind=selected.name.casefold(),
        digest=protected_digest,
        source_file=selected.origin.file,
        source_path=selected.origin.field,
    )
    return CampaignIdentity(
        campaign_id=_provisional_campaign_id(),
        resolution_state="candidate",
        strategy="ambiguous_native_identifier",
        confidence="low",
        evidence=(evidence,),
        association_signals=tuple(
            sorted(
                (*association_signals, native_signal),
                key=lambda signal: (signal.kind, signal.digest),
            )
        ),
        explanation=(
            "GameId/SaveId é apenas candidato de associação; sua estabilidade "
            "como identidade de campanha não está comprovada."
        ),
    )


def resolve_campaign_identity(
    snapshot: NormalizedSnapshot,
    archive_fingerprint: ArchiveFingerprint,
) -> CampaignIdentity:
    """Resolve identidade sem usar nome, caminho, dinheiro, dia ou inventário."""
    del archive_fingerprint
    association_signals = _association_signals(snapshot)
    native = _native_identity(snapshot, association_signals)
    if native is not None:
        return native

    if association_signals:
        protected_signals = [
            {"kind": signal.kind, "digest": signal.digest}
            for signal in association_signals
        ]
        evidence = Evidence(
            evidence_id=_evidence_id("evidence", protected_signals),
            category="derived",
            source_file=";".join(
                sorted({signal.source_file for signal in association_signals})
            ),
            source_path=None,
            field_name=None,
            raw_value=None,
            normalized_value=protected_signals,
            calculation="SHA-256 individual de sinais fracos e ordenados.",
            explanation=(
                "Sinais fracos foram preservados apenas para sugerir associações; "
                "eles não consolidam campanhas automaticamente."
            ),
            confidence="low",
            related_entity="campaign",
        )
        return CampaignIdentity(
            campaign_id=_provisional_campaign_id(),
            resolution_state="candidate",
            strategy="weak_signal_candidate",
            confidence="low",
            evidence=(evidence,),
            association_signals=association_signals,
            explanation=(
                "Campanha provisória independente. Organização e players podem "
                "gerar associações candidatas, nunca união automática."
            ),
        )

    unavailable = Evidence(
        evidence_id=_evidence_id("evidence", "campaign-identity-unavailable"),
        category="unavailable",
        source_file=None,
        source_path=None,
        field_name=None,
        raw_value=None,
        normalized_value=None,
        calculation=None,
        explanation=(
            "Nenhum identificador nativo ou interno estável foi observado; "
            "o fallback não conecta exports diferentes."
        ),
        confidence="unavailable",
        related_entity="campaign",
    )
    return CampaignIdentity(
        campaign_id=_provisional_campaign_id(),
        resolution_state="unresolved",
        strategy="unresolved_without_stable_identity",
        confidence="unavailable",
        evidence=(unavailable,),
        association_signals=(),
        explanation=(
            "Campanha provisória sem identidade observável. Nenhum fingerprint, "
            "nome, caminho ou horário foi usado no campaign_id."
        ),
    )
