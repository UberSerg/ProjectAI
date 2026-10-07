"""IntradayStructureModelV1 — Agent A aggregate features → SignalOutputV1.

ABSTAIN when coverage is missing. Factual structure only (no anthropomorphism).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from app.modules.intelligence.contracts.provenance import EvidenceRef
from app.modules.intelligence.contracts.signal import SignalOutputV1, abstain_signal, unknown_signal
from app.modules.intelligence.signals.base import (
    clip,
    optional_float,
    parse_as_of,
    parse_known_at,
    pit_allows,
    score_to_state,
    weighted_mean,
)

MODEL_ID = "IntradayStructureModelV1"
MODEL_VERSION = "1"
SEMANTIC = "INTRADAY_STRUCTURE"
HORIZON = "1d"

_COVERED = frozenset({"READY", "PARTIAL", "OK", "COVERED"})
_NO_COVERAGE = frozenset(
    {"UNKNOWN", "NOT_AVAILABLE", "NOT_READY", "MISSING", "NO_COVERAGE", "UNAVAILABLE", ""}
)


def _features_map(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    raw = snapshot.get("features")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _volume_confirmation(features: Mapping[str, Any]) -> float | None:
    for key in (
        "price_volume_confirmation",
        "volume_confirmation",
        "accumulation_volume_z",
        "intraday_volume_zscore",
        "volume_zscore",
    ):
        val = optional_float(features.get(key))
        if val is not None:
            return clip(val / 2.0)
    return None


def _weak_close(features: Mapping[str, Any]) -> float | None:
    """close_location in [0,1] (low=weak close → adverse); or weak_close flag/score."""
    loc = optional_float(
        features.get("close_location_in_range")
        or features.get("close_location")
        or features.get("close_in_range")
    )
    if loc is not None:
        # High close supportive, weak close adverse.
        return clip(2.0 * loc - 1.0)
    weak = features.get("weak_close")
    if isinstance(weak, bool):
        return -0.4 if weak else 0.2
    return optional_float(weak)


def _gap_structure(features: Mapping[str, Any]) -> float | None:
    gap = optional_float(
        features.get("overnight_gap") or features.get("gap_return") or features.get("gap")
    )
    cont = optional_float(features.get("gap_continuation") or features.get("gap_follow_through"))
    if cont is not None:
        return clip(cont)
    if gap is None:
        return None
    # Mild continuation bias from gap sign; reversal signal preferred when present.
    rev = optional_float(features.get("gap_reversal") or features.get("intraday_reversal"))
    if rev is not None and optional_float(features.get("gap_reversal")) is not None:
        return clip(-rev if gap > 0 else rev)
    return clip(gap / 0.02)


def _trend_quality(features: Mapping[str, Any]) -> float | None:
    for key in (
        "trend_efficiency",
        "intraday_momentum",
        "intraday_trend_quality",
        "trend_quality",
        "session_trend",
    ):
        val = optional_float(features.get(key))
        if val is not None:
            return clip(val)
    return None


def _abnormal_vol(features: Mapping[str, Any]) -> float | None:
    for key in (
        "realized_intraday_volatility",
        "abnormal_volatility",
        "realized_vol_z",
        "intraday_vol_z",
    ):
        val = optional_float(features.get(key))
        if val is not None:
            # High abnormal vol → adverse tilt (scale: ~1% session realized vol).
            if key == "realized_intraday_volatility":
                return clip(1.0 - (val / 0.01))
            return clip(-abs(val) / 2.0)
    return None


class IntradayStructureModelV1:
    model_id = MODEL_ID
    model_version = MODEL_VERSION
    semantic = SEMANTIC

    def evaluate(
        self,
        *,
        instrument_id: int,
        as_of: date | datetime | str,
        snapshot: Mapping[str, Any] | None,
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
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="no_intraday_coverage",
                horizon=HORIZON,
            )

        coverage = str(snapshot.get("coverage_status") or "UNKNOWN").upper()
        if coverage in _NO_COVERAGE or coverage not in _COVERED:
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="no_intraday_coverage",
                horizon=HORIZON,
                limitations=(f"coverage_status={coverage}",),
            )

        known_at = parse_known_at(snapshot.get("known_at"))
        if known_at is not None and not pit_allows(as_of_d, known_at):
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="intraday_known_at_after_as_of",
                horizon=HORIZON,
            )

        bars_used = int(snapshot.get("bars_used") or 0)
        features = _features_map(snapshot)
        if not features or bars_used <= 0:
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="no_intraday_coverage",
                horizon=HORIZON,
                limitations=("empty_features_or_bars",),
            )

        dims: dict[str, float | None] = {
            "volume_confirmation": _volume_confirmation(features),
            "weak_close": _weak_close(features),
            "gap_structure": _gap_structure(features),
            "trend_quality": _trend_quality(features),
            "abnormal_volatility": _abnormal_vol(features),
        }
        weights = {
            "volume_confirmation": 0.25,
            "weak_close": 0.20,
            "gap_structure": 0.20,
            "trend_quality": 0.25,
            "abnormal_volatility": 0.10,
        }
        available = {k: v for k, v in dims.items() if v is not None}
        if not available:
            return unknown_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="intraday_features_unscored",
                horizon=HORIZON,
            )

        score = weighted_mean([(weights[k], available[k]) for k in available])
        assert score is not None
        score = clip(score)
        coverage_ratio = len(available) / len(weights)
        confidence = clip(coverage_ratio * (0.5 + 0.5 * abs(score)), 0.0, 1.0)
        if coverage == "PARTIAL":
            confidence *= 0.8

        limitations = list(snapshot.get("limitations") or ())
        for name in weights:
            if name not in available:
                limitations.append(f"missing_{name}")

        return SignalOutputV1(
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            semantic=SEMANTIC,
            instrument_id=int(snapshot.get("instrument_id") or instrument_id),
            as_of=as_of_d,
            known_at=known_at,
            horizon=HORIZON,
            state=score_to_state(score),
            score=score,
            confidence=confidence,
            confidence_semantic="EVIDENCE_COMPLETENESS",
            evidence_refs=(
                EvidenceRef(
                    source_type="intraday_feature_snapshot",
                    provider="intelligence_intraday",
                    known_at=known_at,
                    note=str(snapshot.get("interval") or "60m"),
                ),
            ),
            data_freshness=coverage,
            limitations=tuple(dict.fromkeys(limitations)),
            model_metadata={
                "dimensions": dims,
                "bars_used": bars_used,
                "interval": snapshot.get("interval"),
                "coverage_status": coverage,
                "candidate_promotion": False,
            },
        )
