"""Predeclared Investment Committee policy — not tuned to historical returns.

Version id matches contracts.COMMITTEE_POLICY_VERSION:
``committee_policy_v1_predeclared``.

Design principles (transparent, auditable):
- equal semantic-family weights (explicit table; no outcome optimization);
- quorum of independent valid models required;
- disagreement preserved as a first-class score and confidence penalty;
- severe stale / missing core evidence → ABSTAIN;
- material adverse events may override weak positives (risk override, not averaging).
"""

from __future__ import annotations

from typing import Final

from app.modules.intelligence.contracts.committee import COMMITTEE_POLICY_VERSION

POLICY_VERSION: Final[str] = COMMITTEE_POLICY_VERSION

# Quorum: fewer than this many POSITIVE|NEUTRAL|NEGATIVE votes → ABSTAIN.
MIN_VALID_MODELS: Final[int] = 2

# Default signed contribution when SignalOutputV1.score is absent.
STATE_SCORE: Final[dict[str, float]] = {
    "POSITIVE": 0.50,
    "NEUTRAL": 0.00,
    "NEGATIVE": -0.50,
}

# Explicit equal weights by semantic family — do NOT retune on walk-forward returns.
SEMANTIC_WEIGHTS: Final[dict[str, float]] = {
    "TECHNICAL": 1.0,
    "FUNDAMENTAL": 1.0,
    "BANK": 1.0,
    "EVENT": 1.0,
    "MACRO": 1.0,
    "NEWS": 1.0,
    "ML": 1.0,
    "INTRADAY": 1.0,
    "RELATIONS": 1.0,
}
DEFAULT_WEIGHT: Final[float] = 1.0

# Advisory thresholds on confidence-weighted mean score in [-1, 1].
CONSIDER_INCREASE_MIN: Final[float] = 0.25
CONSIDER_REDUCE_MAX: Final[float] = -0.25

# Disagreement ≥ this → refuse CONSIDER_* (emit HOLD) while still reporting the score.
HIGH_DISAGREEMENT: Final[float] = 0.55

# Confidence multipliers (multiplicative, predeclared).
DISAGREEMENT_CONFIDENCE_SLOPE: Final[float] = 1.0  # confidence *= (1 - slope * disagreement)
RISK_HIGH_CONFIDENCE_FACTOR: Final[float] = 0.55
RISK_ELEVATED_CONFIDENCE_FACTOR: Final[float] = 0.75
STALE_SOFT_CONFIDENCE_FACTOR: Final[float] = 0.70

# Weak-positive gate for material-event risk override.
WEAK_POSITIVE_MEAN_MAX: Final[float] = 0.45
MATERIAL_EVENT_RULE_ID: Final[str] = "material_event_overrides_weak_trend"
STALE_DATA_RULE_ID: Final[str] = "stale_data_blocks_confidence"

# data_freshness / risk flag tokens (case-insensitive match on normalized form).
SEVERE_STALE_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "stale_severe",
        "severe_stale",
        "critical_stale",
        "stale_critical",
        "data_stale_severe",
    }
)
SOFT_STALE_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "stale",
        "stale_warn",
        "stale_mild",
        "data_stale",
        "stale_fundamentals",
        "stale_prices",
    }
)

VALID_SIGNAL_STATES: Final[frozenset[str]] = frozenset({"POSITIVE", "NEUTRAL", "NEGATIVE"})
NON_VOTING_STATES: Final[frozenset[str]] = frozenset({"ABSTAIN", "UNKNOWN"})

LIMITATION_ADVISORY_ONLY: Final[str] = "advisory_only_no_broker_orders"
LIMITATION_PREDECLARED: Final[str] = "weights_predeclared_not_tuned_to_returns"
LIMITATION_DISAGREEMENT_PRESERVED: Final[str] = "disagreement_preserved_not_averaged_away"
