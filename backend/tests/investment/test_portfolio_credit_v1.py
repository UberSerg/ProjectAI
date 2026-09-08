"""Portfolio credit intelligence — value-weighted math."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.modules.investment.application.portfolio_credit_service import (
    build_portfolio_credit_intelligence,
)
from app.modules.investment.domain.credit_intelligence import CreditAvailabilityStatus


def test_portfolio_credit_weights() -> None:
    ofz = SimpleNamespace(
        id=1, symbol="SU1", asset_class="bond", instrument_subtype="ofz_gov", name="OFZ"
    )
    corp = SimpleNamespace(
        id=2, symbol="CORP1", asset_class="bond", instrument_subtype="corporate_bond", name="Corp"
    )
    term_gov = SimpleNamespace(bond_type="Government")
    term_corp = SimpleNamespace(bond_type="Corporate")

    session = MagicMock()
    session.get.side_effect = lambda _model, key: {1: ofz, 2: corp}.get(key)
    session.scalar.side_effect = [term_gov, term_corp]

    def _credit(_s, *, instrument_id, symbol, bond_type, subtype=None):
        if bond_type == "Government":
            return {
                "availability_status": CreditAvailabilityStatus.GOVERNMENT_RUSSIAN_FEDERAL.value,
                "rating_raw": None,
                "agency_code": None,
            }
        return {
            "availability_status": CreditAvailabilityStatus.SOURCE_NOT_READY.value,
            "rating_raw": None,
            "agency_code": None,
        }

    with (
        patch(
            "app.modules.investment.application.portfolio_credit_service.resolve_instrument_credit",
            side_effect=_credit,
        ),
        patch(
            "app.modules.investment.application.portfolio_credit_service._issuer_key",
            side_effect=lambda _s, iid, sym: (f"iss-{iid}", f"Issuer {sym}"),
        ),
    ):
        result = build_portfolio_credit_intelligence(
            session,
            positions=[
                {"instrument_id": 1, "symbol": "SU1", "market_value": 600},
                {"instrument_id": 2, "symbol": "CORP1", "market_value": 400},
            ],
            nav=Decimal("1000"),
        )

    assert abs(result["government_weight"] - 0.6) < 1e-9
    assert abs(result["corporate_weight"] - 0.4) < 1e-9
    assert result["rated_corporate_weight"] == 0.0
    assert abs(result["credit_data_unavailable_weight"] - 0.4) < 1e-9
    assert abs(result["unrated_corporate_weight"] - 0.4) < 1e-9
    assert result["provider_verdict"] == "NOT_READY"
    assert result["advisory"] is True
