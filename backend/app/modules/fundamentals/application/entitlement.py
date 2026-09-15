"""Dividend entitlement / ex-date service (V1).

Combines APPROVED dividend record_date + MOEX equity settlement regime +
trading calendar → estimated ex-date.

Does not mutate dividend rows. Ingest continues to leave ``ex_date`` null unless
a caller explicitly requests estimation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.modules.fundamentals.domain.settlement_ex_date import (
    MOEX_EQUITY_T1_EFFECTIVE,
    estimate_ex_date,
    settlement_lag_trading_days,
)
from app.modules.market.domain.trading_calendar import (
    QUALITY_DERIVED_RU,
    QUALITY_WEEKENDS_ONLY,
    MoexEquityTradingCalendar,
)
from app.modules.market.infrastructure.ru_trading_calendar import get_moex_equity_trading_calendar

ENTITLEMENT_SERVICE_VERSION = "dividend_entitlement_v1"


@dataclass(frozen=True, slots=True)
class EntitlementResult:
    record_date: date | None
    ex_date: date | None
    settlement_cycle: str | None
    quality: str
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_date": None if self.record_date is None else self.record_date.isoformat(),
            "ex_date": None if self.ex_date is None else self.ex_date.isoformat(),
            "settlement_cycle": self.settlement_cycle,
            "quality": self.quality,
            "provenance": self.provenance,
            "service_version": ENTITLEMENT_SERVICE_VERSION,
        }


def derive_ex_date(
    record_date: date | None,
    *,
    calendar: MoexEquityTradingCalendar | None = None,
) -> EntitlementResult:
    """Derive ex-date from record date under evidence-based T+N + calendar."""
    cal = calendar if calendar is not None else get_moex_equity_trading_calendar()
    cov = cal.coverage()
    ex, prov = estimate_ex_date(record_date, calendar=cal.as_predicate())
    # Upgrade provenance quality when RU production calendar covers the walk.
    if record_date is not None and cov.get("quality") == QUALITY_DERIVED_RU:
        year_ok = record_date.year in set(cov.get("years") or [])
        if year_ok and ex is not None:
            # isdayoff = RU production workday calendar, NOT an official MOEX session dump.
            prov = {
                **prov,
                "quality": "DERIVED_FROM_RU_WORKDAY_CALENDAR",
                "calendar_quality": QUALITY_DERIVED_RU,
                "calendar_coverage": cov,
                "settlement_evidence": {
                    "t1_effective_from": MOEX_EQUITY_T1_EFFECTIVE.isoformat(),
                    "rule": "T+2 before 2023-07-31 inclusive boundary → T+1 on/after",
                    "source": "ADR 0014 / MOEX equity settlement regime research",
                },
            }
        elif not year_ok:
            prov = {
                **prov,
                "quality": "APPROXIMATE",
                "calendar_quality": QUALITY_WEEKENDS_ONLY,
                "reason": "record_date_outside_bundled_calendar_years",
                "calendar_coverage": cov,
            }
    return EntitlementResult(
        record_date=record_date,
        ex_date=ex,
        settlement_cycle=None if record_date is None else (
            "T+1" if settlement_lag_trading_days(record_date) == 1 else "T+2"
        ),
        quality=str(prov.get("quality") or "UNKNOWN"),
        provenance=prov,
    )


def entitlement_readiness() -> dict[str, Any]:
    cal = get_moex_equity_trading_calendar()
    cov = cal.coverage()
    return {
        "status": "PARTIAL",
        "service_version": ENTITLEMENT_SERVICE_VERSION,
        "calendar": cov,
        "settlement": {
            "t1_effective_from": MOEX_EQUITY_T1_EFFECTIVE.isoformat(),
            "pre_transition": "T+2",
            "post_transition": "T+1",
        },
        "quality": "DERIVED_FROM_RU_WORKDAY_CALENDAR",
        "notes": [
            "ex-date = record_date minus N trading days under settlement lag",
            "Calendar uses RU production holidays (isdayoff.ru) — not an official MOEX session calendar",
            "Ingest leaves ex_date null; this service is research / readiness only unless called",
        ],
    }
