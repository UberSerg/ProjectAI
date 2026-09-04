"""Market as-of selection and upstream readiness for Forward Signal V0."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import InstrumentFeatureDaily
from app.infrastructure.market.models import Candle, Instrument
from app.infrastructure.technical.models import InstrumentTechnicalFeatureDaily, TechnicalSignalDaily
from app.modules.analytics.application.resolve import resolve_feature_set
from app.modules.prediction.application.forward_config import (
    FORWARD_BASIC_FS_CODE,
    FORWARD_BASIC_FS_VERSION,
    FORWARD_COMPLETENESS_LOOKBACK_DAYS,
    FORWARD_COMPLETENESS_RATIO,
    FORWARD_TECH_FS_CODE,
    FORWARD_TECH_FS_VERSION,
    FORWARD_TECH_MODEL_CODE,
    FORWARD_TECH_MODEL_VERSION,
)


@dataclass(frozen=True, slots=True)
class CompletenessReport:
    as_of: date | None
    latest_raw_market_date: date | None
    expected_instruments: int
    available_instruments: int
    missing_instrument_ids: tuple[int, ...]
    ratio: float
    threshold: float
    complete: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "latest_raw_market_date": (
                self.latest_raw_market_date.isoformat() if self.latest_raw_market_date else None
            ),
            "expected_instruments": self.expected_instruments,
            "available_instruments": self.available_instruments,
            "missing_instrument_ids": list(self.missing_instrument_ids),
            "ratio": self.ratio,
            "threshold": self.threshold,
            "complete": self.complete,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class UpstreamReadiness:
    as_of: date
    analytics_ready: bool
    technical_ready: bool
    signals_ready: bool
    analytics_count: int
    technical_count: int
    signal_count: int
    ready: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "analytics_ready": self.analytics_ready,
            "technical_ready": self.technical_ready,
            "signals_ready": self.signals_ready,
            "analytics_count": self.analytics_count,
            "technical_count": self.technical_count,
            "signal_count": self.signal_count,
            "ready": self.ready,
            "reason": self.reason,
            "pins": {
                "basic_daily": f"v{FORWARD_BASIC_FS_VERSION}",
                "technical_daily": f"v{FORWARD_TECH_FS_VERSION}",
                "rules": f"v{FORWARD_TECH_MODEL_VERSION}",
            },
        }


def active_instruments(session: Session) -> list[Instrument]:
    return list(
        session.scalars(select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.id))
    )


def latest_raw_market_date(session: Session) -> date | None:
    raw = session.scalar(select(func.max(Candle.timestamp)).where(Candle.timeframe == "1d"))
    if raw is None:
        return None
    return raw.date() if hasattr(raw, "date") else raw


def select_latest_complete_as_of(
    session: Session,
    *,
    completeness_ratio: float = FORWARD_COMPLETENESS_RATIO,
    lookback_days: int = FORWARD_COMPLETENESS_LOOKBACK_DAYS,
) -> CompletenessReport:
    """Pick latest completed market date with cohort candle coverage >= threshold.

    Does not use system 'today' blindly. Walks back from max candle date.
    """
    latest = latest_raw_market_date(session)
    if latest is None:
        return CompletenessReport(
            as_of=None,
            latest_raw_market_date=None,
            expected_instruments=0,
            available_instruments=0,
            missing_instrument_ids=(),
            ratio=0.0,
            threshold=completeness_ratio,
            complete=False,
            reason="no_market_candles",
        )

    instruments = active_instruments(session)
    if not instruments:
        return CompletenessReport(
            as_of=None,
            latest_raw_market_date=latest,
            expected_instruments=0,
            available_instruments=0,
            missing_instrument_ids=(),
            ratio=0.0,
            threshold=completeness_ratio,
            complete=False,
            reason="no_active_instruments",
        )

    inst_ids = [i.id for i in instruments]
    # Collect recent candle dates per instrument
    lookback_from = latest - timedelta(days=lookback_days)
    rows = session.execute(
        select(Candle.instrument_id, func.date(Candle.timestamp))
        .where(
            Candle.timeframe == "1d",
            Candle.instrument_id.in_(inst_ids),
            Candle.timestamp >= lookback_from,
            Candle.timestamp <= latest,
        )
        .distinct()
    ).all()
    by_date: dict[date, set[int]] = {}
    instruments_with_recent: set[int] = set()
    for iid, d in rows:
        day = d if isinstance(d, date) else date.fromisoformat(str(d))
        by_date.setdefault(day, set()).add(int(iid))
        instruments_with_recent.add(int(iid))

    expected = instruments_with_recent or set(inst_ids)
    # Candidate dates: descending unique candle dates
    for candidate in sorted(by_date.keys(), reverse=True):
        available = by_date.get(candidate, set()) & expected
        ratio = (len(available) / len(expected)) if expected else 0.0
        missing = tuple(sorted(expected - available))
        if ratio + 1e-12 >= completeness_ratio:
            return CompletenessReport(
                as_of=candidate,
                latest_raw_market_date=latest,
                expected_instruments=len(expected),
                available_instruments=len(available),
                missing_instrument_ids=missing,
                ratio=ratio,
                threshold=completeness_ratio,
                complete=True,
                reason="ok",
            )

    # Incomplete at latest
    available = by_date.get(latest, set()) & expected
    ratio = (len(available) / len(expected)) if expected else 0.0
    return CompletenessReport(
        as_of=None,
        latest_raw_market_date=latest,
        expected_instruments=len(expected),
        available_instruments=len(available),
        missing_instrument_ids=tuple(sorted(expected - available)),
        ratio=ratio,
        threshold=completeness_ratio,
        complete=False,
        reason="incomplete_market_coverage",
    )


def check_upstream_readiness(session: Session, as_of: date) -> UpstreamReadiness:
    """Verify pinned Analytics V2 / Technical V2 / rules V2 rows exist for as_of.

    Relations are optional for eligibility; not required for readiness to publish.
    Requires at least one instrument with all three daily sources.
    """
    basic_fs = resolve_feature_set(session, FORWARD_BASIC_FS_CODE, FORWARD_BASIC_FS_VERSION)
    tech_fs = resolve_feature_set(session, FORWARD_TECH_FS_CODE, FORWARD_TECH_FS_VERSION)

    analytics_count = int(
        session.scalar(
            select(func.count()).select_from(InstrumentFeatureDaily).where(
                InstrumentFeatureDaily.feature_set_id == basic_fs.id,
                InstrumentFeatureDaily.date == as_of,
                InstrumentFeatureDaily.is_valid.is_(True),
            )
        )
        or 0
    )
    technical_count = int(
        session.scalar(
            select(func.count()).select_from(InstrumentTechnicalFeatureDaily).where(
                InstrumentTechnicalFeatureDaily.feature_set_id == tech_fs.id,
                InstrumentTechnicalFeatureDaily.date == as_of,
            )
        )
        or 0
    )
    signal_count = int(
        session.scalar(
            select(func.count()).select_from(TechnicalSignalDaily).where(
                TechnicalSignalDaily.model_code == FORWARD_TECH_MODEL_CODE,
                TechnicalSignalDaily.model_version == FORWARD_TECH_MODEL_VERSION,
                TechnicalSignalDaily.basic_feature_set_id == basic_fs.id,
                TechnicalSignalDaily.technical_feature_set_id == tech_fs.id,
                TechnicalSignalDaily.as_of_date == as_of,
            )
        )
        or 0
    )
    analytics_ready = analytics_count > 0
    technical_ready = technical_count > 0
    signals_ready = signal_count > 0
    ready = analytics_ready and technical_ready and signals_ready
    if not ready:
        missing = []
        if not analytics_ready:
            missing.append(f"basic_daily v{FORWARD_BASIC_FS_VERSION}")
        if not technical_ready:
            missing.append(f"technical_daily v{FORWARD_TECH_FS_VERSION}")
        if not signals_ready:
            missing.append(f"rules v{FORWARD_TECH_MODEL_VERSION}")
        reason = "upstream_incomplete:" + ",".join(missing)
    else:
        reason = "ok"
    return UpstreamReadiness(
        as_of=as_of,
        analytics_ready=analytics_ready,
        technical_ready=technical_ready,
        signals_ready=signals_ready,
        analytics_count=analytics_count,
        technical_count=technical_count,
        signal_count=signal_count,
        ready=ready,
        reason=reason,
    )
