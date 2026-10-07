"""IntelligenceRefreshV1 constants — no aggressive polling schedule."""

from __future__ import annotations

REFRESH_WORKFLOW_KEY = "IntelligenceRefreshV1"
REFRESH_NAME = "IntelligenceRefreshV1"
LOCK_KEY = "projectai:lock:intelligence_refresh_v1"
LOCK_TTL_SECONDS = 60 * 60 * 2

# Bounded retries per stage (attempts = 1 + MAX_STAGE_RETRIES).
MAX_STAGE_RETRIES = 2
RETRY_BACKOFF_SECONDS = 0.05  # unit-test friendly; production hooks may override

REFRESH_STAGES: list[str] = [
    "MARKET_INTRADAY",
    "FUNDAMENTALS",
    "NEWS",
    "EXTRACT_EVENTS",
    "MACRO",
    "BUILD_SNAPSHOTS",
    "RUN_MODELS",
    "RISK",
    "COMMITTEE",
    "FINALIZE",
]

# Soft freshness budgets for OWNER diagnostics (hours). Warnings only — not hard fails.
SOURCE_STALE_HOURS: dict[str, float] = {
    "MARKET_INTRADAY": 24.0,
    "FUNDAMENTALS": 24.0 * 14,
    "NEWS": 24.0 * 3,
    "EXTRACT_EVENTS": 24.0 * 3,
    "MACRO": 24.0 * 3,
    "BUILD_SNAPSHOTS": 24.0,
    "RUN_MODELS": 24.0,
    "RISK": 24.0,
    "COMMITTEE": 24.0,
}

TERMINAL_STAGE_STATUSES = frozenset(
    {"SUCCESS", "WARNING", "SKIPPED", "FAILED", "ERROR", "NO_CHANGES"}
)
RETRYABLE_STAGE_STATUSES = frozenset({"FAILED", "ERROR"})
