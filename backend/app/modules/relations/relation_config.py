"""Relation set configuration — single source of parameters for Relations Engine V1."""

from __future__ import annotations

from typing import Any, TypedDict


class RelationSetDefinition(TypedDict):
    code: str
    version: int
    description: str
    parameters: dict[str, Any]


BASIC_RELATIONS_V1: RelationSetDefinition = {
    "code": "basic_relations",
    "version": 1,
    "description": "Statistical relations between instrument and series features (V1)",
    "parameters": {
        "correlation_methods": ["pearson", "spearman"],
        "windows": [20, 60, 120],
        "lead_lags": [1, 2, 3, 4, 5],
        "minimum_coverage_ratio": 0.8,
        "stability_subwindow": 20,
        "exclude_invalid_features": True,
        "exclude_price_discontinuities": True,
        "max_lookback_buffer": 160,
    },
}

RELATION_SETS: tuple[RelationSetDefinition, ...] = (BASIC_RELATIONS_V1,)

# Series transform policy for default relation inputs (documented, not silent).
# FX: pct_change of as-of aligned levels on market calendar.
# Rates: absolute_change of as-of aligned levels (never forward-fill last change).
SERIES_INPUT_TRANSFORMS: dict[str, dict[str, str]] = {
    "USD_RUB_CBR": {
        "feature_key": "pct_change",
        "transform": "asof_level_pct_change",
        "alignment_policy": "market_to_sparse_asof",
    },
    "EUR_RUB_CBR": {
        "feature_key": "pct_change",
        "transform": "asof_level_pct_change",
        "alignment_policy": "market_to_sparse_asof",
    },
    "CNY_RUB_CBR": {
        "feature_key": "pct_change",
        "transform": "asof_level_pct_change",
        "alignment_policy": "market_to_sparse_asof",
    },
    "KEY_RATE": {
        "feature_key": "absolute_change",
        "transform": "asof_level_absolute_change",
        "alignment_policy": "market_to_sparse_asof",
    },
    "RUONIA": {
        "feature_key": "absolute_change",
        "transform": "asof_level_absolute_change",
        "alignment_policy": "market_to_sparse_asof",
    },
}

INSTRUMENT_FEATURE_KEY = "log_return_1d"
INSTRUMENT_TRANSFORM = "analytics_log_return_1d"
INSTRUMENT_ALIGNMENT = "market_to_market"

RELATIONS_COMPUTE_STEPS = [
    "Resolve relation set",
    "Resolve / seed inputs",
    "Resolve as-of dates",
    "Load feature matrix",
    "Calculate relations",
    "Persist snapshots",
    "Run quality summary",
    "Finish",
]
