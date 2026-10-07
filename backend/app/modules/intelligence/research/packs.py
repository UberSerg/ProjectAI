"""Feature-pack definitions for Intelligence Research V1.

Packs are research contracts over named feature groups. They reuse existing
V3/V4 feature names where historically honest, and declare intelligence-only
additive names without marketing a Dataset V5 product milestone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.intelligence.research.constants import (
    DOMAIN_BASE,
    DOMAIN_EVENT,
    DOMAIN_INTRADAY,
    DOMAIN_MACRO,
    DOMAIN_NEWS,
    DOMAIN_RICH_FUNDAMENTAL,
    FEATURE_PACKS,
    PACK_BASE,
    PACK_BASE_EVENT,
    PACK_BASE_INTRADAY,
    PACK_BASE_MACRO,
    PACK_BASE_RICH_FUNDAMENTAL,
    PACK_INTELLIGENCE_FULL,
)
from app.modules.learning.dataset_config import (
    V4_EVENT_FEATURE_NAMES,
    V4_FUNDAMENTAL_FEATURE_NAMES,
    feature_names_for_spec_version,
)

# Agent A intraday daily aggregation keys (intelligence/intraday).
INTRADAY_FEATURE_NAMES: tuple[str, ...] = (
    "overnight_gap",
    "open_to_close_return",
    "first_hour_return",
    "last_hour_return",
    "morning_return",
    "afternoon_return",
    "session_high_low_range",
    "realized_intraday_volatility",
    "intraday_return_std",
    "absolute_move_sum",
    "trend_efficiency",
    "close_vs_session_vwap",
    "close_location_in_range",
    "max_positive_bar",
    "max_negative_bar",
    "volume_first_hour_share",
    "volume_last_hour_share",
    "volume_concentration",
    "intraday_volume_zscore",
    "price_volume_confirmation",
    "morning_vs_afternoon_divergence",
    "intraday_reversal",
    "intraday_momentum",
)

# Richer industrial RAS ratios / deltas beyond frozen V4 pack (Agent B vocabulary).
# Still FNS-only; bank/IFRS lines stay out of historical packs.
RICH_FUNDAMENTAL_EXTRA_NAMES: tuple[str, ...] = (
    "fund_roa",
    "fund_roe",
    "fund_leverage_assets_to_equity",
    "fund_debt_to_assets",
    "fund_asset_turnover",
    "fund_accrual_proxy",
    "fund_revenue_yoy",
    "fund_net_income_yoy",
    "fund_net_margin_delta",
    "fund_roe_delta",
)

RICH_FUNDAMENTAL_FEATURE_NAMES: tuple[str, ...] = (
    tuple(V4_FUNDAMENTAL_FEATURE_NAMES) + RICH_FUNDAMENTAL_EXTRA_NAMES
)

# Event pack: historically honest mechanical CA + V4 dividend disclosure fields.
# News-derived materiality counts are prospective-only (see NEWS_FEATURE_NAMES).
EVENT_FEATURE_NAMES: tuple[str, ...] = tuple(V4_EVENT_FEATURE_NAMES)

# Explicit macro levels / short changes (Agent G). Relations already embed
# KEY_RATE/FX windows inside BASE; these are additive intelligence macros.
MACRO_FEATURE_NAMES: tuple[str, ...] = (
    "macro_key_rate_level",
    "macro_key_rate_change_20d",
    "macro_usd_rub_return_20d",
    "macro_cny_rub_return_20d",
    "macro_ruonia_spread_vs_key_rate",
)

# News / LLM-extracted document features — default PROSPECTIVE_ONLY when known_at
# cannot be established before first observation (often "today").
NEWS_FEATURE_NAMES: tuple[str, ...] = (
    "news_material_event_count_7d",
    "news_material_event_count_30d",
    "news_adverse_materiality_max_30d",
    "news_days_since_last_material_event",
)

DOMAIN_FEATURE_NAMES: dict[str, tuple[str, ...]] = {
    DOMAIN_BASE: (),  # filled at runtime from V3 feature names
    DOMAIN_INTRADAY: INTRADAY_FEATURE_NAMES,
    DOMAIN_RICH_FUNDAMENTAL: RICH_FUNDAMENTAL_FEATURE_NAMES,
    DOMAIN_EVENT: EVENT_FEATURE_NAMES,
    DOMAIN_MACRO: MACRO_FEATURE_NAMES,
    DOMAIN_NEWS: NEWS_FEATURE_NAMES,
}

# Which additive domains each named pack includes (BASE is always present).
PACK_ADDITIVE_DOMAINS: dict[str, tuple[str, ...]] = {
    PACK_BASE: (),
    PACK_BASE_INTRADAY: (DOMAIN_INTRADAY,),
    PACK_BASE_RICH_FUNDAMENTAL: (DOMAIN_RICH_FUNDAMENTAL,),
    PACK_BASE_EVENT: (DOMAIN_EVENT,),
    PACK_BASE_MACRO: (DOMAIN_MACRO,),
    # FULL = historically honest union only — news excluded by design.
    PACK_INTELLIGENCE_FULL: (
        DOMAIN_INTRADAY,
        DOMAIN_RICH_FUNDAMENTAL,
        DOMAIN_EVENT,
        DOMAIN_MACRO,
    ),
}


@dataclass(frozen=True, slots=True)
class FeaturePackSpec:
    """One named pack: BASE features plus zero or more additive domains."""

    name: str
    base_features: tuple[str, ...]
    additive_domains: tuple[str, ...]
    additive_features: tuple[str, ...]
    excludes_news: bool = True

    @property
    def feature_names(self) -> list[str]:
        return list(self.base_features) + list(self.additive_features)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base_feature_count": len(self.base_features),
            "additive_domains": list(self.additive_domains),
            "additive_feature_count": len(self.additive_features),
            "feature_names": self.feature_names,
            "excludes_news": self.excludes_news,
            "includes_news": False,
            "note": (
                "News features are prospective-only by default and never enter "
                "INTELLIGENCE_FULL historical packs."
            ),
        }


def base_feature_names() -> list[str]:
    """V3 / FEATURE_MANIFEST_V1 feature role names (not labels)."""
    return feature_names_for_spec_version(3)


def additive_feature_names(domains: tuple[str, ...] | list[str]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for domain in domains:
        if domain == DOMAIN_BASE:
            continue
        if domain == DOMAIN_NEWS:
            # Never silently fold news into historical packs.
            continue
        for name in DOMAIN_FEATURE_NAMES.get(domain, ()):
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def build_feature_pack(name: str) -> FeaturePackSpec:
    if name not in FEATURE_PACKS:
        raise ValueError(f"unknown Intelligence Research pack: {name}")
    base = tuple(base_feature_names())
    additive_domains = PACK_ADDITIVE_DOMAINS[name]
    additive = tuple(additive_feature_names(additive_domains))
    return FeaturePackSpec(
        name=name,
        base_features=base,
        additive_domains=additive_domains,
        additive_features=additive,
        excludes_news=True,
    )


def all_feature_packs() -> dict[str, FeaturePackSpec]:
    return {name: build_feature_pack(name) for name in FEATURE_PACKS}


def feature_group_definitions() -> dict[str, list[str]]:
    """Frozen pack → feature name lists for experiment identity fingerprinting."""
    return {name: pack.feature_names for name, pack in all_feature_packs().items()}


def prospective_only_feature_names() -> list[str]:
    """Features that default to prospective-only evaluation."""
    return list(NEWS_FEATURE_NAMES)
