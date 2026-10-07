"""Intelligence Research V1 — frozen naming and isolation constants.

This is a NEW research experiment identity for Intelligence Stack packs.
It is NOT Dataset V5, does not retune V4 / Canonical Evidence Campaign,
and must never promote a production Candidate.
"""

from __future__ import annotations

from datetime import date

from app.modules.prediction.candidate_config import (
    MIN_TRAIN_YEARS,
    RANDOM_SEED,
    TARGET_LABEL,
)

EXPERIMENT_NAME = "Intelligence Research V1"
EXPERIMENT_VERSION = "intelligence_research_v1"
EVALUATION_WORDING = "CHRONOLOGICAL OOS RESEARCH"
PRIMARY_TARGET = TARGET_LABEL
TARGET_HORIZON = 20
MODEL_SEED = RANDOM_SEED

# Honest architectural priors (docs / public-data audit) — not fabricated backdates.
# FNS RAS useful online known_at coverage ≈ spring 2022 (Canonical Campaign window start).
FNS_EARLIEST_HONEST_KNOWN_AT = date(2022, 4, 1)
# CBR KEY_RATE / FX series exist long before intelligence stack.
CBR_MACRO_EARLIEST_HONEST_KNOWN_AT = date(2014, 1, 1)
# Mechanical MOEX splits feed — historically available; dividend PIT remains PARTIAL.
SPLIT_EVENT_EARLIEST_HONEST_KNOWN_AT = date(2014, 1, 1)

# Minimum calendar span before chronological OOS is offered (same pin family as Candidate).
MIN_HISTORICAL_YEARS_FOR_OOS = MIN_TRAIN_YEARS
MIN_ROWS_FOR_OOS = 500

MARKETING_FORBIDDEN = (
    "Dataset V5",
    "dataset_v5",
    "production Candidate",
    "Candidate promotion",
    "pristine final holdout",
    "live ready",
)

PACK_BASE = "BASE"
PACK_BASE_INTRADAY = "BASE+INTRADAY"
PACK_BASE_RICH_FUNDAMENTAL = "BASE+RICH_FUNDAMENTAL"
PACK_BASE_EVENT = "BASE+EVENT"
PACK_BASE_MACRO = "BASE+MACRO"
PACK_INTELLIGENCE_FULL = "INTELLIGENCE_FULL"

FEATURE_PACKS: tuple[str, ...] = (
    PACK_BASE,
    PACK_BASE_INTRADAY,
    PACK_BASE_RICH_FUNDAMENTAL,
    PACK_BASE_EVENT,
    PACK_BASE_MACRO,
    PACK_INTELLIGENCE_FULL,
)

# Evaluation eligibility classes (explicit separation required by contract).
MODE_HISTORICAL_EVALUABLE = "HISTORICAL_EVALUABLE"
MODE_PROSPECTIVE_ONLY = "PROSPECTIVE_ONLY"
MODE_INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
MODE_NOT_ELIGIBLE = "NOT_ELIGIBLE"

EVALUATION_MODES: frozenset[str] = frozenset(
    {
        MODE_HISTORICAL_EVALUABLE,
        MODE_PROSPECTIVE_ONLY,
        MODE_INSUFFICIENT_HISTORY,
        MODE_NOT_ELIGIBLE,
    }
)

DOMAIN_BASE = "base"
DOMAIN_INTRADAY = "intraday"
DOMAIN_RICH_FUNDAMENTAL = "rich_fundamental"
DOMAIN_EVENT = "event"
DOMAIN_MACRO = "macro"
DOMAIN_NEWS = "news"

ADDITIVE_DOMAINS: tuple[str, ...] = (
    DOMAIN_INTRADAY,
    DOMAIN_RICH_FUNDAMENTAL,
    DOMAIN_EVENT,
    DOMAIN_MACRO,
    DOMAIN_NEWS,
)
