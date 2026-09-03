"""Feature set definitions — single source of configuration."""

from __future__ import annotations

from typing import Any, TypedDict


class FeatureSetDefinition(TypedDict):
    code: str
    version: int
    description: str
    parameters: dict[str, Any]


BASIC_DAILY_V1: FeatureSetDefinition = {
    "code": "basic_daily",
    "version": 1,
    "description": "Daily instrument and series features for Analytics V1",
    "parameters": {
        "return_windows": [1, 2, 3, 5, 10, 20],
        "volatility_windows": [5, 20],
        "drawdown_window": 20,
        "volume_zscore_window": 20,
        "volatility_ddof": 1,
        "volatility_annualized": False,
        "max_lookback_observations": 20,
        "incremental_safety_observations": 25,
    },
}

BASIC_DAILY_V2: FeatureSetDefinition = {
    "code": "basic_daily",
    "version": 2,
    "description": (
        "Daily features on PIT mechanical-adjusted close/volume "
        "(SPLIT/REVERSE_SPLIT only; not dividend/total-return)"
    ),
    "parameters": {
        "return_windows": [1, 2, 3, 5, 10, 20],
        "volatility_windows": [5, 20],
        "drawdown_window": 20,
        "volume_zscore_window": 20,
        "volatility_ddof": 1,
        "volatility_annualized": False,
        "max_lookback_observations": 20,
        "incremental_safety_observations": 25,
        "price_basis": "mechanical_adjusted",
        "volume_basis": "mechanical_adjusted",
        "mechanical_action_types": ["SPLIT", "REVERSE_SPLIT"],
    },
}

FEATURE_SETS: tuple[FeatureSetDefinition, ...] = (BASIC_DAILY_V1, BASIC_DAILY_V2)

RETURN_COLUMNS = ("return_1d", "return_2d", "return_3d", "return_5d", "return_10d", "return_20d")

FEATURE_BACKFILL_STEPS = [
    "Resolve feature set",
    "Resolve universe",
    "Load source market data",
    "Load source quality issues",
    "Calculate instrument features",
    "Calculate series features",
    "Persist batches",
    "Run feature quality summary",
    "Finish",
]
