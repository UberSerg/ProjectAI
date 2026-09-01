"""TechnicalSignalService — load PIT features, freeze input, call pure TechnicalModel."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain.ports.technical import (
    FeatureSetRef,
    TechnicalFeatureVector,
    TechnicalModel,
    TechnicalModelInput,
    TechnicalModelOutput,
    TechnicalQualityContext,
)
from app.infrastructure.analytics.models import InstrumentFeatureDaily
from app.infrastructure.technical.models import InstrumentTechnicalFeatureDaily


def _f(value: Decimal | float | None) -> float | None:
    if value is None:
        return None
    return float(value)


def merge_quality(
    basic: InstrumentFeatureDaily | None,
    technical: InstrumentTechnicalFeatureDaily | None,
) -> TechnicalQualityContext:
    flags: dict[str, Any] = {}
    if basic is not None:
        flags.update(basic.quality_flags or {})
    if technical is not None:
        flags.update(technical.quality_flags or {})
    critical = bool(flags.get("price_discontinuity") or flags.get("invalid_ohlc"))
    is_valid = True
    has_hist = True
    if basic is not None:
        is_valid = is_valid and bool(basic.is_valid)
        has_hist = has_hist and bool(basic.has_sufficient_history)
    if technical is not None:
        is_valid = is_valid and bool(technical.is_valid)
        has_hist = has_hist and bool(technical.has_sufficient_history)
    if critical:
        is_valid = False
    return TechnicalQualityContext(
        is_valid=is_valid,
        has_sufficient_history=has_hist,
        quality_flags=flags,
        critical=critical,
    )


def build_frozen_input(
    *,
    instrument_id: int,
    ticker: str,
    as_of_date: date,
    basic_ref: FeatureSetRef,
    technical_ref: FeatureSetRef,
    basic: InstrumentFeatureDaily | None,
    technical: InstrumentTechnicalFeatureDaily | None,
) -> TechnicalModelInput:
    return TechnicalModelInput(
        instrument_id=instrument_id,
        ticker=ticker,
        as_of_date=as_of_date,
        basic_feature_set_ref=basic_ref,
        technical_feature_set_ref=technical_ref,
        features=TechnicalFeatureVector(
            return_1d=_f(basic.return_1d) if basic else None,
            return_5d=_f(basic.return_5d) if basic else None,
            return_20d=_f(basic.return_20d) if basic else None,
            volatility_5d=_f(basic.volatility_5d) if basic else None,
            volatility_20d=_f(basic.volatility_20d) if basic else None,
            drawdown_20d=_f(basic.drawdown_20d) if basic else None,
            volume_change_1d=_f(basic.volume_change_1d) if basic else None,
            volume_zscore_20d=_f(basic.volume_zscore_20d) if basic else None,
            sma20_distance=_f(technical.sma20_distance) if technical else None,
            ema20_distance=_f(technical.ema20_distance) if technical else None,
            rsi14=_f(technical.rsi14) if technical else None,
            atr14_pct=_f(technical.atr14_pct) if technical else None,
        ),
        quality=merge_quality(basic, technical),
    )


class TechnicalSignalService:
    """Application orchestration: PIT load → frozen input → model.predict (no SQL inside model)."""

    def __init__(self, model: TechnicalModel) -> None:
        self.model = model

    def evaluate(
        self,
        *,
        instrument_id: int,
        ticker: str,
        as_of_date: date,
        basic_ref: FeatureSetRef,
        technical_ref: FeatureSetRef,
        basic: InstrumentFeatureDaily | None,
        technical: InstrumentTechnicalFeatureDaily | None,
    ) -> tuple[TechnicalModelInput, TechnicalModelOutput]:
        frozen = build_frozen_input(
            instrument_id=instrument_id,
            ticker=ticker,
            as_of_date=as_of_date,
            basic_ref=basic_ref,
            technical_ref=technical_ref,
            basic=basic,
            technical=technical,
        )
        return frozen, self.model.predict(frozen)


def feature_set_ref(feature_set_id: UUID, code: str, version: int) -> FeatureSetRef:
    return FeatureSetRef(code=code, version=version, id=feature_set_id)
