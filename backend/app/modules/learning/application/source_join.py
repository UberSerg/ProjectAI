"""PIT source selection for Analytics / Technical — exact as-of, pinned versions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, TypeVar

T = TypeVar("T")

ANALYTICS_FEATURE_KEYS = (
    "return_1d",
    "return_5d",
    "return_20d",
    "volatility_5d",
    "volatility_20d",
    "drawdown_20d",
    "volume_change_1d",
    "volume_zscore_20d",
)

TECHNICAL_RAW_FEATURE_KEYS = (
    "sma20_distance",
    "ema20_distance",
    "rsi14",
    "atr14_pct",
)

TECHNICAL_SIGNAL_ATTRS: dict[str, str] = {
    "technical_score": "score",
    "technical_confidence": "confidence",
    "trend_contribution": "trend_contribution",
    "momentum_contribution": "momentum_contribution",
    "rsi_contribution": "rsi_contribution",
    "volume_contribution": "volume_contribution",
}


def to_float(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)


def select_exact_as_of(rows_by_date: dict[date, T], as_of: date) -> T | None:
    """Daily PIT: use only the row whose date/as_of equals t. Never a future row."""
    return rows_by_date.get(as_of)


def select_pinned_version(
    rows_by_version: dict[int, dict[date, T]],
    pinned_version: int,
    as_of: date,
) -> T | None:
    """Use the pinned version even if another version is currently active."""
    return select_exact_as_of(rows_by_version.get(pinned_version, {}), as_of)


def select_pinned_model(
    rows_by_model: dict[tuple[str, int], dict[date, T]],
    pinned_code: str,
    pinned_version: int,
    as_of: date,
) -> T | None:
    """Use the pinned model code/version, not whatever is latest/active."""
    return select_exact_as_of(rows_by_model.get((pinned_code, pinned_version), {}), as_of)


def analytics_feature_values(row: Any | None) -> dict[str, float | None]:
    if row is None:
        return {key: None for key in ANALYTICS_FEATURE_KEYS}
    return {key: to_float(getattr(row, key, None)) for key in ANALYTICS_FEATURE_KEYS}


def technical_raw_feature_values(row: Any | None) -> dict[str, float | None]:
    if row is None:
        return {key: None for key in TECHNICAL_RAW_FEATURE_KEYS}
    return {key: to_float(getattr(row, key, None)) for key in TECHNICAL_RAW_FEATURE_KEYS}


def technical_signal_feature_values(row: Any | None) -> tuple[dict[str, float | None], str | None]:
    if row is None:
        return {key: None for key in TECHNICAL_SIGNAL_ATTRS}, None
    values = {key: to_float(getattr(row, attr, None)) for key, attr in TECHNICAL_SIGNAL_ATTRS.items()}
    direction = getattr(row, "direction", None)
    return values, direction if isinstance(direction, str) else None


def merge_phase1_features(
    basic: Any | None,
    technical: Any | None,
    signal: Any | None,
) -> tuple[dict[str, float | None], str | None]:
    """X(t) from Analytics + Technical raw + Technical agent. No labels, no Relations."""
    values: dict[str, float | None] = {}
    values.update(analytics_feature_values(basic))
    values.update(technical_raw_feature_values(technical))
    signal_values, direction = technical_signal_feature_values(signal)
    values.update(signal_values)
    return values, direction
