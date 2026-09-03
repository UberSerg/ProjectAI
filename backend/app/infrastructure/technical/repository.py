"""Batch persistence for technical features and signals."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.technical.models import InstrumentTechnicalFeatureDaily, TechnicalSignalDaily
from app.modules.technical.application.calculator import TechnicalFeatureRecord

# psycopg bind limit is 65535; keep deep-history upserts in chunks.
_UPSERT_CHUNK = 1000


def _dec(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def upsert_technical_features(
    session: Session,
    *,
    instrument_id: int,
    feature_set_id: UUID,
    records: list[TechnicalFeatureRecord],
    source_basic_feature_ids: dict[Any, int] | None = None,
    timeframe: str = "1d",
) -> int:
    if not records:
        return 0
    source_basic_feature_ids = source_basic_feature_ids or {}
    now = datetime.now()
    rows: list[dict[str, Any]] = []
    for rec in records:
        rows.append(
            {
                "instrument_id": instrument_id,
                "date": rec.date,
                "timeframe": timeframe,
                "feature_set_id": feature_set_id,
                "sma20": _dec(rec.sma20),
                "sma20_distance": _dec(rec.sma20_distance),
                "ema20": _dec(rec.ema20),
                "ema20_distance": _dec(rec.ema20_distance),
                "rsi14": _dec(rec.rsi14),
                "atr14": _dec(rec.atr14),
                "atr14_pct": _dec(rec.atr14_pct),
                "has_sufficient_history": rec.has_sufficient_history,
                "is_valid": rec.is_valid,
                "quality_flags": rec.quality_flags,
                "source_basic_feature_id": source_basic_feature_ids.get(rec.date),
                "calculated_at": now,
            }
        )
    for offset in range(0, len(rows), _UPSERT_CHUNK):
        chunk = rows[offset : offset + _UPSERT_CHUNK]
        stmt = insert(InstrumentTechnicalFeatureDaily).values(chunk)
        session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_analytics_instrument_technical_features_daily",
                set_={
                    "sma20": stmt.excluded.sma20,
                    "sma20_distance": stmt.excluded.sma20_distance,
                    "ema20": stmt.excluded.ema20,
                    "ema20_distance": stmt.excluded.ema20_distance,
                    "rsi14": stmt.excluded.rsi14,
                    "atr14": stmt.excluded.atr14,
                    "atr14_pct": stmt.excluded.atr14_pct,
                    "has_sufficient_history": stmt.excluded.has_sufficient_history,
                    "is_valid": stmt.excluded.is_valid,
                    "quality_flags": stmt.excluded.quality_flags,
                    "source_basic_feature_id": stmt.excluded.source_basic_feature_id,
                    "calculated_at": stmt.excluded.calculated_at,
                },
            )
        )
    return len(rows)


def upsert_technical_signals(
    session: Session,
    *,
    rows: list[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    for offset in range(0, len(rows), _UPSERT_CHUNK):
        chunk = rows[offset : offset + _UPSERT_CHUNK]
        stmt = insert(TechnicalSignalDaily).values(chunk)
        session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_technical_signals_daily",
                set_={
                    "run_id": stmt.excluded.run_id,
                    "model_config_hash": stmt.excluded.model_config_hash,
                    "source_basic_feature_id": stmt.excluded.source_basic_feature_id,
                    "source_technical_feature_id": stmt.excluded.source_technical_feature_id,
                    "score": stmt.excluded.score,
                    "confidence": stmt.excluded.confidence,
                    "direction": stmt.excluded.direction,
                    "trend_contribution": stmt.excluded.trend_contribution,
                    "momentum_contribution": stmt.excluded.momentum_contribution,
                    "rsi_contribution": stmt.excluded.rsi_contribution,
                    "volume_contribution": stmt.excluded.volume_contribution,
                    "is_valid": stmt.excluded.is_valid,
                    "quality_flags": stmt.excluded.quality_flags,
                    "calculated_at": stmt.excluded.calculated_at,
                },
            )
        )
    return len(rows)
