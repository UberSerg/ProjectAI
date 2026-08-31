"""Batch persistence for analytics features."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import InstrumentFeatureDaily, SeriesFeatureDaily
from app.modules.analytics.application.calculator import InstrumentFeatureRecord
from app.modules.analytics.application.series_calculator import SeriesFeatureRecord


def _dec(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def upsert_instrument_features(
    session: Session,
    *,
    instrument_id: int,
    feature_set_id: UUID,
    feature_version: int,
    records: list[InstrumentFeatureRecord],
    timeframe: str = "1d",
) -> int:
    if not records:
        return 0
    rows: list[dict[str, Any]] = []
    now = datetime.now()
    for rec in records:
        rows.append(
            {
                "instrument_id": instrument_id,
                "date": rec.date,
                "timeframe": timeframe,
                "feature_set_id": feature_set_id,
                "feature_version": feature_version,
                "close": _dec(rec.close),
                "volume": _dec(rec.volume),
                "return_1d": _dec(rec.return_1d),
                "return_2d": _dec(rec.return_2d),
                "return_3d": _dec(rec.return_3d),
                "return_5d": _dec(rec.return_5d),
                "return_10d": _dec(rec.return_10d),
                "return_20d": _dec(rec.return_20d),
                "log_return_1d": _dec(rec.log_return_1d),
                "volatility_5d": _dec(rec.volatility_5d),
                "volatility_20d": _dec(rec.volatility_20d),
                "drawdown_20d": _dec(rec.drawdown_20d),
                "volume_change_1d": _dec(rec.volume_change_1d),
                "volume_zscore_20d": _dec(rec.volume_zscore_20d),
                "has_sufficient_history": rec.has_sufficient_history,
                "is_valid": rec.is_valid,
                "quality_flags": rec.quality_flags,
                "calculated_at": now,
                "source_updated_at": rec.source_updated_at,
            }
        )
    stmt = insert(InstrumentFeatureDaily).values(rows)
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_analytics_instrument_features_daily",
            set_={
                "feature_version": stmt.excluded.feature_version,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "return_1d": stmt.excluded.return_1d,
                "return_2d": stmt.excluded.return_2d,
                "return_3d": stmt.excluded.return_3d,
                "return_5d": stmt.excluded.return_5d,
                "return_10d": stmt.excluded.return_10d,
                "return_20d": stmt.excluded.return_20d,
                "log_return_1d": stmt.excluded.log_return_1d,
                "volatility_5d": stmt.excluded.volatility_5d,
                "volatility_20d": stmt.excluded.volatility_20d,
                "drawdown_20d": stmt.excluded.drawdown_20d,
                "volume_change_1d": stmt.excluded.volume_change_1d,
                "volume_zscore_20d": stmt.excluded.volume_zscore_20d,
                "has_sufficient_history": stmt.excluded.has_sufficient_history,
                "is_valid": stmt.excluded.is_valid,
                "quality_flags": stmt.excluded.quality_flags,
                "calculated_at": stmt.excluded.calculated_at,
                "source_updated_at": stmt.excluded.source_updated_at,
            },
        )
    )
    return len(rows)


def upsert_series_features(
    session: Session,
    *,
    series_id: int,
    feature_set_id: UUID,
    records: list[SeriesFeatureRecord],
) -> int:
    if not records:
        return 0
    rows: list[dict[str, Any]] = []
    now = datetime.now()
    for rec in records:
        rows.append(
            {
                "series_id": series_id,
                "date": rec.date,
                "feature_set_id": feature_set_id,
                "value": _dec(rec.value),
                "previous_value": _dec(rec.previous_value),
                "absolute_change": _dec(rec.absolute_change),
                "pct_change": _dec(rec.pct_change),
                "days_since_change": rec.days_since_change,
                "is_valid": rec.is_valid,
                "quality_flags": rec.quality_flags,
                "calculated_at": now,
            }
        )
    stmt = insert(SeriesFeatureDaily).values(rows)
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_analytics_series_features_daily",
            set_={
                "value": stmt.excluded.value,
                "previous_value": stmt.excluded.previous_value,
                "absolute_change": stmt.excluded.absolute_change,
                "pct_change": stmt.excluded.pct_change,
                "days_since_change": stmt.excluded.days_since_change,
                "is_valid": stmt.excluded.is_valid,
                "quality_flags": stmt.excluded.quality_flags,
                "calculated_at": stmt.excluded.calculated_at,
            },
        )
    )
    return len(rows)


def count_feature_quality(session: Session, feature_set_id: UUID) -> dict[str, int]:
    from sqlalchemy import func, select

    valid = (
        session.scalar(
            select(func.count())
            .select_from(InstrumentFeatureDaily)
            .where(
                InstrumentFeatureDaily.feature_set_id == feature_set_id,
                InstrumentFeatureDaily.is_valid.is_(True),
            )
        )
        or 0
    )
    invalid = (
        session.scalar(
            select(func.count())
            .select_from(InstrumentFeatureDaily)
            .where(
                InstrumentFeatureDaily.feature_set_id == feature_set_id,
                InstrumentFeatureDaily.is_valid.is_(False),
            )
        )
        or 0
    )
    warnings = (
        session.scalar(
            select(func.count())
            .select_from(InstrumentFeatureDaily)
            .where(
                InstrumentFeatureDaily.feature_set_id == feature_set_id,
                InstrumentFeatureDaily.quality_flags.contains({"price_discontinuity": True}),
            )
        )
        or 0
    )
    return {"valid": int(valid), "invalid": int(invalid), "warnings": int(warnings)}
