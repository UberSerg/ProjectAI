"""Read-only bond detail endpoint tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.modules.investment.application.services import _bond_why_kraken, get_bond_detail


def test_bond_why_kraken_includes_eligibility() -> None:
    text = _bond_why_kraken({
        "support_status": "SUPPORTED",
        "investment_eligibility": "RESEARCH_ONLY",
        "credit_status": "UNKNOWN",
        "credit_safety_note": "note",
    })
    assert "RESEARCH_ONLY" in text
    assert "SUPPORTED" in text

@patch("app.modules.investment.application.services.list_bonds")
def test_get_bond_detail_none(mock_list) -> None:
    mock_list.return_value = []
    session = MagicMock()
    assert get_bond_detail(session, "NOSUCH") is None

@patch("app.modules.investment.application.services.list_bonds")
def test_get_bond_detail_with_cashflows(mock_list) -> None:
    mock_list.return_value = [{
        "instrument_id": 1,
        "symbol": "SU26230RMFS1",
        "support_status": "SUPPORTED",
        "investment_eligibility": "RESEARCH_ONLY",
        "credit_status": "UNKNOWN",
    }]
    cf = MagicMock()
    cf.cashflow_date = __import__("datetime").date(2026, 1, 1)
    cf.cashflow_type = "COUPON"
    cf.amount = 40
    cf.currency = "RUB"
    cf.source = "MOEX"
    session = MagicMock()
    session.scalars.return_value.all.return_value = [cf]
    detail = get_bond_detail(session, "su26230rmfs1")
    assert detail is not None
    assert detail["symbol"] == "SU26230RMFS1"
    assert detail["cashflows"][0]["cashflow_type"] == "COUPON"
    assert "why_kraken_ru" in detail
