"""Intraday candle ingest + PIT feature aggregation orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.ports.market_data import CandleBar
from app.infrastructure.market.models import Candle, Instrument, InstrumentSource
from app.infrastructure.market.moex_interval_candles import MoexIntervalCandlesProvider
from app.modules.intelligence.contracts.snapshots_domain import IntradayFeatureSnapshotV1
from app.modules.intelligence.intraday.application.features import (
    IntervalBar,
    bar_from_mapping,
    bars_for_as_of,
    compute_intraday_features,
)
from app.modules.intelligence.intraday.application.persist_candles import upsert_interval_candles
from app.modules.intelligence.intraday.application.persist_snapshots import (
    table_available,
    upsert_feature_snapshot,
)
from app.modules.intelligence.intraday.constants import PRIMARY_INTERVAL, SOURCE_MOEX
from app.modules.market.application.instrument_search import resolve_instrument_ref
from app.modules.market.application.operational_quote import resolve_board_secid

MSK = ZoneInfo("Europe/Moscow")


@dataclass
class IngestResult:
    symbol: str
    instrument_id: int
    board: str
    secid: str
    interval: str
    from_date: str
    till_date: str
    received: int = 0
    inserted: int = 0
    updated: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "instrument_id": self.instrument_id,
            "board": self.board,
            "secid": self.secid,
            "interval": self.interval,
            "from_date": self.from_date,
            "till_date": self.till_date,
            "received": self.received,
            "inserted": self.inserted,
            "updated": self.updated,
            "error": self.error,
        }


@dataclass
class AggregateResult:
    symbol: str
    snapshot: IntradayFeatureSnapshotV1 | None = None
    persisted: bool = False
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "persisted": self.persisted,
            "error": self.error,
            **self.extra,
        }


def resolve_symbols(session: Session, symbols: list[str]) -> list[tuple[str, Instrument]]:
    out: list[tuple[str, Instrument]] = []
    for raw in symbols:
        inst = resolve_instrument_ref(session, raw)
        if inst is None:
            raise ValueError(f"instrument not found: {raw}")
        out.append((str(inst.symbol).upper(), inst))
    return out


def latest_candle_date(
    session: Session,
    instrument_id: int,
    *,
    timeframe: str = PRIMARY_INTERVAL,
    source: str = SOURCE_MOEX,
) -> date | None:
    ts = session.scalar(
        select(func.max(Candle.timestamp)).where(
            Candle.instrument_id == instrument_id,
            Candle.timeframe == timeframe,
            Candle.source == source,
        )
    )
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(MSK).date()


def _rows_to_bars(rows: list[dict[str, Any]]) -> list[CandleBar]:
    bars: list[CandleBar] = []
    for row in rows:
        close = row.get("close")
        ts = row.get("timestamp")
        if close is None or ts is None:
            continue
        bars.append(
            CandleBar(
                timestamp=ts,
                open=row.get("open"),
                high=row.get("high"),
                low=row.get("low"),
                close=close,
                volume=row.get("volume"),
            )
        )
    return bars


def ingest_interval_candles(
    session: Session,
    symbols: list[str],
    *,
    from_date: date,
    till_date: date,
    interval: str = PRIMARY_INTERVAL,
    provider: MoexIntervalCandlesProvider | None = None,
    incremental: bool = False,
) -> list[IngestResult]:
    provider = provider or MoexIntervalCandlesProvider()
    results: list[IngestResult] = []
    for symbol, instrument in resolve_symbols(session, symbols):
        board, secid = resolve_board_secid(session, instrument)
        start = from_date
        if incremental:
            latest = latest_candle_date(session, int(instrument.id), timeframe=interval)
            if latest is not None:
                start = max(from_date, latest)
        result = IngestResult(
            symbol=symbol,
            instrument_id=int(instrument.id),
            board=board,
            secid=secid,
            interval=interval,
            from_date=start.isoformat(),
            till_date=till_date.isoformat(),
        )
        try:
            rows, _raw = provider.fetch_interval_candle_rows(
                secid,
                start,
                till_date,
                board=board,
                interval=interval,
            )
            written = upsert_interval_candles(
                session,
                int(instrument.id),
                _rows_to_bars(rows),
                source=SOURCE_MOEX,
                timeframe=interval,
            )
            result.received = written["received"]
            result.inserted = written["inserted"]
            result.updated = written["updated"]
        except Exception as exc:  # noqa: BLE001 — CLI surface
            result.error = f"{type(exc).__name__}: {exc}"
        results.append(result)
    return results


def _load_day_bars(
    session: Session,
    instrument_id: int,
    as_of: date,
    *,
    interval: str,
) -> list[IntervalBar]:
    start = datetime.combine(as_of, datetime.min.time(), tzinfo=MSK).astimezone(UTC)
    end = start + timedelta(days=1)
    candles = list(
        session.scalars(
            select(Candle)
            .where(
                Candle.instrument_id == instrument_id,
                Candle.timeframe == interval,
                Candle.source == SOURCE_MOEX,
                Candle.timestamp >= start,
                Candle.timestamp < end,
            )
            .order_by(Candle.timestamp)
        )
    )
    bars: list[IntervalBar] = []
    for c in candles:
        mapped = bar_from_mapping(
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "value": None,
            }
        )
        if mapped is not None:
            bars.append(mapped)
    return bars


def _prev_close(
    session: Session,
    instrument_id: int,
    as_of: date,
    *,
    interval: str,
) -> float | None:
    start = datetime.combine(as_of, datetime.min.time(), tzinfo=MSK).astimezone(UTC)
    # Prefer previous 60m close; fall back to daily candle.
    prev_intra = session.scalar(
        select(Candle)
        .where(
            Candle.instrument_id == instrument_id,
            Candle.timeframe == interval,
            Candle.source == SOURCE_MOEX,
            Candle.timestamp < start,
        )
        .order_by(Candle.timestamp.desc())
        .limit(1)
    )
    if prev_intra is not None:
        return float(prev_intra.close)
    prev_daily = session.scalar(
        select(Candle)
        .where(
            Candle.instrument_id == instrument_id,
            Candle.timeframe == "1d",
            Candle.timestamp < start,
        )
        .order_by(Candle.timestamp.desc())
        .limit(1)
    )
    if prev_daily is not None:
        return float(prev_daily.close)
    return None


def aggregate_as_of(
    session: Session,
    symbols: list[str],
    as_of: date,
    *,
    interval: str = PRIMARY_INTERVAL,
    persist: bool = True,
    now_utc: datetime | None = None,
) -> list[AggregateResult]:
    can_persist = persist and table_available(session)
    results: list[AggregateResult] = []
    for symbol, instrument in resolve_symbols(session, symbols):
        item = AggregateResult(symbol=symbol)
        try:
            day_bars = _load_day_bars(session, int(instrument.id), as_of, interval=interval)
            prev = _prev_close(session, int(instrument.id), as_of, interval=interval)
            snap = compute_intraday_features(
                instrument_id=int(instrument.id),
                as_of=as_of,
                day_bars=day_bars,
                prev_close=prev,
                interval=interval,
                now_utc=now_utc,
            )
            item.snapshot = snap
            if can_persist and snap.coverage_status != "MISSING":
                upsert_feature_snapshot(session, snap)
                item.persisted = True
            elif persist and not can_persist:
                item.extra["persist_skipped"] = "intelligence.intraday_feature_snapshots missing"
        except Exception as exc:  # noqa: BLE001
            item.error = f"{type(exc).__name__}: {exc}"
        results.append(item)
    return results


def aggregate_range(
    session: Session,
    symbols: list[str],
    from_date: date,
    till_date: date,
    *,
    interval: str = PRIMARY_INTERVAL,
    persist: bool = True,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    day = from_date
    while day <= till_date:
        # Skip weekends lightly; holidays still attempted (MISSING ok).
        if day.weekday() < 5:
            for item in aggregate_as_of(
                session, symbols, day, interval=interval, persist=persist
            ):
                payload = item.to_dict()
                payload["as_of"] = day.isoformat()
                out.append(payload)
        day += timedelta(days=1)
    return out


def smoke_live(
    session: Session,
    symbols: list[str],
    *,
    lookback_days: int = 5,
    interval: str = PRIMARY_INTERVAL,
    provider: MoexIntervalCandlesProvider | None = None,
    persist_candles: bool = True,
    persist_snapshots: bool = True,
) -> dict[str, Any]:
    """Bounded real MOEX fetch + feature aggregation proof."""
    provider = provider or MoexIntervalCandlesProvider()
    till = datetime.now(MSK).date()
    from_date = till - timedelta(days=lookback_days)
    ingest = ingest_interval_candles(
        session,
        symbols,
        from_date=from_date,
        till_date=till,
        interval=interval,
        provider=provider,
        incremental=False,
    )
    if not persist_candles:
        session.rollback()
        # Re-fetch rows in-memory path for features without relying on rolled-back rows.
        snapshots: list[dict[str, Any]] = []
        for symbol, instrument in resolve_symbols(session, symbols):
            board, secid = resolve_board_secid(session, instrument)
            rows, _ = provider.fetch_interval_candle_rows(
                secid, from_date, till, board=board, interval=interval
            )
            interval_bars = [b for r in rows if (b := bar_from_mapping(r)) is not None]
            # Choose latest date with bars.
            dates = sorted({b.begin_msk.date() for b in interval_bars}, reverse=True)
            as_of = dates[0] if dates else till
            day = bars_for_as_of(interval_bars, as_of)
            prev_dates = [d for d in dates if d < as_of]
            prev_close = None
            if prev_dates:
                prev_day = bars_for_as_of(interval_bars, prev_dates[0])
                if prev_day:
                    prev_close = prev_day[-1].close
            snap = compute_intraday_features(
                instrument_id=int(instrument.id),
                as_of=as_of,
                day_bars=day,
                prev_close=prev_close,
                interval=interval,
            )
            snapshots.append(
                {
                    "symbol": symbol,
                    "board": board,
                    "secid": secid,
                    "snapshot": snap.to_dict(),
                    "bars_fetched": len(interval_bars),
                }
            )
        return {
            "mode": "memory_only",
            "from_date": from_date.isoformat(),
            "till_date": till.isoformat(),
            "interval": interval,
            "ingest": [r.to_dict() for r in ingest],
            "snapshots": snapshots,
        }

    # Persist candles; aggregate latest weekday with data per symbol.
    session.flush()
    snapshots_out: list[dict[str, Any]] = []
    for symbol, instrument in resolve_symbols(session, symbols):
        board, secid = resolve_board_secid(session, instrument)
        latest = latest_candle_date(session, int(instrument.id), timeframe=interval)
        as_of = latest or till
        # Prefer a completed READY day; fall back to latest PARTIAL with bars.
        chosen = as_of
        snap = None
        partial_fallback: AggregateResult | None = None
        partial_day: date | None = None
        for delta in range(0, lookback_days + 1):
            candidate = as_of - timedelta(days=delta)
            if candidate.weekday() >= 5:
                continue
            agg = aggregate_as_of(
                session,
                [symbol],
                candidate,
                interval=interval,
                persist=persist_snapshots,
            )[0]
            if not agg.snapshot or agg.snapshot.bars_used <= 0:
                continue
            if agg.snapshot.coverage_status == "READY":
                snap = agg
                chosen = candidate
                break
            if partial_fallback is None:
                partial_fallback = agg
                partial_day = candidate
        if snap is None and partial_fallback is not None and partial_day is not None:
            snap = partial_fallback
            chosen = partial_day
        snapshots_out.append(
            {
                "symbol": symbol,
                "instrument_id": int(instrument.id),
                "board": board,
                "secid": secid,
                "as_of": chosen.isoformat(),
                "snapshot": snap.snapshot.to_dict() if snap and snap.snapshot else None,
                "persisted": bool(snap.persisted) if snap else False,
                "error": snap.error if snap else "no_bars",
            }
        )
    return {
        "mode": "db",
        "from_date": from_date.isoformat(),
        "till_date": till.isoformat(),
        "interval": interval,
        "ingest": [r.to_dict() for r in ingest],
        "snapshots": snapshots_out,
        "source": SOURCE_MOEX,
        "provider": "MoexIntervalCandlesProvider",
        "endpoint": "/iss/engines/stock/markets/shares/boards/{board}/securities/{secid}/candles.json",
    }


def mapping_summary(session: Session, symbols: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, instrument in resolve_symbols(session, symbols):
        board, secid = resolve_board_secid(session, instrument)
        sources = list(
            session.scalars(
                select(InstrumentSource).where(
                    InstrumentSource.instrument_id == int(instrument.id),
                    InstrumentSource.source.in_(("MOEX", "MOEX_ISS")),
                    InstrumentSource.valid_to.is_(None),
                )
            )
        )
        rows.append(
            {
                "symbol": symbol,
                "instrument_id": int(instrument.id),
                "board": board,
                "secid": secid,
                "mappings": [
                    {
                        "source": s.source,
                        "external_id": s.external_id,
                        "board": s.board,
                        "valid_from": s.valid_from.isoformat() if s.valid_from else None,
                        "valid_to": s.valid_to.isoformat() if s.valid_to else None,
                    }
                    for s in sources
                ],
            }
        )
    return rows
