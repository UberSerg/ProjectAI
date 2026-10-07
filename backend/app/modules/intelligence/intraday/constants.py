"""Intraday intelligence constants (MOEX TQBR 60m primary)."""

from __future__ import annotations

PRIMARY_INTERVAL = "60m"
SOURCE_MOEX = "MOEX"
FEATURE_SET_VERSION = "intraday_features_v1"

# Main continuous auction hours (MSK begin hour of 60m bars).
# 09:00 bar is thin opening-auction / early; evening session is 19–23.
MAIN_SESSION_HOURS = tuple(range(10, 19))  # 10..18 inclusive
MORNING_HOURS = (10, 11, 12, 13)
AFTERNOON_HOURS = (14, 15, 16, 17, 18)
FIRST_HOUR = 10
LAST_MAIN_HOUR = 18

# Coverage thresholds for a completed main session on 60m.
MIN_BARS_READY = 7
MIN_BARS_PARTIAL = 1

COVERAGE_READY = "READY"
COVERAGE_PARTIAL = "PARTIAL"
COVERAGE_MISSING = "MISSING"
COVERAGE_UNKNOWN = "UNKNOWN"
