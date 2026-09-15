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
from app.modules.market.infrastructure.moex_session_calendar import (
    QUALITY_MOEX_HISTORY,
    MoexIssHistorySessionCalendar,
    get_moex_iss_history_session_calendar,
)
from app.modules.market.infrastructure.ru_trading_calendar import get_moex_equity_trading_calendar

ENTITLEMENT_SERVICE_VERSION = "dividend_entitlement_v2"


@dataclass(frozen=True, slots=True)
class EntitlementResult:
    record_date: date | None
    ex_date: date | None
    last_eligible_trading_date: date | None
    settlement_cycle: str | None
    quality: str
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_date": None if self.record_date is None else self.record_date.isoformat(),
            "ex_date": None if self.ex_date is None else self.ex_date.isoformat(),
            "last_eligible_trading_date": (
                None
                if self.last_eligible_trading_date is None
                else self.last_eligible_trading_date.isoformat()
            ),
            "settlement_cycle": self.settlement_cycle,
            "quality": self.quality,
            "provenance": self.provenance,
            "service_version": ENTITLEMENT_SERVICE_VERSION,
        }


def derive_ex_date(
    record_date: date | None,
    *,
    calendar: MoexIssHistorySessionCalendar | MoexEquityTradingCalendar | None = None,
) -> EntitlementResult:
    """Derive ex-date from record date under evidence-based T+N + calendar.

    Prefer MOEX ISS history session calendar; fall back to RU workday calendar.
    ``ex_date`` = first session on which a purchase is NOT entitled.
    ``last_eligible_trading_date`` = previous trading session before ex_date (cum-div).
    """
    cal: Any
    if calendar is not None:
        cal = calendar
    else:
        cal = get_moex_iss_history_session_calendar()
        if not cal.trading_days:
            cal = get_moex_equity_trading_calendar()
    cov = cal.coverage()
    predicate = cal.as_predicate() if hasattr(cal, "as_predicate") else cal.is_trading_day
    ex, prov = estimate_ex_date(record_date, calendar=predicate)

    quality = str(prov.get("quality") or "UNKNOWN")
    if record_date is not None and ex is not None:
        cov_quality = str(cov.get("quality") or "")
        if cov_quality == QUALITY_MOEX_HISTORY and record_date.year in range(2021, 2027):
            quality = "DERIVED_FROM_MOEX_ISS_HISTORY_SESSIONS"
            prov = {
                **prov,
                "quality": quality,
                "calendar_quality": QUALITY_MOEX_HISTORY,
                "calendar_coverage": cov,
                "settlement_evidence": {
                    "t1_effective_from": MOEX_EQUITY_T1_EFFECTIVE.isoformat(),
                    "rule": "T+2 before 2023-07-31 inclusive boundary → T+1 on/after",
                    "source": "ADR 0014 / MOEX equity settlement regime research",
                },
            }
        elif cov_quality == QUALITY_DERIVED_RU:
            quality = "DERIVED_FROM_RU_WORKDAY_CALENDAR"
            prov = {
                **prov,
                "quality": quality,
                "calendar_quality": QUALITY_DERIVED_RU,
                "calendar_coverage": cov,
                "settlement_evidence": {
                    "t1_effective_from": MOEX_EQUITY_T1_EFFECTIVE.isoformat(),
                    "rule": "T+2 before 2023-07-31 inclusive boundary → T+1 on/after",
                    "source": "ADR 0014 / MOEX equity settlement regime research",
                },
            }

    last_eligible = None
    if ex is not None and hasattr(cal, "previous_trading_day"):
        last_eligible = cal.previous_trading_day(ex, inclusive=False)
    elif ex is not None:
        # Generic walk: day before ex that is trading.
        from datetime import timedelta

        cursor = ex - timedelta(days=1)
        for _ in range(14):
            if predicate(cursor):
                last_eligible = cursor
                break
            cursor -= timedelta(days=1)

    return EntitlementResult(
        record_date=record_date,
        ex_date=ex,
        last_eligible_trading_date=last_eligible,
        settlement_cycle=None
        if record_date is None
        else ("T+1" if settlement_lag_trading_days(record_date) == 1 else "T+2"),
        quality=quality,
        provenance=prov,
    )


def entitlement_readiness() -> dict[str, Any]:
    cal = get_moex_iss_history_session_calendar()
    cov = cal.coverage()
    ru = get_moex_equity_trading_calendar().coverage()
    status = "PARTIAL"
    quality = str(cov.get("quality") or QUALITY_WEEKENDS_ONLY)
    if quality == QUALITY_MOEX_HISTORY:
        status = "PARTIAL"  # still PARTIAL until full official session dump validated end-to-end
    return {
        "status": status,
        "service_version": ENTITLEMENT_SERVICE_VERSION,
        "calendar": cov,
        "fallback_calendar": ru,
        "settlement": {
            "t1_effective_from": MOEX_EQUITY_T1_EFFECTIVE.isoformat(),
            "pre_transition": "T+2",
            "post_transition": "T+1",
        },
        "quality": quality,
        "notes": [
            "Primary calendar: MOEX ISS SBER TQBR TRADEDATE history (observed sessions)",
            "Fallback: RU production workday calendar (isdayoff.ru)",
            "Engine dailytable alone is exception-only (~tens of rows), not a full calendar",
            "Ingest leaves ex_date null unless explicitly derived",
        ],
    }
