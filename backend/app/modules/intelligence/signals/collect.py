"""Collect independent SignalOutputV1 adapters for one instrument.

Does not combine models. Missing session → None (builder emits UNKNOWN stubs).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.intelligence.contracts.signal import SignalOutputV1, unknown_signal
from app.modules.intelligence.signals.event import EventModelV1
from app.modules.intelligence.signals.fundamental import FundamentalModelV1
from app.modules.intelligence.signals.intraday import IntradayStructureModelV1
from app.modules.intelligence.signals.macro import MacroModelV1
from app.modules.intelligence.signals.technical import TechnicalModelV1


def _f(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


def _load_technical_features(session: Session, instrument_id: int, as_of: date) -> dict[str, Any] | None:
    from app.infrastructure.analytics.models import InstrumentFeatureDaily
    from app.infrastructure.technical.models import InstrumentTechnicalFeatureDaily

    basic = session.scalar(
        select(InstrumentFeatureDaily)
        .where(
            InstrumentFeatureDaily.instrument_id == instrument_id,
            InstrumentFeatureDaily.date <= as_of,
            InstrumentFeatureDaily.timeframe == "1d",
        )
        .order_by(InstrumentFeatureDaily.date.desc(), InstrumentFeatureDaily.id.desc())
        .limit(1)
    )
    tech = session.scalar(
        select(InstrumentTechnicalFeatureDaily)
        .where(
            InstrumentTechnicalFeatureDaily.instrument_id == instrument_id,
            InstrumentTechnicalFeatureDaily.date <= as_of,
            InstrumentTechnicalFeatureDaily.timeframe == "1d",
        )
        .order_by(
            InstrumentTechnicalFeatureDaily.date.desc(),
            InstrumentTechnicalFeatureDaily.id.desc(),
        )
        .limit(1)
    )
    if basic is None and tech is None:
        return None
    features: dict[str, Any] = {}
    quality: dict[str, Any] = {}
    is_valid = True
    if basic is not None:
        features.update(
            {
                "return_5d": _f(basic.return_5d),
                "return_20d": _f(basic.return_20d),
                "volatility_20d": _f(basic.volatility_20d),
                "drawdown_20d": _f(basic.drawdown_20d),
                "volume_zscore_20d": _f(basic.volume_zscore_20d),
            }
        )
        quality.update(dict(basic.quality_flags or {}))
        is_valid = is_valid and bool(basic.is_valid)
    if tech is not None:
        features.update(
            {
                "sma20_distance": _f(tech.sma20_distance),
                "ema20_distance": _f(tech.ema20_distance),
                "atr14_pct": _f(tech.atr14_pct),
                "rsi14": _f(tech.rsi14),
            }
        )
        quality.update(dict(tech.quality_flags or {}))
        is_valid = is_valid and bool(tech.is_valid)
    features["_quality_flags"] = quality
    features["_is_valid"] = is_valid
    return features


def _fundamental_payload(session: Session, instrument_id: int, as_of: date) -> dict[str, Any] | None:
    try:
        from app.modules.intelligence.fundamentals import build_fundamental_snapshot
    except ImportError:
        return None
    try:
        snap = build_fundamental_snapshot(session, instrument_id, as_of)
    except TypeError:
        return None
    if snap is None:
        return None
    return snap.to_dict() if hasattr(snap, "to_dict") else dict(snap)


def _intraday_payload(session: Session, instrument_id: int, as_of: date) -> dict[str, Any] | None:
    try:
        from app.modules.intelligence.intraday import build_intraday_snapshot
    except ImportError:
        return None
    from datetime import timedelta

    # Prefer completed READY session on/before as_of (today may be incomplete PARTIAL).
    partial: dict[str, Any] | None = None
    for delta in range(0, 8):
        day = as_of - timedelta(days=delta)
        if day.weekday() >= 5:
            continue
        snap = build_intraday_snapshot(instrument_id=instrument_id, as_of=day, session=session)
        if snap is None:
            continue
        payload = snap.to_dict() if hasattr(snap, "to_dict") else dict(snap)
        coverage = str(payload.get("coverage_status") or "").upper()
        if coverage == "READY":
            return payload
        if partial is None and coverage == "PARTIAL" and int(payload.get("bars_used") or 0) >= 9:
            partial = payload
    return partial


def _macro_payload(session: Session, as_of: date) -> dict[str, Any] | None:
    try:
        from app.modules.intelligence.macro import build_macro_snapshot
    except ImportError:
        return None
    snap = build_macro_snapshot(session, as_of)
    if snap is None:
        return None
    return snap.to_dict() if hasattr(snap, "to_dict") else dict(snap)


def collect_instrument_signals(
    *,
    instrument_id: int,
    as_of: date,
    session: Session | None = None,
) -> tuple[SignalOutputV1, ...] | None:
    """Return independent model outputs, or None when no DB session is available."""
    if session is None:
        return None

    tech_feats = _load_technical_features(session, instrument_id, as_of)
    fund = _fundamental_payload(session, instrument_id, as_of)
    intra = _intraday_payload(session, instrument_id, as_of)
    macro = _macro_payload(session, as_of)

    technical = TechnicalModelV1().evaluate(
        instrument_id=instrument_id,
        as_of=as_of,
        features=None if tech_feats is None else {k: v for k, v in tech_feats.items() if not k.startswith("_")},
        quality_flags=None if tech_feats is None else tech_feats.get("_quality_flags"),
        is_valid=None if tech_feats is None else tech_feats.get("_is_valid"),
    )
    fundamental = FundamentalModelV1().evaluate(
        instrument_id=instrument_id,
        as_of=as_of,
        snapshot=fund,
    )
    event = EventModelV1().evaluate(
        instrument_id=instrument_id,
        as_of=as_of,
        events=None,
    )
    intraday = IntradayStructureModelV1().evaluate(
        instrument_id=instrument_id,
        as_of=as_of,
        snapshot=intra,
    )
    if intraday.semantic != "INTRADAY":
        intraday = replace(intraday, semantic="INTRADAY")

    macro_sig = MacroModelV1().evaluate(
        instrument_id=instrument_id,
        as_of=as_of,
        snapshot=macro,
        sector_sensitivity_known=False,
    )
    from app.modules.intelligence.signals.cross_sectional_ml import CrossSectionalMLModelV1

    ml = CrossSectionalMLModelV1().evaluate(
        instrument_id=instrument_id,
        as_of=as_of,
        provenance=None,
    )
    bank = unknown_signal(
        model_id="BankModelV1",
        model_version="1",
        semantic="BANK_FI",
        instrument_id=instrument_id,
        as_of=as_of,
        reason="bank_universe_metrics_not_available",
        horizon="reporting_cycle",
    )
    news = unknown_signal(
        model_id="NewsModelV1",
        model_version="1",
        semantic="NEWS",
        instrument_id=instrument_id,
        as_of=as_of,
        reason="news_events_prospective_only_no_extracted_facts",
        horizon="event_window",
    )
    return (technical, fundamental, event, intraday, macro_sig, ml, bank, news)
