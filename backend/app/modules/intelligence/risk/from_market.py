"""Build RiskAssessmentV1 from locally stored PIT market/technical facts."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.modules.intelligence.contracts.risk import RiskAssessmentV1
from app.modules.intelligence.risk.engine import assess_risk
from app.modules.intelligence.risk.inputs import RiskFactorInputs


def assess_instrument_risk(
    *,
    instrument_id: int,
    as_of: date,
    session: Session | None = None,
    extra: dict[str, Any] | None = None,
) -> RiskAssessmentV1 | None:
    if session is None:
        return None
    from app.modules.intelligence.signals.collect import _load_technical_features

    feats = _load_technical_features(session, instrument_id, as_of) or {}
    extra = extra or {}
    inputs = RiskFactorInputs(
        as_of=as_of,
        instrument_id=instrument_id,
        realized_vol=feats.get("volatility_20d") if isinstance(feats.get("volatility_20d"), int | float) else None,
        atr_pct=feats.get("atr14_pct") if isinstance(feats.get("atr14_pct"), int | float) else None,
        drawdown=feats.get("drawdown_20d") if isinstance(feats.get("drawdown_20d"), int | float) else None,
        market_regime=extra.get("market_regime"),
        material_adverse_event=bool(extra.get("material_adverse_event")),
        data_missing_critical=not feats,
    )
    return assess_risk(inputs)
