"""PIT MacroSnapshotV1 from existing CBR series + IMOEX daily candles."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Date, cast, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument, Series, SeriesValue
from app.modules.intelligence.contracts.snapshots_domain import MacroSnapshotV1
from app.modules.intelligence.macro.constants import (
    INDEX_IMOEX,
    KNOWN_AT_QUALITY,
    LIMITATION_FX_PIT,
    LIMITATION_KEY_RATE_PIT,
    LIMITATION_NO_SHORT_LONG,
    LIMITATION_NO_YIELD_CURVE,
    LIMITATION_RGBI_PROXY,
    SERIES_KEY_RATE,
    SERIES_USD_RUB,
    STATUS_NOT_AVAILABLE,
    STATUS_PARTIAL,
    STATUS_READY,
    STATUS_UNKNOWN,
    WINDOW_FX_20D,
    WINDOW_RETURN_20D,
    WINDOW_VOL_20D,
)
from app.modules.intelligence.macro.metrics import last_nonzero_change, realized_vol_log, simple_return
from app.modules.intelligence.macro.regimes import classify_regimes


def _series_points(session: Session, code: str, as_of: date) -> list[tuple[date, float]]:
    rows = session.execute(
        select(SeriesValue.timestamp, SeriesValue.value)
        .join(Series, Series.id == SeriesValue.series_id)
        .where(Series.code == code, cast(SeriesValue.timestamp, Date) <= as_of)
        .order_by(SeriesValue.timestamp)
    ).all()
    out: list[tuple[date, float]] = []
    for ts, value in rows:
        if value is None:
            continue
        d = ts.date() if hasattr(ts, "date") else ts
        out.append((d, float(value)))
    return out


def _imoex_closes(session: Session, as_of: date) -> list[float]:
    inst = session.scalar(select(Instrument).where(Instrument.symbol == INDEX_IMOEX).limit(1))
    if inst is None:
        return []
    rows = session.scalars(
        select(Candle)
        .where(
            Candle.instrument_id == int(inst.id),
            Candle.timeframe == "1d",
            cast(Candle.timestamp, Date) <= as_of,
        )
        .order_by(Candle.timestamp)
    ).all()
    return [float(c.close) for c in rows]


def _overall_market(regimes: dict[str, str]) -> str:
    trend = regimes.get("MARKET_TREND")
    vol = regimes.get("VOLATILITY")
    if trend == "risk-off" or vol == "stress":
        return "ADVERSE"
    if trend == "risk-on" and vol in {"calm", "elevated"}:
        return "SUPPORTIVE"
    if trend in {"neutral", "risk-on", "risk-off"}:
        return "NEUTRAL"
    return "UNKNOWN"


def build_macro_snapshot(
    *,
    as_of: date,
    session: Session | None = None,
) -> MacroSnapshotV1 | None:
    if session is None:
        return None

    limitations = [
        LIMITATION_NO_YIELD_CURVE,
        LIMITATION_NO_SHORT_LONG,
        LIMITATION_RGBI_PROXY,
        LIMITATION_KEY_RATE_PIT,
        LIMITATION_FX_PIT,
    ]
    key_points = _series_points(session, SERIES_KEY_RATE, as_of)
    fx_points = _series_points(session, SERIES_USD_RUB, as_of)
    closes = _imoex_closes(session, as_of)

    key_chg, key_chg_date = last_nonzero_change(key_points)
    fx_vals = [v for _, v in fx_points]
    fx_ret = simple_return(fx_vals, WINDOW_FX_20D) if fx_vals else None
    imoex_ret = simple_return(closes, WINDOW_RETURN_20D) if closes else None
    imoex_vol = realized_vol_log(closes, WINDOW_VOL_20D) if closes else None

    latest_key = key_points[-1] if key_points else None
    observations: dict[str, Any] = {
        "key_rate_level": {
            "value": latest_key[1] if latest_key else None,
            "as_of": latest_key[0].isoformat() if latest_key else None,
        },
        "key_rate_change_pp": {"value": key_chg, "as_of": key_chg_date.isoformat() if key_chg_date else None},
        "usd_rub_pct_change_20d": {"value": fx_ret},
        "imoex_return_20d": {"value": imoex_ret},
        "imoex_realized_vol_20d": {"value": imoex_vol},
        "known_at_quality": KNOWN_AT_QUALITY,
    }
    regimes = classify_regimes(observations)
    regimes.pop("policy_version", None)
    regimes["market"] = _overall_market(regimes)

    sources: list[str] = []
    if key_points:
        sources.append("CBR_KEY_RATE")
    if fx_points:
        sources.append("CBR_USD_RUB")
    if closes:
        sources.append("MOEX_IMOEX")

    if not sources:
        status = STATUS_NOT_AVAILABLE
    elif key_points and fx_points and closes:
        status = STATUS_READY
    elif key_points or fx_points or closes:
        status = STATUS_PARTIAL
    else:
        status = STATUS_UNKNOWN

    known = None
    for pts in (key_points, fx_points):
        if pts:
            known = pts[-1][0]
    return MacroSnapshotV1(
        as_of=as_of,
        known_at=known,
        status=status,
        observations=observations,
        regimes=regimes,
        limitations=tuple(limitations),
        sources=tuple(sources),
    )
