"""Identidade criptográfica de arquivos e resolução conservadora de campanhas."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Iterable

from .archive import validate_archive
from .memory_models import (
    ArchiveFingerprint,
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


def _native_identity(snapshot: NormalizedSnapshot) -> CampaignIdentity | None:
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
    return CampaignIdentity(
        campaign_id=f"campaign-{protected_digest[:32]}",
        strategy="native_campaign_identifier",
        confidence=confidence,
        evidence=(evidence,),
        explanation=(
            "Identidade derivada de um candidato a identificador nativo em "
            "Game.json; o valor original foi protegido por hash."
        ),
    )


def resolve_campaign_identity(
    snapshot: NormalizedSnapshot,
    archive_fingerprint: ArchiveFingerprint,
) -> CampaignIdentity:
    """Resolve identidade sem usar nome, caminho, dinheiro, dia ou inventário."""
    native = _native_identity(snapshot)
    if native is not None:
        return native

    organisation = snapshot.metadata.organisation_name
    player_ids = sorted(
        str(player.get("player"))
        for player in snapshot.players
        if player.get("player")
    )
    protected_signals: dict[str, Any] = {}
    sources: list[str] = []
    if organisation:
        protected_signals["organisation"] = _stable_digest(organisation)
        sources.append("Game.json:OrganisationName")
    if player_ids:
        protected_signals["players"] = [_stable_digest(value) for value in player_ids]
        sources.append("Players/*")

    if protected_signals:
        digest = _stable_digest(protected_signals)
        confidence = "medium" if organisation and player_ids else "low"
        strategy = (
            "stable_internal_identifiers"
            if confidence == "medium"
            else "partial_internal_identifier"
        )
        evidence = Evidence(
            evidence_id=_evidence_id("evidence", protected_signals),
            category="derived",
            source_file=";".join(sources),
            source_path=None,
            field_name=None,
            raw_value=None,
            normalized_value=protected_signals,
            calculation="SHA-256 de sinais internos estáveis e ordenados.",
            explanation=(
                "Não há ID nativo comprovado; a identidade combina sinais internos "
                "protegidos por hash."
            ),
            confidence=confidence,
            related_entity="campaign",
        )
        return CampaignIdentity(
            campaign_id=f"campaign-{digest[:32]}",
            strategy=strategy,
            confidence=confidence,
            evidence=(evidence,),
            explanation=(
                "Combinação determinística de identificadores internos. Pode agrupar "
                "campanhas distintas do mesmo jogador/organização."
            ),
        )

    fallback_digest = _stable_digest(
        {
            "archive": archive_fingerprint.digest,
            "game_version": snapshot.metadata.game_version,
        }
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
        campaign_id=f"campaign-{fallback_digest[:32]}",
        strategy="archive_scoped_fallback",
        confidence="low",
        evidence=(unavailable,),
        explanation=(
            "Fallback limitado ao conteúdo deste arquivo. Snapshots futuros podem "
            "não ser associados automaticamente."
        ),
    )
