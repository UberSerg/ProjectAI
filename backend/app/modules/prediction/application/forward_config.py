"""Forward Signal V0 frozen pins and constants."""

from __future__ import annotations

from app.modules.learning.dataset_config import (
    PIT_DAILY_CORE_V2,
    QUALITY_POLICY_V2,
    RELATION_CONTEXTS_V1,
)
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
from app.modules.technical.technical_config import RULES_V1_CODE, RULES_V2_CONFIG_HASH, RULES_V2_VERSION

FORWARD_SEGMENT = "FORWARD_LIVE"
OUTCOME_PENDING = "PENDING_OUTCOME"

# Exact source pins — never resolve active/latest
FORWARD_BASIC_FS_CODE = str(PIT_DAILY_CORE_V2["basic_feature_set_code"])
FORWARD_BASIC_FS_VERSION = int(PIT_DAILY_CORE_V2["basic_feature_set_version"])
FORWARD_TECH_FS_CODE = str(PIT_DAILY_CORE_V2["technical_feature_set_code"])
FORWARD_TECH_FS_VERSION = int(PIT_DAILY_CORE_V2["technical_feature_set_version"])
FORWARD_TECH_MODEL_CODE = RULES_V1_CODE
FORWARD_TECH_MODEL_VERSION = RULES_V2_VERSION
FORWARD_TECH_MODEL_CONFIG_HASH = RULES_V2_CONFIG_HASH
FORWARD_RELATION_SET_CODE = str(PIT_DAILY_CORE_V2["relation_set_code"])
FORWARD_RELATION_SET_VERSION = int(PIT_DAILY_CORE_V2["relation_set_version"])
FORWARD_RELATION_CONTEXTS = list(RELATION_CONTEXTS_V1)
FORWARD_MAX_RELATION_AGE_DAYS = int(QUALITY_POLICY_V2["max_relation_age_days"])
FORWARD_RELATIONS_OPTIONAL = bool(QUALITY_POLICY_V2.get("relations_optional", True))

# Market completeness: among instruments with a candle in the lookback window,
# require this fraction to have a candle on candidate as_of.
FORWARD_COMPLETENESS_RATIO = 0.80
FORWARD_COMPLETENESS_LOOKBACK_DAYS = 30

EXPECTED_CANDIDATE_CONFIG_HASH = CANDIDATE_V0_CONFIG.config_hash()
EXPECTED_FEATURE_SCHEMA_HASH = CANDIDATE_V0_CONFIG.feature_schema_hash()
EXPECTED_FEATURE_COUNT = 90
EXPECTED_DATASET_VALUES_HASH = CANDIDATE_V0_CONFIG.required_values_hash
