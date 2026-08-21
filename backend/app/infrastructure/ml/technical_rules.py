"""Rule-based technical model stub — replaceable via TechnicalModel port."""

from __future__ import annotations

from app.domain.ports.technical import (
    SignalDirection,
    TechnicalModel,
    TechnicalModelInput,
    TechnicalModelOutput,
)


class RuleBasedTechnicalModel(TechnicalModel):
    def predict(self, model_input: TechnicalModelInput) -> TechnicalModelOutput:
        return TechnicalModelOutput(
            ticker=model_input.ticker,
            score=0.0,
            confidence=0.0,
            direction=SignalDirection.NEUTRAL,
            metadata={"impl": "rules"},
        )
