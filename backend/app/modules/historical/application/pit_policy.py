"""Point-in-time replay policy for one parsed observation.

The policy changes only whether that observation is accepted. It does not
relabel ``artifact.historical_pit_quality`` and it does not invent a
publication timestamp. Callers store ``artifact.historical_pit_quality``
unchanged.
"""

from __future__ import annotations

from dataclasses import replace

from app.modules.historical.domain.evidence import (
    HistoricalArtifact,
    ParsedObservation,
    PitQuality,
    RecordQuality,
)

PIT_PROXY_EXCLUDED_FROM_VERIFIED_REPLAY = "pit_proxy_excluded_from_verified_replay"
RESEARCH_ONLY_EXCLUDED_FROM_STRICT_REPLAY = "research_only_excluded_from_strict_replay"

_MODES = frozenset({"verified", "research"})


def apply_pit_policy(
    observation: ParsedObservation,
    artifact: HistoricalArtifact,
    *,
    mode: str,
) -> ParsedObservation:
    """Return the observation after the replay mode's PIT gate.

    ``verified`` quarantines every artifact that is not ``PIT_VERIFIED``.
    A proxy row gets ``pit_proxy_excluded_from_verified_replay``. Any other
    non-verified label gets ``research_only_excluded_from_strict_replay``.
    ``research`` leaves ``PIT_PROXY`` acceptance unchanged and quarantines
    ``RESEARCH_ONLY`` with that same research limitation.

    Callers persist ``artifact.historical_pit_quality`` as it already stands.
    This function does not copy ``period_end`` into ``published_at`` or
    otherwise invent a publication timestamp, and it does not relabel
    ``PIT_PROXY`` or ``RESEARCH_ONLY`` as ``PIT_VERIFIED``.
    """
    if mode not in _MODES:
        raise ValueError(f"unknown pit policy mode: {mode}")
    limitation = _exclusion(artifact.historical_pit_quality, mode)
    if limitation is None:
        return observation
    limitations = observation.limitations
    if limitation not in limitations:
        limitations = (*limitations, limitation)
    return replace(
        observation,
        quality_status=RecordQuality.QUARANTINE,
        limitations=limitations,
    )


def _exclusion(quality: PitQuality, mode: str) -> str | None:
    if mode == "verified":
        if quality is PitQuality.PIT_VERIFIED:
            return None
        if quality is PitQuality.PIT_PROXY:
            return PIT_PROXY_EXCLUDED_FROM_VERIFIED_REPLAY
        return RESEARCH_ONLY_EXCLUDED_FROM_STRICT_REPLAY
    if quality is PitQuality.RESEARCH_ONLY:
        return RESEARCH_ONLY_EXCLUDED_FROM_STRICT_REPLAY
    return None
