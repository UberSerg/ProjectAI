"""Frozen PROSPECTIVE_MODEL_AB_V0 experiment identity and Model Edge constants."""

from __future__ import annotations

from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
from app.modules.prediction.candidate_v1_config import CANDIDATE_V1_RANKER_CONFIG
from app.modules.shadow.config import (
    MODEL_AB_EXPERIMENT_GROUP,
    MODEL_AB_PORTFOLIO_A_NAME,
    MODEL_AB_PORTFOLIO_B_NAME,
)
from app.modules.simulator.config import POLICY_HYSTERESIS_V1, RISK_NAME

EXPERIMENT_CODE = "PROSPECTIVE_MODEL_AB_V0"
EXPERIMENT_HUMAN_NAME = "Проспективное сравнение моделей V0 и V1"
EXPERIMENT_GROUP = MODEL_AB_EXPERIMENT_GROUP

STATUS_REGISTERED = "REGISTERED"
STATUS_ACTIVE = "ACTIVE"

# Prediction semantics. V0 forecasts a return; V1 emits a cross-sectional ranking score.
# A RANKING_SCORE must never be rendered as a percentage or fed to return arithmetic.
SEMANTIC_EXPECTED_RETURN = "EXPECTED_RETURN"
SEMANTIC_RANKING_SCORE = "RANKING_SCORE"

CANDIDATE_A_NAME = CANDIDATE_V0_CONFIG.candidate_name
CANDIDATE_A_VERSION = CANDIDATE_V0_CONFIG.candidate_version
CANDIDATE_B_NAME = CANDIDATE_V1_RANKER_CONFIG.candidate_name
CANDIDATE_B_VERSION = CANDIDATE_V1_RANKER_CONFIG.candidate_version

# Shadow portfolios owned by this experiment. Only the MODEL differs between them.
SHADOW_PORTFOLIO_A_NAME = MODEL_AB_PORTFOLIO_A_NAME
SHADOW_PORTFOLIO_B_NAME = MODEL_AB_PORTFOLIO_B_NAME
SHADOW_POLICY_NAME = POLICY_HYSTERESIS_V1
SHADOW_RISK_NAME = RISK_NAME
INITIAL_CAPITAL = 1_000_000.0

# Comparability of a paired batch.
FULLY_COMPARABLE = "FULLY_COMPARABLE"
PARTIALLY_COMPARABLE = "PARTIALLY_COMPARABLE"
NOT_COMPARABLE = "NOT_COMPARABLE"
# Eligible-set overlap at/above this share still counts as fully comparable.
FULL_COMPARABILITY_MIN_OVERLAP = 1.0
PARTIAL_COMPARABILITY_MIN_OVERLAP = 0.90

# Cash hurdle: a fixed annual compounding benchmark used only as post-processing.
# It never mutates Simulator / Shadow cash or NAV.
CASH_HURDLE_ANNUAL_RATE = 0.10
CASH_HURDLE_DAY_COUNT = 365.25
CASH_HURDLE_LABEL = "CASH_HURDLE_10PCT_ANNUAL"

# Economic viability labelling thresholds (excess return over the cash hurdle).
VIABILITY_CLEARLY_ABOVE = 0.02
VIABILITY_CLEARLY_BELOW = -0.02

DIAGNOSTICS_VERSION = "MODEL_DIAGNOSTICS_V0"
DIAGNOSTICS_SEGMENT = "DEVELOPMENT_OOS"
DIAGNOSTICS_TOP_SHARES: tuple[float, ...] = (0.05, 0.10, 0.20, 0.30)
DIAGNOSTICS_OVERLAP_TOP_N = 20
DIAGNOSTICS_PERSISTENCE_TOP_N: tuple[int, ...] = (20, 35)
DIAGNOSTICS_MIN_IC_INSTRUMENTS = CANDIDATE_V0_CONFIG.min_ic_instruments
ECONOMIC_COST_GRID_BPS: tuple[float, ...] = (0.0, 5.0, 10.0, 20.0)

# Daily cycle stage names. All Model Edge stages are non-fatal by contract.
STAGE_PAIRED_FORWARD = "PROSPECTIVE_MODEL_AB"
STAGE_PAIRED_SHADOW = "PROSPECTIVE_MODEL_AB_SHADOW"
STAGE_PAIRED_OUTCOME = "PROSPECTIVE_MODEL_AB_OUTCOME"


def candidate_a_config_hash() -> str:
    return CANDIDATE_V0_CONFIG.config_hash()


def candidate_b_config_hash() -> str:
    return CANDIDATE_V1_RANKER_CONFIG.config_hash()


def semantic_for_candidate_version(candidate_version: str) -> str:
    if candidate_version == CANDIDATE_B_VERSION:
        return SEMANTIC_RANKING_SCORE
    return SEMANTIC_EXPECTED_RETURN
