"""Daily Research Cycle V0 constants and pins."""

from __future__ import annotations

CYCLE_NAME = "DAILY_RESEARCH_CYCLE_V0"
CYCLE_WORKFLOW_TYPE = "DAILY_RESEARCH_CYCLE_V0"
LOCK_KEY = "projectai:lock:daily_research_cycle"
LOCK_TTL_SECONDS = 60 * 60 * 3

CYCLE_STEPS = [
    "SOURCE_DISCOVERY",
    "MARKET_UPDATE",
    "CBR_UPDATE",
    "CORPORATE_ACTION_UPDATE",
    "ANALYTICS_V2",
    "TECHNICAL_V2",
    "RELATIONS_V2",
    "FORWARD_SIGNAL",
    "SHADOW_ADVANCE",
    # Experimental Model Edge stages — non-fatal; must not block operational V0.
    "PROSPECTIVE_MODEL_AB",
    "PROSPECTIVE_MODEL_AB_SHADOW",
    "FORWARD_OUTCOME_EVALUATION",
    "PROSPECTIVE_MODEL_AB_OUTCOME",
    "FINALIZE",
]

# Exact V2 pins — never active/latest resolution
ANALYTICS_CODE = "basic_daily"
ANALYTICS_VERSION = 2
TECHNICAL_MODEL_CODE = "rules"
TECHNICAL_MODEL_VERSION = 2
RELATIONS_CODE = "basic_relations"
RELATIONS_VERSION = 2
