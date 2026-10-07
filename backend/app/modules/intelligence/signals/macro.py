"""MacroModelV1 — regime supportive/neutral/adverse/unknown → SignalOutputV1."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from app.modules.intelligence.contracts.provenance import EvidenceRef
from app.modules.intelligence.contracts.signal import (
    SignalOutputV1,
    SignalState,
    abstain_signal,
    unknown_signal,
)
from app.modules.intelligence.signals.base import clip, parse_as_of, parse_known_at, pit_allows

MODEL_ID = "MacroModelV1"
MODEL_VERSION = "1"
SEMANTIC = "MACRO"
HORIZON = "regime"

_REGIME_MAP: dict[str, tuple[SignalState, float | None]] = {
    "SUPPORTIVE": ("POSITIVE", 0.45),
    "NEUTRAL": ("NEUTRAL", 0.0),
    "ADVERSE": ("NEGATIVE", -0.45),
    "UNKNOWN": ("UNKNOWN", None),
}


def _normalize_regime(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    aliases = {
        "SUPPORTIVE": "SUPPORTIVE",
        "FAVORABLE": "SUPPORTIVE",
        "POSITIVE": "SUPPORTIVE",
        "NEUTRAL": "NEUTRAL",
        "ADVERSE": "ADVERSE",
        "NEGATIVE": "ADVERSE",
        "UNFAVORABLE": "ADVERSE",
        "UNKNOWN": "UNKNOWN",
    }
    return aliases.get(text)


def _pick_regime(
    snapshot: Mapping[str, Any],
    *,
    sector: str | None,
    sector_sensitivity_known: bool,
) -> tuple[str, str, str]:
    """Return (regime_key_used, regime_label, context_scope)."""
    regimes = snapshot.get("regimes")
    regimes_map = dict(regimes) if isinstance(regimes, Mapping) else {}

    if sector_sensitivity_known and sector:
        for key in (f"sector:{sector}", sector, f"sector_{sector}"):
            if key in regimes_map:
                label = _normalize_regime(regimes_map[key])
                if label:
                    return key, label, "sector"
        # Explicit unknown sector sensitivity path handled by caller when not known.
        if "sector" in regimes_map:
            label = _normalize_regime(regimes_map["sector"])
            if label:
                return "sector", label, "sector"

    for key in ("market", "market_wide", "equity", "moex", "default"):
        if key in regimes_map:
            label = _normalize_regime(regimes_map[key])
            if label:
                return key, label, "market_wide"

    # Single regime value or first usable entry.
    if len(regimes_map) == 1:
        key, raw = next(iter(regimes_map.items()))
        label = _normalize_regime(raw)
        if label:
            return str(key), label, "market_wide"

    for key, raw in regimes_map.items():
        label = _normalize_regime(raw)
        if label:
            return str(key), label, "market_wide"

    obs = snapshot.get("observations")
    if isinstance(obs, Mapping) and "regime" in obs:
        label = _normalize_regime(obs.get("regime"))
        if label:
            return "observations.regime", label, "market_wide"

    return "", "UNKNOWN", "unknown"


class MacroModelV1:
    model_id = MODEL_ID
    model_version = MODEL_VERSION
    semantic = SEMANTIC

    def evaluate(
        self,
        *,
        instrument_id: int,
        as_of: date | datetime | str,
        snapshot: Mapping[str, Any] | None,
        sector: str | None = None,
        sector_sensitivity_known: bool = False,
    ) -> SignalOutputV1:
        as_of_d = parse_as_of(as_of)
        if as_of_d is None:
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=date.today(),
                reason="missing_as_of",
                horizon=HORIZON,
            )

        if snapshot is None:
            return unknown_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="missing_macro_snapshot",
                horizon=HORIZON,
            )

        status = str(snapshot.get("status") or "UNKNOWN").upper()
        if status in {"NOT_AVAILABLE", "UNKNOWN"}:
            return unknown_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason=f"macro_status_{status.lower()}",
                horizon=HORIZON,
            )

        known_at = parse_known_at(snapshot.get("known_at"))
        if known_at is not None and not pit_allows(as_of_d, known_at):
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="macro_known_at_after_as_of",
                horizon=HORIZON,
            )

        regime_key, regime_label, scope = _pick_regime(
            snapshot,
            sector=sector,
            sector_sensitivity_known=sector_sensitivity_known,
        )
        if not regime_key and regime_label == "UNKNOWN":
            return unknown_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="macro_regime_unknown",
                horizon=HORIZON,
            )

        state, score = _REGIME_MAP[regime_label]
        if state == "UNKNOWN":
            return unknown_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="macro_regime_unknown",
                horizon=HORIZON,
            )

        limitations = list(snapshot.get("limitations") or ())
        if scope == "market_wide":
            limitations.append("market_wide_context_only")
        if not sector_sensitivity_known:
            limitations.append("sector_sensitivity_unknown")

        confidence = 0.55 if scope == "sector" else 0.4
        if status == "PARTIAL":
            confidence *= 0.85
        confidence = clip(confidence, 0.0, 1.0)

        sources = snapshot.get("sources") or ()
        provider = str(sources[0]) if sources else "macro"

        return SignalOutputV1(
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            semantic=SEMANTIC,
            instrument_id=instrument_id,
            as_of=as_of_d,
            known_at=known_at,
            horizon=HORIZON,
            state=state,
            score=score,
            confidence=confidence,
            confidence_semantic="MODEL_DEFINED",
            evidence_refs=(
                EvidenceRef(
                    source_type="macro_snapshot",
                    provider=provider,
                    known_at=known_at,
                    note=f"regime={regime_label}",
                ),
            ),
            data_freshness=status,
            limitations=tuple(dict.fromkeys(limitations)),
            model_metadata={
                "regime": regime_label,
                "regime_key": regime_key,
                "context_scope": scope,
                "sector": sector,
                "sector_sensitivity_known": sector_sensitivity_known,
                "candidate_promotion": False,
            },
        )
