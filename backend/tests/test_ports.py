"""Port abstraction and domain contract smoke tests."""

from datetime import date
from uuid import uuid4

from app.domain.ports.llm import LLMMessage
from app.domain.ports.portfolio import PortfolioPolicyInput, PortfolioPolicyOutput
from app.domain.ports.technical import (
    FactorContributions,
    FeatureSetRef,
    SignalDirection,
    TechnicalFeatureVector,
    TechnicalModelInput,
    TechnicalModelOutput,
    TechnicalQualityContext,
)
from app.infrastructure.llm.polza import PolzaProvider
from app.infrastructure.ml.portfolio_rules import RuleBasedPortfolioPolicy
from app.infrastructure.ml.technical_rules import RuleBasedTechnicalModel


def _sample_input(**feature_overrides: float | None) -> TechnicalModelInput:
    feats = {
        "return_1d": 0.01,
        "return_5d": 0.08,
        "return_20d": 0.12,
        "volatility_5d": 0.02,
        "volatility_20d": 0.03,
        "drawdown_20d": -0.05,
        "volume_change_1d": 0.1,
        "volume_zscore_20d": 2.0,
        "sma20_distance": 0.04,
        "ema20_distance": 0.03,
        "rsi14": 65.0,
        "atr14_pct": 0.02,
    }
    feats.update(feature_overrides)
    return TechnicalModelInput(
        instrument_id=1,
        ticker="SBER",
        as_of_date=date(2024, 6, 1),
        basic_feature_set_ref=FeatureSetRef(code="basic_daily", version=1, id=uuid4()),
        technical_feature_set_ref=FeatureSetRef(code="technical_daily", version=1, id=uuid4()),
        features=TechnicalFeatureVector(**feats),
        quality=TechnicalQualityContext(),
    )


def test_technical_model_contract() -> None:
    model = RuleBasedTechnicalModel()
    output = model.predict(_sample_input())
    assert isinstance(output, TechnicalModelOutput)
    assert output.ticker == "SBER"
    assert output.direction is SignalDirection.BULLISH
    assert -1.0 <= output.score <= 1.0
    assert 0.0 <= output.confidence <= 1.0
    assert output.model_code == "rules"
    assert output.metadata["impl"] == "rules"


def test_portfolio_policy_contract() -> None:
    policy = RuleBasedPortfolioPolicy()
    signal = TechnicalModelOutput(
        instrument_id=1,
        ticker="SBER",
        as_of_date=date(2024, 6, 1),
        score=0.0,
        confidence=0.0,
        direction=SignalDirection.NEUTRAL,
        model_code="rules",
        model_version=1,
        basic_feature_set_ref=FeatureSetRef(code="basic_daily", version=1),
        technical_feature_set_ref=FeatureSetRef(code="technical_daily", version=1),
        factor_contributions=FactorContributions(),
    )
    result = policy.decide(PortfolioPolicyInput(signals=(signal,), account_id="virtual-1"))
    assert isinstance(result, PortfolioPolicyOutput)
    assert result.decisions == ()


def test_polza_provider_is_not_live() -> None:
    provider = PolzaProvider()
    try:
        provider.complete([LLMMessage(role="user", content="ping")])
        raised = False
    except NotImplementedError:
        raised = True
    assert raised
