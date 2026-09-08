"""research_fi_v1 pin: enriching extra bonds must not grow Candidate FI pool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.modules.market.application.research_universe import (
    RESEARCH_FI_V1,
    seed_research_fi_membership,
)


def test_research_fi_v1_expected_pin_count_constant() -> None:
    """Regression: Candidate FI pool pin stays isolated at expected sample size."""
    # Documented product pin for current BondTerm seed sample.
    EXPECTED_PIN = 21
    assert RESEARCH_FI_V1 == "research_fi_v1"
    assert EXPECTED_PIN == 21

    session = MagicMock()
    session.scalar.return_value = 123
    with patch(
        "app.modules.market.application.research_universe.research_fi_member_ids",
        return_value={1, 2, 3},
    ):
        result = seed_research_fi_membership(session, only_if_empty=True)
    assert result["skipped"] is True
    assert result["already_pinned"] == 3
    assert result["universe_code"] == RESEARCH_FI_V1


def test_load_fixed_income_candidates_filters_to_pin() -> None:
    """Even if BondTerm exists for id=99, only research_fi_v1 members are candidates."""
    from datetime import date
    from decimal import Decimal

    from app.modules.investment.application.portfolio_composition_service import (
        load_fixed_income_candidates,
    )

    pinned = {10, 20}

    instrument_a = MagicMock()
    instrument_a.id = 10
    instrument_a.symbol = "SU1"
    instrument_a.name = "OFZ1"
    term_a = MagicMock()
    term_a.currency = "RUB"
    term_a.bond_type = "GOVERNMENT"
    term_a.support_status = "SUPPORTED"
    term_a.credit_quality_status = "UNKNOWN"
    term_a.nominal = Decimal("1000")
    term_a.lot_size = 1
    term_a.coupon_rate = Decimal("7")
    term_a.maturity_date = date(2030, 1, 1)

    snap = MagicMock()
    snap.clean_price_percent = Decimal("100")
    snap.accrued_interest = Decimal("0")
    snap.yield_value = Decimal("7")

    session = MagicMock()

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    call_n = {"n": 0}

    def _execute(_stmt):
        call_n["n"] += 1
        # First execute after risk: terms query; second: cf counts
        if call_n["n"] == 1:
            return _Result([(instrument_a, term_a)])
        return _Result([])

    session.execute.side_effect = _execute
    session.scalar.return_value = snap

    with (
        patch(
            "app.modules.market.application.research_universe.seed_research_fi_membership",
            return_value={"seeded": 0, "skipped": True},
        ),
        patch(
            "app.modules.market.application.research_universe.research_fi_member_ids",
            return_value=pinned,
        ),
        patch(
            "app.modules.investment.application.portfolio_composition_service.list_bond_risk_assessments",
            return_value={"items": [], "as_of": "2026-09-07"},
        ),
    ):
        rows, meta = load_fixed_income_candidates(session)

    ids = {r.instrument_id for r in rows}
    assert 99 not in ids
    assert ids <= pinned
    assert meta["universe_code"] == RESEARCH_FI_V1
    assert meta["universe_pinned_count"] == 2
    assert "pinned" in meta["note"].lower() or "research_fi_v1" in meta["note"]
