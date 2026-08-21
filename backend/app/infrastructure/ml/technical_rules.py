"""Rule-based technical model stub — replaceable via TechnicalModel port."""

from __future__ import annotations

from typing import Any

from app.domain.ports.technical import TechnicalModel, TechnicalSignal


class RuleBasedTechnicalModel(TechnicalModel):
    def predict(self, features: dict[str, Any]) -> TechnicalSignal:
        ticker = str(features.get("ticker", "UNKNOWN"))
        return TechnicalSignal(ticker=ticker, score=0.0, confidence=0.0, metadata={"impl": "rules"})
