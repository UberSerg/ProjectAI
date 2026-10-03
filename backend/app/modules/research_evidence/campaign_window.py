"""Predeclared Canonical Evidence Campaign V1 window (data availability, not outcomes).

``latest_mature_20d_as_of`` is derived only from the trading calendar, priced sessions,
and 20-session label maturity. It must not depend on IC, model returns, or economics.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from typing import Any, Protocol

from sqlalchemy import Date, cast, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument
from app.modules.prediction.application.splits import build_expanding_folds
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG, CandidateV0Config

PRIMARY_DATE_FROM = date(2022, 4, 1)
MIN_VIABLE_MATURE_AS_OF = date(2024, 4, 1)
LABEL_HORIZON_SESSIONS = 20
WINDOW_ROLE_PRIMARY = "PRIMARY"
WINDOW_ROLE_FULL_HISTORY_DIAGNOSTIC = "FULL_HISTORY_DIAGNOSTIC"
STATUS_OK = "OK"
STATUS_INSUFFICIENT = "CAMPAIGN_DATA_INSUFFICIENT"
PRIMARY_START_RATIONALE = (
    "Practical beginning of useful online FNS RAS known_at coverage around spring 2022 "
    "(data availability, not outcome optimization)."
)


class TradingDayCalendar(Protocol):
    def is_trading_day(self, day: date) -> bool: ...


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def latest_mature_20d_as_of(
    session_dates: Sequence[date],
    *,
    horizon_sessions: int = LABEL_HORIZON_SESSIONS,
) -> date | None:
    """Latest as_of that still has ``horizon_sessions`` later priced sessions.

    Maturity is session-count only: as_of at index i is mature iff i + horizon exists.
    Does not compute returns, IC, or eligibility flags.
    """
    ordered = sorted({day for day in session_dates})
    if horizon_sessions < 1 or len(ordered) <= horizon_sessions:
        return None
    return ordered[-(horizon_sessions + 1)]


def expanding_oos_fold_count(
    *,
    date_from: date,
    date_to: date | None,
    config: CandidateV0Config | None = None,
) -> int:
    """How many expanding folds the existing Candidate V0 contract would emit.

    Does not shorten ``min_train_years``. Empty folds mean the window is too short.
    """
    if date_to is None or date_to < date_from:
        return 0
    cfg = config or CANDIDATE_V0_CONFIG
    folds = build_expanding_folds(
        data_start=date_from,
        development_end_exclusive=date_to + timedelta(days=1),
        config=cfg,
    )
    return len(folds)


def load_priced_equity_session_dates(session: Session) -> list[date]:
    """Distinct daily equity candle dates (actual price history)."""
    stmt = (
        select(cast(Candle.timestamp, Date))
        .select_from(Candle)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Candle.timeframe == "1d", Instrument.asset_class == "equity")
        .distinct()
        .order_by(cast(Candle.timestamp, Date))
    )
    try:
        rows = session.execute(stmt).all()
    except Exception:  # noqa: BLE001 — snapshot must degrade honestly
        return []
    out: list[date] = []
    for row in rows:
        value = row[0] if not isinstance(row, date) else row
        if isinstance(value, date):
            out.append(value)
    return out


def sessions_on_calendar(
    priced_dates: Iterable[date],
    calendar: TradingDayCalendar | None,
) -> list[date]:
    """Intersect priced sessions with the trading calendar when one is provided."""
    ordered = sorted({day for day in priced_dates})
    if calendar is None:
        return ordered
    return [day for day in ordered if calendar.is_trading_day(day)]


def campaign_primary_bounds(window: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """Read frozen primary ``date_from`` / mature ``date_to`` from the window payload.

    ``resolve_campaign_window`` nests bounds under ``primary``; some fixtures flatten
    them. ``date_to`` may also be ``latest_mature_20d_as_of``. Never reads IC/returns.
    """
    if not isinstance(window, dict):
        return None, None
    primary = window.get("primary") if isinstance(window.get("primary"), dict) else {}
    date_from = window.get("date_from") or primary.get("date_from")
    date_to = (
        window.get("date_to")
        or primary.get("date_to")
        or window.get("latest_mature_20d_as_of")
    )
    return (
        str(date_from) if date_from else None,
        str(date_to) if date_to else None,
    )


def resolve_campaign_window(
    session_dates: Sequence[date],
    *,
    date_from: date = PRIMARY_DATE_FROM,
    horizon_sessions: int = LABEL_HORIZON_SESSIONS,
    min_viable_mature: date = MIN_VIABLE_MATURE_AS_OF,
    oos_config: CandidateV0Config | None = None,
) -> dict[str, Any]:
    """Primary campaign window plus optional full-history diagnostic bounds."""
    cfg = oos_config or CANDIDATE_V0_CONFIG
    ordered = sorted({day for day in session_dates})
    mature = latest_mature_20d_as_of(ordered, horizon_sessions=horizon_sessions)
    fold_n = expanding_oos_fold_count(date_from=date_from, date_to=mature, config=cfg)
    reasons: list[str] = []
    if mature is None:
        reasons.append("no_mature_20d_as_of")
    elif mature < min_viable_mature:
        reasons.append("latest_mature_20d_as_of_before_min_viable")
    if fold_n <= 0:
        reasons.append("too_short_for_expanding_oos")
    status = STATUS_INSUFFICIENT if reasons else STATUS_OK
    earliest = ordered[0] if ordered else None
    return {
        "status": status,
        "reasons": reasons,
        "primary": {
            "role": WINDOW_ROLE_PRIMARY,
            "date_from": date_from.isoformat(),
            "date_to": _iso(mature),
            "date_from_rationale": PRIMARY_START_RATIONALE,
            "replaces_after_outcomes": False,
        },
        "full_history_diagnostic": {
            "role": WINDOW_ROLE_FULL_HISTORY_DIAGNOSTIC,
            "date_from": _iso(earliest),
            "date_to": _iso(mature),
            "note": (
                "Coverage / robustness diagnostic only. Must not replace the predeclared "
                "primary window after seeing outcomes."
            ),
            "replaces_primary": False,
        },
        "latest_mature_20d_as_of": _iso(mature),
        "label_horizon_sessions": horizon_sessions,
        "priced_session_count": len(ordered),
        "expanding_oos": {
            "min_train_years": int(cfg.min_train_years),
            "validation_months": int(cfg.validation_months),
            "step_months": int(cfg.step_months),
            "fold_count": fold_n,
            "shortened_training": False,
        },
        "min_viable_mature_as_of": min_viable_mature.isoformat(),
        "derivation": {
            "inputs": ["trading_calendar", "priced_equity_sessions", "label_horizon_sessions"],
            "excluded": ["ic", "model_return", "benchmark_return", "economics"],
        },
    }


def resolve_primary_campaign_window(
    session: Session,
    *,
    calendar: TradingDayCalendar | None = None,
    oos_config: CandidateV0Config | None = None,
) -> dict[str, Any]:
    """Load priced equity sessions, intersect the trading calendar, resolve the window."""
    cal = calendar
    if cal is None:
        from app.modules.market.infrastructure.ru_trading_calendar import (
            get_moex_equity_trading_calendar,
        )

        cal = get_moex_equity_trading_calendar()
    priced = load_priced_equity_session_dates(session)
    sessions = sessions_on_calendar(priced, cal)
    payload = resolve_campaign_window(sessions, oos_config=oos_config)
    payload["calendar"] = {
        "applied": True,
        "priced_session_count": len(priced),
        "calendar_session_count": len(sessions),
        "quality": "DERIVED_FROM_RU_PRODUCTION_CALENDAR",
        "note": "Not an official MOEX session dump; weekends + RU public holidays excluded.",
    }
    return payload
