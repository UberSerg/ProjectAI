"""TechnicalModelV1 — transparent daily technical SignalOutputV1 adapter.

Consumes existing daily technical / basic feature dicts. Does not read other models.
Missing core evidence => UNKNOWN/ABSTAIN (never fabricated zero score).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from hashlib import sha256
from typing import Any

from app.modules.intelligence.contracts.provenance import EvidenceRef
from app.modules.intelligence.contracts.signal import SignalOutputV1, abstain_signal, unknown_signal
from app.modules.intelligence.signals.base import (
    clip,
    optional_float,
    parse_as_of,
    parse_known_at,
    score_to_state,
    weighted_mean,
)

MODEL_ID = "TechnicalModelV1"
MODEL_VERSION = "1"
SEMANTIC = "TECHNICAL"
HORIZON = "20d"

# Transparent category weights (documented in model_metadata).
_WEIGHTS = {
    "trend": 0.30,
    "momentum": 0.30,
    "volatility": 0.15,
    "drawdown": 0.15,
    "volume": 0.10,
}

_DISTANCE_SCALE = 0.05
_RETURN_SCALE = 0.10
_VOL_SCALE = 0.04  # atr14_pct / volatility_20d typical daily scale
_DRAWDOWN_SCALE = 0.15
_VOLUME_SCALE = 3.0


def _feature_hash(features: Mapping[str, Any]) -> str:
    keys = sorted(features.keys())
    payload = "|".join(f"{k}={features.get(k)!r}" for k in keys)
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def _trend_factor(features: Mapping[str, Any]) -> float | None:
    parts: list[float] = []
    sma = optional_float(features.get("sma20_distance"))
    ema = optional_float(features.get("ema20_distance"))
    if sma is not None:
        parts.append(clip(sma / _DISTANCE_SCALE))
    if ema is not None:
        parts.append(clip(ema / _DISTANCE_SCALE))
    if not parts:
        return None
    return sum(parts) / len(parts)


def _momentum_factor(features: Mapping[str, Any]) -> float | None:
    parts: list[tuple[float, float]] = []
    r5 = optional_float(features.get("return_5d"))
    r20 = optional_float(features.get("return_20d"))
    if r5 is not None:
        parts.append((0.6, clip(r5 / _RETURN_SCALE)))
    if r20 is not None:
        parts.append((0.4, clip(r20 / _RETURN_SCALE)))
    return weighted_mean(parts)


def _volatility_factor(features: Mapping[str, Any]) -> float | None:
    """Elevated realized vol is a mild adverse tilt (not a trade recommendation)."""
    atr = optional_float(features.get("atr14_pct"))
    vol20 = optional_float(features.get("volatility_20d"))
    raw = atr if atr is not None else vol20
    if raw is None:
        return None
    # Above scale → negative; calm → near 0 / slightly positive.
    return clip(1.0 - (raw / _VOL_SCALE))


def _drawdown_factor(features: Mapping[str, Any]) -> float | None:
    dd = optional_float(features.get("drawdown_20d"))
    if dd is None:
        return None
    # drawdown_20d typically <= 0; deeper drawdown → more negative.
    return clip(dd / _DRAWDOWN_SCALE)


def _volume_factor(features: Mapping[str, Any], momentum: float | None) -> float | None:
    z = optional_float(features.get("volume_zscore_20d"))
    if z is None or momentum is None:
        return None
    if z <= 0:
        return 0.0
    sign = 1.0 if momentum > 0 else (-1.0 if momentum < 0 else 0.0)
    return sign * clip(z / _VOLUME_SCALE, 0.0, 1.0)


class TechnicalModelV1:
    """Independent technical perspective for Intelligence Stack V1."""

    model_id = MODEL_ID
    model_version = MODEL_VERSION
    semantic = SEMANTIC

    def evaluate(
        self,
        *,
        instrument_id: int,
        as_of: date | datetime | str,
        features: Mapping[str, Any] | None,
        known_at: date | datetime | str | None = None,
        quality_flags: Mapping[str, Any] | None = None,
        is_valid: bool | None = None,
        data_freshness: str | None = None,
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

        if features is None:
            return unknown_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="missing_technical_features",
                horizon=HORIZON,
            )

        flags = dict(quality_flags or {})
        critical = bool(flags.get("price_discontinuity") or flags.get("critical"))
        if is_valid is False or critical:
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="technical_quality_critical",
                horizon=HORIZON,
                limitations=("critical_quality_flags",),
            )

        momentum = _momentum_factor(features)
        factors: dict[str, float | None] = {
            "trend": _trend_factor(features),
            "momentum": momentum,
            "volatility": _volatility_factor(features),
            "drawdown": _drawdown_factor(features),
            "volume": _volume_factor(features, momentum),
        }
        available = {k: v for k, v in factors.items() if v is not None}
        # Core directional evidence: need at least trend or momentum.
        if "trend" not in available and "momentum" not in available:
            return unknown_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="insufficient_trend_momentum_evidence",
                horizon=HORIZON,
            )

        parts = [(_WEIGHTS[k], available[k]) for k in available]
        score = weighted_mean(parts)
        assert score is not None
        score = clip(score)

        coverage = len(available) / len(_WEIGHTS)
        confidence = clip(coverage * (0.5 + 0.5 * abs(score)), 0.0, 1.0)
        state = score_to_state(score)

        known = parse_known_at(known_at) if known_at is not None else as_of_d
        limitations: list[str] = []
        if "volume" not in available:
            limitations.append("volume_confirmation_unavailable")
        if "volatility" not in available:
            limitations.append("volatility_unavailable")
        if "drawdown" not in available:
            limitations.append("drawdown_unavailable")

        return SignalOutputV1(
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            semantic=SEMANTIC,
            instrument_id=instrument_id,
            as_of=as_of_d,
            known_at=known,
            horizon=HORIZON,
            state=state,
            score=score,
            confidence=confidence,
            confidence_semantic="EVIDENCE_COMPLETENESS",
            evidence_refs=(
                EvidenceRef(
                    source_type="technical_features",
                    provider="analytics_technical_daily",
                    known_at=known,
                    note="transparent_trend_momentum_vol_drawdown_volume",
                ),
            ),
            feature_snapshot_hash=_feature_hash(features),
            data_freshness=data_freshness,
            limitations=tuple(limitations),
            model_metadata={
                "factor_contributions": {k: factors[k] for k in _WEIGHTS},
                "weights": dict(_WEIGHTS),
                "coverage_ratio": coverage,
                "categories": ("trend", "momentum", "volatility", "drawdown", "volume"),
                "candidate_promotion": False,
            },
        )
