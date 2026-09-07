"""Fixed Income Enrichment V2 + research_fi_v1 pin + cashflow intelligence tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.modules.investment.domain.cashflow_timeline import (
    CashflowEventType,
    build_instrument_timeline,
    dedupe_redemption_amort,
    project_portfolio_cashflows,
    sum_horizon,
)
from app.modules.investment.domain.currency import resolve_nominal_currency
from app.modules.investment.domain.enrichment import EnrichmentKind, EnrichmentPriority
from app.modules.investment.domain.fixed_income import calculate_bond_purchase


def test_sur_faceunit_maps_to_rub() -> None:
    face = resolve_nominal_currency(face_unit="SUR")
    assert face.canonical == "RUB"


def test_dirty_price_uses_calculate_bond_purchase() -> None:
    purchase = calculate_bond_purchase(
        nominal=Decimal("1000"),
        clean_price_percent=Decimal("98.5"),
        accrued_interest_per_bond=Decimal("12.3"),
        lots=1,
        lot_size=1,
    )
    assert purchase.dirty_total == Decimal("985") + Decimal("12.3")


def test_dedupe_redemption_and_final_amort() -> None:
    rows = [
        (date(2030, 1, 15), "COUPON", Decimal("35"), "RUB"),
        (date(2030, 1, 15), "AMORTIZATION", Decimal("1000"), "RUB"),
        (date(2030, 1, 15), "REDEMPTION", Decimal("1000"), "RUB"),
    ]
    out = dedupe_redemption_amort(rows)
    types = [t for _, t, _, _ in out]
    assert CashflowEventType.BOND_REDEMPTION in types
    assert CashflowEventType.BOND_AMORTIZATION not in types
    assert CashflowEventType.BOND_COUPON in types


def test_portfolio_cashflow_horizons_no_offer_in_gross() -> None:
    events = build_instrument_timeline(
        instrument_id=1,
        symbol="SU26238",
        units=Decimal("10"),
        cashflows=[
            (date(2026, 10, 1), "COUPON", Decimal("35"), "RUB"),
            (date(2026, 11, 1), "OFFER", Decimal("100"), "RUB"),
            (date(2027, 1, 15), "REDEMPTION", Decimal("1000"), "RUB"),
            (date(2027, 1, 15), "AMORTIZATION", Decimal("1000"), "RUB"),
        ],
        as_of=date(2026, 9, 7),
    )
    proj = project_portfolio_cashflows(events=events, as_of=date(2026, 9, 7))
    h30 = proj["horizons"]["30d"]
    assert h30["coupon"] == pytest.approx(350.0)
    assert h30["gross"] == pytest.approx(350.0)
    # Offer not in gross
    assert all(e["event_type"] != "OFFER" or e["informational"] for e in proj["events"])
    h12 = proj["horizons"]["12m"]
    # Redemption once (amort dropped)
    assert h12["redemption"] == pytest.approx(10000.0)
    assert h12["amortization"] == pytest.approx(0.0)


def test_enrichment_priority_ordering() -> None:
    assert EnrichmentPriority.P0_PORTFOLIO < EnrichmentPriority.P1_NEW_BOND
    assert EnrichmentPriority.P1_NEW_BOND < EnrichmentPriority.P2_OFZ
    assert EnrichmentPriority.P2_OFZ < EnrichmentPriority.P3_OTHER_BOND
    assert EnrichmentPriority.P3_OTHER_BOND < EnrichmentPriority.P4_INACTIVE


def test_enqueue_improves_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.investment.application import enrichment_service as svc
    from app.modules.investment.domain.enrichment import EnrichmentStatus

    job = MagicMock()
    job.priority = int(EnrichmentPriority.P3_OTHER_BOND)
    job.status = EnrichmentStatus.PENDING.value
    session = MagicMock()
    session.scalar.return_value = job
    session.flush = MagicMock()

    out = svc.enqueue_enrichment(
        session, 42, EnrichmentKind.FIXED_INCOME_TERMS, EnrichmentPriority.P0_PORTFOLIO
    )
    assert out.priority == int(EnrichmentPriority.P0_PORTFOLIO)


def test_source_failure_preserves_terms_on_empty_bondization() -> None:
    from app.modules.investment.application.enrichment_service import enrich_single_bond
    from app.modules.investment.infrastructure.models import BondTerm

    instrument = MagicMock()
    instrument.id = 7
    instrument.symbol = "TESTBOND"
    instrument.primary_board = "TQOB"
    instrument.currency = "RUB"
    instrument.support_level = "PARTIAL"

    existing_term = MagicMock(spec=BondTerm)
    existing_term.nominal = Decimal("1000")
    existing_term.maturity_date = date(2030, 1, 1)
    existing_term.lot_size = 1
    existing_term.currency = "RUB"
    existing_term.raw_fields = {"keep": True}
    existing_term.support_status = "SUPPORTED"

    session = MagicMock()
    # First scalar: existing term; later calls return None/board sources
    session.scalar.side_effect = [existing_term, None, None]

    client = MagicMock()
    client.fetch_bondization.return_value = {"coupons": [], "amortizations": [], "offers": []}
    client.fetch_board_rows.return_value = []

    result = enrich_single_bond(session, instrument, client=client)
    assert result["status"] == "PARTIAL"
    assert result.get("preserved_terms") is True
    # BondTerm fields must not be cleared
    assert existing_term.nominal == Decimal("1000")
    assert existing_term.support_status == "SUPPORTED"


def test_horizon_sum_counts_events() -> None:
    events = build_instrument_timeline(
        instrument_id=1,
        symbol="X",
        units=Decimal("1"),
        cashflows=[
            (date(2026, 9, 20), "COUPON", Decimal("10"), "RUB"),
            (date(2026, 12, 20), "COUPON", Decimal("10"), "RUB"),
        ],
        as_of=date(2026, 9, 7),
    )
    h = sum_horizon(events, as_of=date(2026, 9, 7), days=30)
    assert h.event_count == 1
    assert h.gross == Decimal("10")
