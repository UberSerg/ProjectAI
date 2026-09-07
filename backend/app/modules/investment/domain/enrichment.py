"""Fixed Income enrichment queue — kinds, priorities, statuses."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class EnrichmentKind(StrEnum):
    FIXED_INCOME_TERMS = "FIXED_INCOME_TERMS"
    FIXED_INCOME_CASHFLOWS = "FIXED_INCOME_CASHFLOWS"
    FIXED_INCOME_MARKET = "FIXED_INCOME_MARKET"
    DIVIDEND_HISTORY = "DIVIDEND_HISTORY"


class EnrichmentStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NO_DATA = "NO_DATA"


class EnrichmentPriority(IntEnum):
    """Lower number = higher priority."""

    P0_PORTFOLIO = 0  # Manual Portfolio + Shadow positions/orders + Candidate selections
    P1_NEW_BOND = 1  # newly discovered bonds from master sync
    P2_OFZ = 2
    P3_OTHER_BOND = 3
    P4_INACTIVE = 4


FI_KINDS: tuple[EnrichmentKind, ...] = (
    EnrichmentKind.FIXED_INCOME_TERMS,
    EnrichmentKind.FIXED_INCOME_CASHFLOWS,
    EnrichmentKind.FIXED_INCOME_MARKET,
)

LOCK_KEY = "projectai:fi_enrichment:lock"
LOCK_TTL_SECONDS = 600
