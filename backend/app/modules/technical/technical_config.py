"""Technical Agent V1 configuration — feature set + rules_v1 model."""

from __future__ import annotations

import hashlib
import json
from typing import Any, TypedDict


class FeatureSetDefinition(TypedDict):
    code: str
    version: int
    description: str
    parameters: dict[str, Any]


TECHNICAL_DAILY_V1: FeatureSetDefinition = {
    "code": "technical_daily",
    "version": 1,
    "description": "Daily technical indicators (SMA/EMA distance, RSI14 Wilder, ATR14 pct)",
    "parameters": {
        "sma_window": 20,
        "ema_span": 20,
        "ema_adjust": False,
        "ema_min_periods": 20,
        "rsi_period": 14,
        "atr_period": 14,
        # Full-history recompute for Update (exact Wilder/EMA equivalence).
        "incremental_strategy": "full_history_tail_persist",
        "incremental_safety_observations": 5,
        "max_indicator_lookback": 20,
    },
}

TECHNICAL_DAILY_V2: FeatureSetDefinition = {
    "code": "technical_daily",
    "version": 2,
    "description": (
        "Daily technical indicators on PIT mechanical-adjusted OHLCV "
        "(SPLIT/REVERSE_SPLIT only; not dividend/total-return)"
    ),
    "parameters": {
        "sma_window": 20,
        "ema_span": 20,
        "ema_adjust": False,
        "ema_min_periods": 20,
        "rsi_period": 14,
        "atr_period": 14,
        "incremental_strategy": "full_history_tail_persist",
        "incremental_safety_observations": 5,
        "max_indicator_lookback": 20,
        "price_basis": "mechanical_adjusted",
        "volume_basis": "mechanical_adjusted",
        "basic_feature_set_code": "basic_daily",
        "basic_feature_set_version": 2,
        "mechanical_action_types": ["SPLIT", "REVERSE_SPLIT"],
    },
}

TECHNICAL_FEATURE_SETS: tuple[FeatureSetDefinition, ...] = (TECHNICAL_DAILY_V1, TECHNICAL_DAILY_V2)

RULES_V1_CODE = "rules"
RULES_V1_VERSION = 1
RULES_V2_VERSION = 2

RULES_V1_CONFIG: dict[str, Any] = {
    "trend_weight": 0.35,
    "momentum_weight": 0.35,
    "rsi_weight": 0.20,
    "volume_weight": 0.10,
    "distance_scale": 0.05,
    "return_scale": 0.10,
    "rsi_center": 50.0,
    "rsi_scale": 20.0,
    "volume_scale": 3.0,
    "bullish_threshold": 0.20,
    "bearish_threshold": -0.20,
    "momentum_return_5d_weight": 0.6,
    "momentum_return_20d_weight": 0.4,
    "required_factors": ["trend", "momentum", "rsi", "volume"],
}

TECHNICAL_BACKFILL_STEPS = [
    "Resolve model",
    "Resolve feature sets",
    "Resolve universe",
    "Load source market/basic analytics",
    "Calculate technical features",
    "Persist technical features",
    "Build frozen model inputs",
    "Evaluate rules model",
    "Persist technical signals",
    "Run quality summary",
    "Finish",
]


def config_hash(config: dict[str, Any]) -> str:
    """Stable SHA-256 over canonical JSON of model config."""
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


RULES_V1_CONFIG_HASH = config_hash(RULES_V1_CONFIG)
RULES_V2_CONFIG = dict(RULES_V1_CONFIG)
RULES_V2_CONFIG_HASH = config_hash(RULES_V2_CONFIG)


class TechnicalContract(TypedDict):
    model_code: str
    model_version: int
    basic_code: str
    basic_version: int
    technical_code: str
    technical_version: int
    config: dict[str, Any]
    config_hash: str
    price_basis: str


TECHNICAL_CONTRACTS: dict[tuple[str, int], TechnicalContract] = {
    (RULES_V1_CODE, RULES_V1_VERSION): {
        "model_code": RULES_V1_CODE,
        "model_version": RULES_V1_VERSION,
        "basic_code": "basic_daily",
        "basic_version": 1,
        "technical_code": "technical_daily",
        "technical_version": 1,
        "config": RULES_V1_CONFIG,
        "config_hash": RULES_V1_CONFIG_HASH,
        "price_basis": "raw",
    },
    (RULES_V1_CODE, RULES_V2_VERSION): {
        "model_code": RULES_V1_CODE,
        "model_version": RULES_V2_VERSION,
        "basic_code": "basic_daily",
        "basic_version": 2,
        "technical_code": "technical_daily",
        "technical_version": 2,
        "config": RULES_V2_CONFIG,
        "config_hash": RULES_V2_CONFIG_HASH,
        "price_basis": "mechanical_adjusted",
    },
}


def resolve_technical_contract(model_code: str, model_version: int) -> TechnicalContract:
    contract = TECHNICAL_CONTRACTS.get((model_code, model_version))
    if contract is None:
        raise ValueError(f"Unknown model {model_code} v{model_version}")
    return contract


def list_technical_contracts() -> tuple[TechnicalContract, ...]:
    return tuple(TECHNICAL_CONTRACTS[key] for key in sorted(TECHNICAL_CONTRACTS))
