"""Port abstraction smoke tests."""

from app.domain.ports.llm import LLMMessage
from app.infrastructure.llm.polza import PolzaProvider
from app.infrastructure.ml.portfolio_rules import RuleBasedPortfolioPolicy
from app.infrastructure.ml.technical_rules import RuleBasedTechnicalModel


def test_technical_model_port() -> None:
    model = RuleBasedTechnicalModel()
    signal = model.predict({"ticker": "SBER"})
    assert signal.ticker == "SBER"


def test_portfolio_policy_port() -> None:
    policy = RuleBasedPortfolioPolicy()
    assert policy.decide({}) == []


def test_polza_provider_is_not_live() -> None:
    provider = PolzaProvider()
    try:
        provider.complete([LLMMessage(role="user", content="ping")])
        raised = False
    except NotImplementedError:
        raised = True
    assert raised
