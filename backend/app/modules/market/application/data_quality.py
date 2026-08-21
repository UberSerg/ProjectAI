"""Basic market data quality checks for V1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, DataQualityIssue, Instrument


def run_data_quality_checks(session: Session, *, batch_id: int | None = None) -> dict[str, int]:
    warnings = 0
    errors = 0
    now = datetime.now(UTC)

    # Invalid OHLC / negative volume on recent candles
    recent = session.scalars(
        select(Candle).order_by(Candle.timestamp.desc()).limit(5000)
    ).all()
    for candle in recent:
        if candle.high < candle.low or candle.close > candle.high or candle.close < candle.low:
            errors += 1
            _add_issue(
                session,
                instrument_id=candle.instrument_id,
                batch_id=batch_id,
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
            errors += 1
            _add_issue(
                session,
                instrument_id=candle.instrument_id,
                batch_id=batch_id,
                issue_type="negative_volume",
                severity="error",
                timestamp=candle.timestamp,
                message="Negative volume",
                details={"volume": str(candle.volume)},
            )

    # Abnormal jump warning between consecutive closes per instrument (sample)
    instrument_ids = session.scalars(select(Instrument.id).where(Instrument.is_active.is_(True))).all()
    for instrument_id in instrument_ids:
        bars = list(
            session.scalars(
                select(Candle)
                .where(Candle.instrument_id == instrument_id, Candle.timeframe == "1d")
                .order_by(Candle.timestamp.desc())
                .limit(5)
            )
        )
        if len(bars) < 2:
            continue
        newer, older = bars[0], bars[1]
        if older.close == 0:
            continue
        change = abs((newer.close - older.close) / older.close)
        if change >= Decimal("0.25"):
            warnings += 1
            _add_issue(
                session,
                instrument_id=instrument_id,
                batch_id=batch_id,
                issue_type="abnormal_price_jump",
                severity="warning",
                timestamp=newer.timestamp,
                message=f"Close changed by {float(change):.1%} vs previous bar",
                details={"from": str(older.close), "to": str(newer.close)},
            )

    # Missing recent data: no candle in last 7 calendar days for equities with history
    cutoff = now - timedelta(days=7)
    for instrument_id in instrument_ids:
        last_ts = session.scalar(
            select(func.max(Candle.timestamp)).where(Candle.instrument_id == instrument_id)
        )
        if last_ts is None:
            continue
        if last_ts < cutoff:
            warnings += 1
            _add_issue(
                session,
                instrument_id=instrument_id,
                batch_id=batch_id,
                issue_type="missing_recent_data",
                severity="warning",
                timestamp=last_ts,
                message="No recent candle within 7 days (may include holidays)",
                details={"last_timestamp": last_ts.isoformat()},
            )

    session.flush()
    return {"warnings": warnings, "errors": errors, "checked_at": now.isoformat()}


def _add_issue(
    session: Session,
    *,
    instrument_id: int | None,
    batch_id: int | None,
    issue_type: str,
    severity: str,
    timestamp: datetime | None,
    message: str,
    details: dict[str, Any],
) -> None:
    session.add(
        DataQualityIssue(
            instrument_id=instrument_id,
            batch_id=batch_id,
            issue_type=issue_type,
            severity=severity,
            timestamp=timestamp,
            message=message,
            details=details,
        )
    )
