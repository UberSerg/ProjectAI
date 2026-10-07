"""PIT observation loaders for macro snapshot (market.series_values + market.candles)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, cast, desc, func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument, Series, SeriesValue
from app.modules.intelligence.macro.constants import (
    BREADTH_EQUITY_LOOKBACK,
    BREADTH_MIN_NAMES,
    INDEX_IMOEX,
    INDEX_RGBI,
    KNOWN_AT_QUALITY,
    LIMITATION_BREADTH_THIN,
    LIMITATION_FX_PIT,
    LIMITATION_KEY_RATE_PIT,
    LIMITATION_NO_SHORT_LONG,
    LIMITATION_NO_YIELD_CURVE,
    LIMITATION_RGBI_PROXY,
    POLICY_VERSION,
    RATE_CHANGE_LOOKBACK_DAYS,
    SERIES_KEY_RATE,
    SERIES_RUONIA,
    SERIES_USD_RUB,
    SNAPSHOT_BUILDER,
    TIMEFRAME_DAILY,
    WINDOW_FX_20D,
    WINDOW_RETURN_20D,
    WINDOW_RETURN_60D,
    WINDOW_VOL_20D,
)
from app.modules.intelligence.macro.metrics import (
    breadth_advance_share,
    last_nonzero_change,
    pct_change_from_levels,
    realized_vol_log,
    series_level_change,
    simple_return,
)


def load_series_points(
    session: Session,
    code: str,
    as_of: date,
) -> list[tuple[date, float]]:
    """Series values with observation date <= as_of (PIT)."""
    rows = session.execute(
        select(SeriesValue.timestamp, SeriesValue.value)
        .join(Series, Series.id == SeriesValue.series_id)
        .where(
            Series.code == code,
            cast(SeriesValue.timestamp, Date) <= as_of,
        )
        .order_by(SeriesValue.timestamp)
    ).all()
    return [(ts.date() if isinstance(ts, datetime) else ts, float(val)) for ts, val in rows]


def load_daily_closes(
    session: Session,
    symbol: str,
    as_of: date,
    *,
    limit: int,
) -> list[tuple[date, float]]:
    """Most recent ``limit`` daily closes with candle date <= as_of."""
    inst = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    if inst is None:
        return []
    rows = session.execute(
        select(Candle.timestamp, Candle.close)
        .where(
            Candle.instrument_id == inst.id,
            Candle.timeframe == TIMEFRAME_DAILY,
            cast(Candle.timestamp, Date) <= as_of,
        )
        .order_by(desc(Candle.timestamp))
        .limit(limit)
    ).all()
    points = [(ts.date() if isinstance(ts, datetime) else ts, float(close)) for ts, close in rows]
    points.reverse()
    return points


def _equity_ids_with_history(session: Session, as_of: date, need_bars: int) -> list[int]:
    """Equities that have at least ``need_bars`` daily closes <= as_of."""
    rows = session.execute(
        select(Candle.instrument_id)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(
            Instrument.asset_class == "equity",
            Candle.timeframe == TIMEFRAME_DAILY,
            cast(Candle.timestamp, Date) <= as_of,
        )
        .group_by(Candle.instrument_id)
        .having(func.count(Candle.id) >= need_bars)
    ).all()
    return [int(r[0]) for r in rows]


def compute_breadth(
    session: Session,
    as_of: date,
) -> tuple[dict[str, Any] | None, list[str]]:
    limitations: list[str] = [LIMITATION_BREADTH_THIN]
    need = BREADTH_EQUITY_LOOKBACK
    equity_ids = _equity_ids_with_history(session, as_of, need)
    returns: list[float | None] = []
    for iid in equity_ids:
        rows = session.execute(
            select(Candle.close)
            .where(
                Candle.instrument_id == iid,
                Candle.timeframe == TIMEFRAME_DAILY,
                cast(Candle.timestamp, Date) <= as_of,
            )
            .order_by(desc(Candle.timestamp))
            .limit(need)
        ).all()
        closes = [float(r[0]) for r in reversed(rows)]
        returns.append(simple_return(closes, WINDOW_RETURN_20D))
    share, n = breadth_advance_share(returns)
    if share is None or n < BREADTH_MIN_NAMES:
        return None, limitations
    return {
        "value": share,
        "names_used": n,
        "window": WINDOW_RETURN_20D,
        "definition": "share_of_equities_with_positive_return_20d",
        "as_of": as_of.isoformat(),
        "known_at": as_of.isoformat(),
        "known_at_quality": KNOWN_AT_QUALITY,
    }, limitations


def assemble_observations(
    session: Session,
    as_of: date,
    *,
    include_breadth: bool = True,
) -> tuple[dict[str, Any], list[str], list[str], date | None]:
    """Build observation dict + limitations + sources + max known_at date."""
    observations: dict[str, Any] = {
        "builder": SNAPSHOT_BUILDER,
        "policy_version": POLICY_VERSION,
    }
    limitations: list[str] = [
        LIMITATION_NO_YIELD_CURVE,
        LIMITATION_NO_SHORT_LONG,
        LIMITATION_KEY_RATE_PIT,
        LIMITATION_FX_PIT,
    ]
    sources: list[str] = []
    known_dates: list[date] = []

    # --- KEY_RATE ---
    key_points = load_series_points(session, SERIES_KEY_RATE, as_of)
    if key_points:
        sources.append(f"CBR:{SERIES_KEY_RATE}")
        d, v = key_points[-1]
        known_dates.append(d)
        observations["key_rate"] = {
            "value": v,
            "unit": "percent",
            "as_of": d.isoformat(),
            "known_at": d.isoformat(),
            "known_at_quality": KNOWN_AT_QUALITY,
            "series_code": SERIES_KEY_RATE,
        }
        chg, from_d, to_d = series_level_change(
            key_points, as_of=as_of, lookback_days=RATE_CHANGE_LOOKBACK_DAYS
        )
        last_chg, last_chg_d = last_nonzero_change(key_points)
        observations["key_rate_change_pp"] = {
            "value": chg,
            "from_date": from_d.isoformat() if from_d else None,
            "to_date": to_d.isoformat() if to_d else None,
            "lookback_days": RATE_CHANGE_LOOKBACK_DAYS,
            "last_nonzero_change_pp": last_chg,
            "last_nonzero_change_date": last_chg_d.isoformat() if last_chg_d else None,
            "known_at": (to_d or d).isoformat(),
            "known_at_quality": KNOWN_AT_QUALITY,
        }
    else:
        observations["key_rate"] = None
        observations["key_rate_change_pp"] = None

    # --- USD/RUB ---
    fx_points = load_series_points(session, SERIES_USD_RUB, as_of)
    if fx_points:
        sources.append(f"CBR:{SERIES_USD_RUB}")
        d, v = fx_points[-1]
        known_dates.append(d)
        fx_chg = pct_change_from_levels(fx_points, WINDOW_FX_20D)
        observations["usd_rub"] = {
            "value": v,
            "unit": "RUB_per_USD",
            "as_of": d.isoformat(),
            "known_at": d.isoformat(),
            "known_at_quality": KNOWN_AT_QUALITY,
            "series_code": SERIES_USD_RUB,
        }
        observations["usd_rub_pct_change_20d"] = {
            "value": fx_chg,
            "window_obs": WINDOW_FX_20D,
            "known_at": d.isoformat(),
            "known_at_quality": KNOWN_AT_QUALITY,
        }
    else:
        observations["usd_rub"] = None
        observations["usd_rub_pct_change_20d"] = None

    # RUONIA presence check (honest missing for spread)
    ruonia = load_series_points(session, SERIES_RUONIA, as_of)
    observations["ruonia"] = None
    if ruonia:
        sources.append(f"CBR:{SERIES_RUONIA}")
        d, v = ruonia[-1]
        known_dates.append(d)
        observations["ruonia"] = {
            "value": v,
            "unit": "percent",
            "as_of": d.isoformat(),
            "known_at": d.isoformat(),
            "known_at_quality": KNOWN_AT_QUALITY,
        }

    observations["gov_yield_curve"] = None
    observations["short_long_spread"] = None

    # --- IMOEX ---
    need_closes = max(WINDOW_RETURN_60D, WINDOW_VOL_20D) + 1
    imoex = load_daily_closes(session, INDEX_IMOEX, as_of, limit=need_closes + 5)
    if imoex:
        sources.append(f"MOEX:{INDEX_IMOEX}")
        closes = [c for _, c in imoex]
        last_d = imoex[-1][0]
        known_dates.append(last_d)
        observations["imoex_close"] = {
            "value": closes[-1],
            "as_of": last_d.isoformat(),
            "known_at": last_d.isoformat(),
            "known_at_quality": KNOWN_AT_QUALITY,
        }
        observations["imoex_return_20d"] = {
            "value": simple_return(closes, WINDOW_RETURN_20D),
            "window": WINDOW_RETURN_20D,
            "known_at": last_d.isoformat(),
        }
        observations["imoex_return_60d"] = {
            "value": simple_return(closes, WINDOW_RETURN_60D),
            "window": WINDOW_RETURN_60D,
            "known_at": last_d.isoformat(),
        }
        observations["imoex_realized_vol_20d"] = {
            "value": realized_vol_log(closes, WINDOW_VOL_20D, ddof=1),
            "window": WINDOW_VOL_20D,
            "unit": "daily_log_return_std",
            "ddof": 1,
            "known_at": last_d.isoformat(),
        }
    else:
        observations["imoex_close"] = None
        observations["imoex_return_20d"] = None
        observations["imoex_return_60d"] = None
        observations["imoex_realized_vol_20d"] = None

    # --- RGBI price proxy (not yield curve) ---
    rgbi = load_daily_closes(session, INDEX_RGBI, as_of, limit=WINDOW_RETURN_20D + 5)
    if rgbi:
        sources.append(f"MOEX:{INDEX_RGBI}")
        limitations.append(LIMITATION_RGBI_PROXY)
        closes = [c for _, c in rgbi]
        last_d = rgbi[-1][0]
        known_dates.append(last_d)
        observations["rgbi_return_20d"] = {
            "value": simple_return(closes, WINDOW_RETURN_20D),
            "window": WINDOW_RETURN_20D,
            "semantics": "gov_bond_PRICE_index_proxy_not_ytm",
            "known_at": last_d.isoformat(),
        }
    else:
        observations["rgbi_return_20d"] = None

    # --- Breadth ---
    if include_breadth:
        breadth, breadth_limits = compute_breadth(session, as_of)
        limitations.extend(breadth_limits)
        observations["breadth_advance_share_20d"] = breadth
        if breadth is not None:
            sources.append("MOEX:equity_breadth_local")
            known_dates.append(as_of)
    else:
        observations["breadth_advance_share_20d"] = None

    max_known = max(known_dates) if known_dates else None
    return observations, limitations, sources, max_known
