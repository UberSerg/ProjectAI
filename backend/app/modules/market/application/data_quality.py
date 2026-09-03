"""Market data quality checks with explicit historical vs operational modes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.infrastructure.market.models import (
    Candle,
    CorporateAction,
    DataQualityIssue,
    Instrument,
)
from app.modules.market.application.split_events import EVENT_TYPE_SPLIT

DQMode = Literal["historical", "operational"]


class DQModeEnum(StrEnum):
    HISTORICAL = "historical"
    OPERATIONAL = "operational"


@dataclass(slots=True, frozen=True)
class DataQualityContext:
    """Explicit DQ context — never inferred from wall-clock alone."""

    mode: DQMode
    date_from: date | None = None
    date_to: date | None = None
    batch_id: int | None = None
    stale_after_days: int = 7


def run_data_quality_checks(
    session: Session,
    context: DataQualityContext,
) -> dict[str, Any]:
    """Run DQ checks for the given explicit context."""
    if context.mode == "historical":
        if context.date_from is None or context.date_to is None:
            raise ValueError("historical DQ requires date_from and date_to")
        return _run_historical(session, context)
    return _run_operational(session, context)


def _run_historical(session: Session, context: DataQualityContext) -> dict[str, Any]:
    assert context.date_from is not None and context.date_to is not None
    start_ts = datetime.combine(context.date_from, datetime.min.time(), UTC)
    end_ts = datetime.combine(context.date_to, datetime.max.time(), UTC)
    counts = {"info": 0, "warning": 0, "error": 0, "by_type": {}}

    instruments = list(
        session.scalars(
            select(Instrument)
            .options(selectinload(Instrument.sources))
            .where(Instrument.is_active.is_(True))
        )
        .unique()
        .all()
    )

    candles = list(
        session.scalars(
            select(Candle).where(
                Candle.timeframe == "1d",
                Candle.timestamp >= start_ts,
                Candle.timestamp <= end_ts,
            )
        ).all()
    )
    split_dates = load_split_effective_dates(session)

    # Missing instrument mapping
    for instrument in instruments:
        if not instrument.sources:
            _issue(
                session,
                counts,
                context,
                instrument_id=instrument.id,
                issue_type="missing_instrument_mapping",
                severity="error",
                timestamp=None,
                message=f"Instrument {instrument.symbol} has no source mapping",
                details={"symbol": instrument.symbol},
            )

    # Empty response / no candles in requested range for mapped instruments
    candles_by_instrument: dict[int, list[Candle]] = {}
    for candle in candles:
        candles_by_instrument.setdefault(candle.instrument_id, []).append(candle)

    for instrument in instruments:
        if not any(s.source == "MOEX" for s in instrument.sources):
            continue
        bars = candles_by_instrument.get(instrument.id, [])
        if not bars:
            _issue(
                session,
                counts,
                context,
                instrument_id=instrument.id,
                issue_type="suspicious_empty_response",
                severity="warning",
                timestamp=None,
                message=(
                    f"No candles for {instrument.symbol} in "
                    f"{context.date_from}..{context.date_to}"
                ),
                details={
                    "symbol": instrument.symbol,
                    "date_from": context.date_from.isoformat(),
                    "date_to": context.date_to.isoformat(),
                },
            )

    # Duplicate timestamps (should be prevented by unique constraint)
    seen: dict[tuple[int, datetime, str], int] = {}
    for candle in candles:
        key = (candle.instrument_id, candle.timestamp, candle.source)
        seen[key] = seen.get(key, 0) + 1
    for key, n in seen.items():
        if n > 1:
            instrument_id, ts, source = key
            _issue(
                session,
                counts,
                context,
                instrument_id=instrument_id,
                issue_type="duplicate_candle",
                severity="error",
                timestamp=ts,
                message=f"Duplicate candle x{n}",
                details={"source": source, "count": n},
            )

    # Invalid OHLC / negative volume
    for candle in candles:
        if candle.high < candle.low or candle.close > candle.high or candle.close < candle.low:
            _issue(
                session,
                counts,
                context,
                instrument_id=candle.instrument_id,
                issue_type="invalid_ohlc",
                severity="error",
                timestamp=candle.timestamp,
                message="Invalid OHLC relationship",
                details={
                    "open": str(candle.open),
                    "high": str(candle.high),
                    "low": str(candle.low),
                    "close": str(candle.close),
                },
            )
        if candle.volume is not None and candle.volume < 0:
            _issue(
                session,
                counts,
                context,
                instrument_id=candle.instrument_id,
                issue_type="negative_volume",
                severity="error",
                timestamp=candle.timestamp,
                message="Negative volume",
                details={"volume": str(candle.volume)},
            )

    # Abnormal jumps within range
    for instrument_id, bars in candles_by_instrument.items():
        ordered = sorted(bars, key=lambda c: c.timestamp)
        for older, newer in zip(ordered, ordered[1:], strict=False):
            if older.close == 0:
                continue
            change = abs((newer.close - older.close) / older.close)
            if change >= Decimal("0.25"):
                _issue(
                    session,
                    counts,
                    context,
                    instrument_id=instrument_id,
                    issue_type="abnormal_price_jump",
                    severity="warning",
                    timestamp=newer.timestamp,
                    message=f"Close changed by {float(change):.1%} vs previous bar",
                    details=_jump_details(
                        older,
                        newer,
                        explained_by_split=(instrument_id, newer.timestamp.date()) in split_dates,
                    ),
                )

    # Gaps vs trading calendar inferred from loaded MOEX dates (not wall-clock today)
    trading_days = sorted({c.timestamp.date() for c in candles})
    if len(trading_days) >= 5:
        trading_set = set(trading_days)
        for instrument in instruments:
            if not any(s.source == "MOEX" for s in instrument.sources):
                continue
            bars = candles_by_instrument.get(instrument.id, [])
            if not bars:
                continue
            present = {c.timestamp.date() for c in bars}
            # Only evaluate gaps between first and last observation for this instrument
            first, last = min(present), max(present)
            expected = {d for d in trading_set if first <= d <= last}
            missing = sorted(expected - present)
            # Ignore tiny gaps; warn when material share missing
            if len(expected) >= 10 and len(missing) / len(expected) >= 0.15:
                _issue(
                    session,
                    counts,
                    context,
                    instrument_id=instrument.id,
                    issue_type="missing_trading_days_in_range",
                    severity="warning",
                    timestamp=datetime.combine(last, datetime.min.time(), UTC),
                    message=(
                        f"{instrument.symbol}: missing {len(missing)}/{len(expected)} "
                        "trading days inside observed range"
                    ),
                    details={
                        "missing_count": len(missing),
                        "expected_count": len(expected),
                        "sample_missing": [d.isoformat() for d in missing[:5]],
                        "mode": "historical",
                    },
                )

    # Explicitly do NOT emit missing_recent_data in historical mode
    session.flush()
    return {
        "mode": "historical",
        "date_from": context.date_from.isoformat(),
        "date_to": context.date_to.isoformat(),
        "info": counts["info"],
        "warnings": counts["warning"],
        "errors": counts["error"],
        "by_type": counts["by_type"],
        "checked_at": datetime.now(UTC).isoformat(),
    }


def _run_operational(session: Session, context: DataQualityContext) -> dict[str, Any]:
    counts = {"info": 0, "warning": 0, "error": 0, "by_type": {}}
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=context.stale_after_days)

    instruments = list(
        session.scalars(
            select(Instrument)
            .options(selectinload(Instrument.sources))
            .where(Instrument.is_active.is_(True))
        )
        .unique()
        .all()
    )
    split_dates = load_split_effective_dates(session)

    for instrument in instruments:
        if not instrument.sources:
            _issue(
                session,
                counts,
                context,
                instrument_id=instrument.id,
                issue_type="missing_instrument_mapping",
                severity="error",
                timestamp=None,
                message=f"Instrument {instrument.symbol} has no source mapping",
                details={"symbol": instrument.symbol},
            )
            continue
        if not any(s.source == "MOEX" for s in instrument.sources):
            continue

        last_ts = session.scalar(
            select(func.max(Candle.timestamp)).where(
                Candle.instrument_id == instrument.id,
                Candle.timeframe == "1d",
            )
        )
        if last_ts is None:
            _issue(
                session,
                counts,
                context,
                instrument_id=instrument.id,
                issue_type="missing_recent_data",
                severity="warning",
                timestamp=None,
                message=f"No candles at all for {instrument.symbol}",
                details={"symbol": instrument.symbol, "mode": "operational"},
            )
            continue

        # Spot-check latest bars for OHLC / volume / jump
        latest = list(
            session.scalars(
                select(Candle)
                .where(Candle.instrument_id == instrument.id, Candle.timeframe == "1d")
                .order_by(Candle.timestamp.desc())
                .limit(5)
            )
        )
        for candle in latest:
            if candle.high < candle.low or candle.close > candle.high or candle.close < candle.low:
                _issue(
                    session,
                    counts,
                    context,
                    instrument_id=instrument.id,
                    issue_type="invalid_ohlc",
                    severity="error",
                    timestamp=candle.timestamp,
                    message="Invalid OHLC relationship",
                    details={
                        "open": str(candle.open),
                        "high": str(candle.high),
                        "low": str(candle.low),
                        "close": str(candle.close),
                    },
                )
            if candle.volume is not None and candle.volume < 0:
                _issue(
                    session,
                    counts,
                    context,
                    instrument_id=instrument.id,
                    issue_type="negative_volume",
                    severity="error",
                    timestamp=candle.timestamp,
                    message="Negative volume",
                    details={"volume": str(candle.volume)},
                )
        if len(latest) >= 2:
            newer, older = latest[0], latest[1]
            if older.close != 0:
                change = abs((newer.close - older.close) / older.close)
                if change >= Decimal("0.25"):
                    _issue(
                        session,
                        counts,
                        context,
                        instrument_id=instrument.id,
                        issue_type="abnormal_price_jump",
                        severity="warning",
                        timestamp=newer.timestamp,
                        message=f"Close changed by {float(change):.1%} vs previous bar",
                        details=_jump_details(
                            older,
                            newer,
                            explained_by_split=(instrument.id, newer.timestamp.date()) in split_dates,
                        ),
                    )

        if last_ts < cutoff:
            lag_days = (now.date() - last_ts.date()).days
            _issue(
                session,
                counts,
                context,
                instrument_id=instrument.id,
                issue_type="missing_recent_data",
                severity="warning",
                timestamp=last_ts,
                message=(
                    f"Last candle for {instrument.symbol} is {lag_days} days old "
                    f"(threshold {context.stale_after_days}d)"
                ),
                details={
                    "last_timestamp": last_ts.isoformat(),
                    "lag_days": lag_days,
                    "mode": "operational",
                },
            )
            _issue(
                session,
                counts,
                context,
                instrument_id=instrument.id,
                issue_type="source_lag",
                severity="info",
                timestamp=last_ts,
                message=f"Source lag detected for {instrument.symbol}",
                details={"lag_days": lag_days, "mode": "operational"},
            )

    session.flush()
    return {
        "mode": "operational",
        "info": counts["info"],
        "warnings": counts["warning"],
        "errors": counts["error"],
        "by_type": counts["by_type"],
        "checked_at": now.isoformat(),
    }


def load_split_effective_dates(session: Session) -> set[tuple[int, date]]:
    rows = session.execute(
        select(CorporateAction.instrument_id, CorporateAction.event_date).where(
            CorporateAction.event_type == EVENT_TYPE_SPLIT
        )
    ).all()
    return {(instrument_id, event_date) for instrument_id, event_date in rows}


def split_explains_jump(session: Session, instrument_id: int, jump_date: date) -> bool:
    """True when a persisted SPLIT effective_date matches the jump date for the instrument."""
    return (instrument_id, jump_date) in load_split_effective_dates(session)


def annotate_jumps_explained_by_splits(session: Session) -> int:
    """Annotate existing abnormal_price_jump rows. Does not delete the jump or rewrite candles."""
    split_dates = load_split_effective_dates(session)
    if not split_dates:
        return 0
    issues = list(
        session.scalars(
            select(DataQualityIssue).where(DataQualityIssue.issue_type == "abnormal_price_jump")
        )
    )
    annotated = 0
    for issue in issues:
        if issue.instrument_id is None or issue.timestamp is None:
            continue
        if (issue.instrument_id, issue.timestamp.date()) not in split_dates:
            continue
        details = dict(issue.details or {})
        if details.get("explained_by_corporate_action") == EVENT_TYPE_SPLIT:
            continue
        details["explained_by_corporate_action"] = EVENT_TYPE_SPLIT
        issue.details = details
        flag_modified(issue, "details")
        annotated += 1
    if annotated:
        session.flush()
    return annotated


def _jump_details(older: Candle, newer: Candle, *, explained_by_split: bool) -> dict[str, Any]:
    details: dict[str, Any] = {"from": str(older.close), "to": str(newer.close)}
    if explained_by_split:
        details["explained_by_corporate_action"] = EVENT_TYPE_SPLIT
    return details


def _issue(
    session: Session,
    counts: dict[str, Any],
    context: DataQualityContext,
    *,
    instrument_id: int | None,
    issue_type: str,
    severity: str,
    timestamp: datetime | None,
    message: str,
    details: dict[str, Any],
) -> None:
    counts[severity] = int(counts.get(severity, 0)) + 1
    by_type: dict[str, int] = counts["by_type"]
    by_type[issue_type] = by_type.get(issue_type, 0) + 1
    session.add(
        DataQualityIssue(
            instrument_id=instrument_id,
            batch_id=context.batch_id,
            issue_type=issue_type,
            severity=severity,
            timestamp=timestamp,
            message=message,
            details={**details, "dq_mode": context.mode},
        )
    )
