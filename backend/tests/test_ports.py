"""Port abstraction and domain contract smoke tests."""

from app.domain.ports.llm import LLMMessage
from app.domain.ports.portfolio import PortfolioPolicyInput, PortfolioPolicyOutput
from app.domain.ports.technical import (
    SignalDirection,
    TechnicalModelInput,
    TechnicalModelOutput,
)
from app.infrastructure.llm.polza import PolzaProvider
from app.infrastructure.ml.portfolio_rules import RuleBasedPortfolioPolicy
from app.infrastructure.ml.technical_rules import RuleBasedTechnicalModel


def test_technical_model_contract() -> None:
    model = RuleBasedTechnicalModel()
    output = model.predict(TechnicalModelInput(ticker="SBER", features={"close": 100.0}))
    assert isinstance(output, TechnicalModelOutput)
    assert output.ticker == "SBER"
    assert output.direction is SignalDirection.NEUTRAL
    assert output.score == 0.0
    assert output.confidence == 0.0
    assert output.metadata["impl"] == "rules"


def test_portfolio_policy_contract() -> None:
    policy = RuleBasedPortfolioPolicy()
    signal = TechnicalModelOutput(
        ticker="SBER",
        score=0.0,
        confidence=0.0,
        direction=SignalDirection.NEUTRAL,
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
