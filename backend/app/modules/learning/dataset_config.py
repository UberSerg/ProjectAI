"""Dataset / PIT Join — versioned dataset specifications (v1 frozen, v2 mechanical)."""

from __future__ import annotations

from typing import Any

from app.modules.technical.technical_config import (
    RULES_V1_CODE,
    RULES_V1_CONFIG_HASH,
    RULES_V1_VERSION,
    RULES_V2_CONFIG_HASH,
    RULES_V2_VERSION,
)

PIT_DAILY_CORE_CODE = "pit_daily_core"
PIT_DAILY_CORE_VERSION = 1
PIT_DAILY_CORE_V2_VERSION = 2
# Released contract stays active; V2 is buildable but not auto-activated.
PIT_DAILY_CORE_ACTIVE_VERSION = 1

# Dataset V0: Relations PIT join is part of X(t). Pin is basic_relations v1 only.
RELATIONS_JOIN_ENABLED = True


def relation_feature_names(contexts: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for ctx in contexts:
        key = ctx["key"]
        for w in ctx.get("windows", [20, 60, 120]):
            names.append(f"rel_{key}_w{w}_pearson")
            names.append(f"rel_{key}_w{w}_spearman")
            if w == 60:
                names.append(f"rel_{key}_w{w}_rolling_corr_std")
                names.append(f"rel_{key}_w{w}_sign_consistency")
        for lag in ctx.get("lags", [1, 2, 3, 4, 5]):
            names.append(f"rel_{key}_subject_leads_lag{lag}_pearson")
            names.append(f"rel_{key}_context_leads_lag{lag}_pearson")
    return names


def relation_feature_manifest_entries(contexts: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"name": name, "role": "feature", "source": "relations"} for name in relation_feature_names(contexts)]

# Real relation_inputs codes from Relations V1 seed (not invented).
RELATION_CONTEXTS_V1: list[dict[str, Any]] = [
    {
        "key": "imoex",
        "input_code": "instrument:IMOEX:log_return_1d",
        "display_name": "IMOEX",
        "windows": [20, 60, 120],
        "lag_window": 60,
        "lags": [1, 2, 3, 4, 5],
    },
    {
        "key": "usd_rub",
        "input_code": "series:USD_RUB_CBR:pct_change",
        "display_name": "USD/RUB",
        "windows": [20, 60, 120],
        "lag_window": 60,
        "lags": [1, 2, 3, 4, 5],
    },
    {
        "key": "cny_rub",
        "input_code": "series:CNY_RUB_CBR:pct_change",
        "display_name": "CNY/RUB",
        "windows": [20, 60, 120],
        "lag_window": 60,
        "lags": [1, 2, 3, 4, 5],
    },
    {
        "key": "key_rate",
        "input_code": "series:KEY_RATE:absolute_change",
        "display_name": "KEY_RATE",
        "windows": [20, 60, 120],
        "lag_window": 60,
        "lags": [1, 2, 3, 4, 5],
    },
]

FEATURE_MANIFEST_V1: list[dict[str, str]] = [
    # Analytics
    {"name": "return_1d", "role": "feature", "source": "analytics"},
    {"name": "return_5d", "role": "feature", "source": "analytics"},
    {"name": "return_20d", "role": "feature", "source": "analytics"},
    {"name": "volatility_5d", "role": "feature", "source": "analytics"},
    {"name": "volatility_20d", "role": "feature", "source": "analytics"},
    {"name": "drawdown_20d", "role": "feature", "source": "analytics"},
    {"name": "volume_change_1d", "role": "feature", "source": "analytics"},
    {"name": "volume_zscore_20d", "role": "feature", "source": "analytics"},
    # Technical raw
    {"name": "sma20_distance", "role": "feature", "source": "technical"},
    {"name": "ema20_distance", "role": "feature", "source": "technical"},
    {"name": "rsi14", "role": "feature", "source": "technical"},
    {"name": "atr14_pct", "role": "feature", "source": "technical"},
    # Technical agent
    {"name": "technical_score", "role": "feature", "source": "technical_agent"},
    {"name": "technical_confidence", "role": "feature", "source": "technical_agent"},
    {"name": "trend_contribution", "role": "feature", "source": "technical_agent"},
    {"name": "momentum_contribution", "role": "feature", "source": "technical_agent"},
    {"name": "rsi_contribution", "role": "feature", "source": "technical_agent"},
    {"name": "volume_contribution", "role": "feature", "source": "technical_agent"},
    # Relations — generated from RELATION_CONTEXTS_V1 so the spec lists full X(t)
    *relation_feature_manifest_entries(RELATION_CONTEXTS_V1),
    # Labels
    {"name": "forward_return_1d", "role": "label", "source": "market"},
    {"name": "forward_return_5d", "role": "label", "source": "market"},
    {"name": "forward_return_10d", "role": "label", "source": "market"},
    {"name": "forward_return_20d", "role": "label", "source": "market"},
    # Metadata (not X)
    {"name": "technical_direction", "role": "metadata", "source": "technical_agent"},
    {"name": "relation_as_of_date", "role": "metadata", "source": "relations"},
    {"name": "relation_age_days", "role": "metadata", "source": "relations"},
]

RELATION_FEATURE_PREFIXES = ("rel_",)

LABEL_SPEC_V1: dict[str, Any] = {
    "horizons": [1, 5, 10, 20],
    "formula": "close(t+N_observations) / close(t) - 1",
    "observation_basis": "trading_observations",
    "exclude_discontinuity_in_target_window": True,
}

QUALITY_POLICY_V1: dict[str, Any] = {
    "max_relation_age_days": 8,
    "require_core_features_valid": True,
    "require_technical_valid": True,
    "relations_optional": True,
    "relations_join_enabled": RELATIONS_JOIN_ENABLED,
    "relations_available_means": "at_least_one_context_usable",
    "relation_missing_means": "no_usable_context_for_sample",
    "relation_pit_field": "snapshot.as_of_date",
    "relation_run_source_watermark": "compute_lineage_not_pit",
    "no_imputation": True,
    "fail_hard_on_pit_violation": True,
}

PIT_DAILY_CORE_V1: dict[str, Any] = {
    "code": PIT_DAILY_CORE_CODE,
    "version": PIT_DAILY_CORE_VERSION,
    "description": "Point-in-time daily ML dataset: Analytics + Technical + Relations @ t; forward returns as labels",
    "feature_manifest": FEATURE_MANIFEST_V1,
    "relation_contexts": RELATION_CONTEXTS_V1,
    "label_spec": LABEL_SPEC_V1,
    "quality_policy": QUALITY_POLICY_V1,
    "basic_feature_set_code": "basic_daily",
    "basic_feature_set_version": 1,
    "technical_feature_set_code": "technical_daily",
    "technical_feature_set_version": 1,
    "technical_model_code": RULES_V1_CODE,
    "technical_model_version": RULES_V1_VERSION,
    "technical_model_config_hash": RULES_V1_CONFIG_HASH,
    "relation_set_code": "basic_relations",
    "relation_set_version": 1,
    "universe_policy": "current_active_instruments",
    "parameters": {
        "relation_windows": [20, 60, 120],
        "lag_window": 60,
        "lags": [1, 2, 3, 4, 5],
    },
}

# Same X schema as V1; pins + label price_basis differ. Do not mutate V1.
LABEL_SPEC_V2: dict[str, Any] = {
    "horizons": [1, 5, 10, 20],
    "formula": (
        "mechanical_comparable_close(t+N_observations) / mechanical_comparable_close(t) - 1 "
        "(SPLIT/REVERSE_SPLIT only; not dividend/total-return)"
    ),
    "observation_basis": "trading_observations",
    "price_basis": "mechanical_adjusted",
    "exclude_unexplained_discontinuity_in_target_window": True,
    "mechanical_ca_in_window": "normalize_not_invalidate",
    "dividend_adjusted": False,
    "total_return": False,
}

QUALITY_POLICY_V2: dict[str, Any] = {
    **QUALITY_POLICY_V1,
    "label_price_basis": "mechanical_adjusted",
    "mechanical_action_types": ["SPLIT", "REVERSE_SPLIT"],
}

PIT_DAILY_CORE_V2: dict[str, Any] = {
    "code": PIT_DAILY_CORE_CODE,
    "version": PIT_DAILY_CORE_V2_VERSION,
    "description": (
        "Point-in-time daily ML dataset V2: Analytics/Technical/Relations mechanical V2 pins; "
        "forward mechanical price-return labels (not dividend/total-return)"
    ),
    "feature_manifest": FEATURE_MANIFEST_V1,
    "relation_contexts": RELATION_CONTEXTS_V1,
    "label_spec": LABEL_SPEC_V2,
    "quality_policy": QUALITY_POLICY_V2,
    "basic_feature_set_code": "basic_daily",
    "basic_feature_set_version": 2,
    "technical_feature_set_code": "technical_daily",
    "technical_feature_set_version": 2,
    "technical_model_code": RULES_V1_CODE,
    "technical_model_version": RULES_V2_VERSION,
    "technical_model_config_hash": RULES_V2_CONFIG_HASH,
    "relation_set_code": "basic_relations",
    "relation_set_version": 2,
    "universe_policy": "current_active_instruments",
    "parameters": {
        "relation_windows": [20, 60, 120],
        "lag_window": 60,
        "lags": [1, 2, 3, 4, 5],
        "price_basis": "mechanical_adjusted",
        "label_price_basis": "mechanical_adjusted",
    },
}

DATASET_SPEC_DEFINITIONS: tuple[dict[str, Any], ...] = (PIT_DAILY_CORE_V1, PIT_DAILY_CORE_V2)

DATASET_BUILD_STEPS = [
    "Resolve dataset spec",
    "Resolve pinned source versions",
    "Resolve universe",
    "Load Analytics",
    "Load Technical",
    "Load Relations",
    "Build PIT features",
    "Build labels",
    "Apply quality",
    "Run PIT validation",
    "Materialize samples",
    "Calculate hashes",
    "Persist summary",
    "Finish",
]


def feature_names_from_manifest(manifest: list[dict[str, str]]) -> list[str]:
    return [m["name"] for m in manifest if m.get("role") == "feature"]


def label_names_from_manifest(manifest: list[dict[str, str]]) -> list[str]:
    return [m["name"] for m in manifest if m.get("role") == "label"]


def is_sample_relation_missing(*, relations_enabled: bool, relations_available: bool) -> bool:
    """Run-level relation_missing: join is on and the sample has no usable context.

    Disabled join is not missing. Partial coverage (some contexts usable) is not missing.
    """
    return relations_enabled and not relations_available


def is_horizon_training_eligible(
    *,
    core_valid: bool,
    technical_available: bool,
    label_valid: bool,
    relations_optional: bool = True,
    relations_available: bool = False,
) -> bool:
    """Relations are optional for Dataset V0: missing/stale/self does not block eligibility."""
    if not (core_valid and technical_available and label_valid):
        return False
    if relations_optional:
        return True
    return relations_available


def uses_mechanical_label_basis(label_spec: dict[str, Any] | None) -> bool:
    return (label_spec or {}).get("price_basis") == "mechanical_adjusted"
