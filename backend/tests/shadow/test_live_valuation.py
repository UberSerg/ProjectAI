"""Live valuation: missing marks ≠ zero; FULL/PARTIAL/UNAVAILABLE semantics."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.domain.ports.intraday_market import (
    IntradayQuote,
    MarketSessionStatus,
    QuoteFreshness,
)
from app.modules.shadow.application.live_valuation import (
    EodMark,
    ValuationStatus,
    build_live_portfolio_snapshot,
)


def _quote(
    iid: int,
    *,
    last: float | None = 110.0,
    prev: float | None = 99.0,
    freshness: QuoteFreshness = QuoteFreshness.LIVE,
) -> IntradayQuote:
    return IntradayQuote(
        secid=f"T{iid}",
        board="TQBR",
        trading_date=date(2026, 9, 5),
        observed_at=datetime(2026, 9, 5, 11, 0, tzinfo=UTC),
        source_timestamp=None,
        market_status=MarketSessionStatus.OPEN,
        open_price=100.0,
        last_price=last,
        bid=None,
        ask=None,
        previous_close=prev,
        volume=1.0,
        source="MOEX_ISS",
        freshness=freshness,
        quality="ok",
        instrument_id=iid,
    )


def _nine_positions() -> dict[str, dict]:
    return {
        str(i): {"instrument_id": i, "ticker": f"T{i}", "quantity": 100.0} for i in range(1, 10)
    }


def test_live_nav_from_last() -> None:
    snap = build_live_portfolio_snapshot(
        portfolio_id=1,
        cash=50_000.0,
        positions={"1": {"instrument_id": 1, "ticker": "SBER", "quantity": 100.0}},
        quotes_by_instrument={1: _quote(1, last=110.0)},
        entry_by_instrument={1: 100.0},
    )
    assert snap.valuation_status == ValuationStatus.FULL
    assert snap.nav == 61_000.0
    assert snap.known_market_value == 11_000.0
    assert snap.unrealized_pnl == 1_000.0
    assert snap.position_marks[0].mark_source == "LAST"
    assert snap.quote_coverage == 1.0
    assert snap.nav_is_complete is True


def test_fallback_previous_close_is_stale() -> None:
    snap = build_live_portfolio_snapshot(
        portfolio_id=1,
        cash=0.0,
        positions={"1": {"instrument_id": 1, "ticker": "SBER", "quantity": 10.0}},
        quotes_by_instrument={1: _quote(1, last=None, prev=99.0, freshness=QuoteFreshness.MARKET_CLOSED)},
    )
    assert snap.known_market_value == 990.0
    assert snap.nav == 990.0
    assert snap.position_marks[0].mark_source == "PREVIOUS_CLOSE"
    assert snap.position_marks[0].freshness == QuoteFreshness.STALE.value


def test_partial_2_of_9_does_not_zero_fill_or_report_full_pnl() -> None:
    """Regression: 2/9 coverage must not invent −751k vs 1M initial capital."""
    quotes = {1: _quote(1, last=100.0), 2: _quote(2, last=200.0)}
    entries = {i: 100.0 for i in range(1, 10)}
    snap = build_live_portfolio_snapshot(
        portfolio_id=1,
        cash=48_896.0,
        positions=_nine_positions(),
        quotes_by_instrument=quotes,
        entry_by_instrument=entries,
        cost_basis_nav=1_000_000.0,
    )
    assert snap.valuation_status == ValuationStatus.PARTIAL
    assert snap.nav is None
    assert snap.unrealized_pnl is None
    assert snap.nav_is_complete is False
    assert snap.quote_coverage == pytest.approx(2 / 9)
    # Known MV = 100*100 + 200*100 = 30_000; zeros not added for 7 missing
    assert snap.known_market_value == 30_000.0
    assert snap.known_nav == 48_896.0 + 30_000.0
    assert len(snap.unpriced_positions) == 7
    for m in snap.position_marks:
        if not m.priced:
            assert m.market_value is None
    # Must NOT look like total P&L vs 1M
    fake_total_pnl = (snap.known_nav) - 1_000_000.0
    assert fake_total_pnl < -900_000  # what the bug produced — UI must not use this
    assert snap.unrealized_pnl is None


def test_zero_of_nine_unavailable() -> None:
    snap = build_live_portfolio_snapshot(
        portfolio_id=1,
        cash=100_000.0,
        positions=_nine_positions(),
        quotes_by_instrument={},
        entry_by_instrument={i: 100.0 for i in range(1, 10)},
        cost_basis_nav=1_000_000.0,
    )
    assert snap.valuation_status == ValuationStatus.UNAVAILABLE
    assert snap.nav is None
    assert snap.unrealized_pnl is None
    assert snap.known_market_value == 0.0
    assert len(snap.unpriced_positions) == 9


def test_nine_of_nine_full() -> None:
    quotes = {i: _quote(i, last=100.0) for i in range(1, 10)}
    snap = build_live_portfolio_snapshot(
        portfolio_id=1,
        cash=100_000.0,
        positions=_nine_positions(),
        quotes_by_instrument=quotes,
        entry_by_instrument={i: 100.0 for i in range(1, 10)},
        cost_basis_nav=1_000_000.0,
    )
    assert snap.valuation_status == ValuationStatus.FULL
    assert snap.nav == 100_000.0 + 9 * 10_000.0
    assert snap.unrealized_pnl == 0.0
    assert snap.quote_coverage == 1.0


def test_eod_fallback_when_intraday_missing() -> None:
    snap = build_live_portfolio_snapshot(
        portfolio_id=1,
        cash=0.0,
        positions={"1": {"instrument_id": 1, "ticker": "SBER", "quantity": 10.0}},
        quotes_by_instrument={},
        entry_by_instrument={1: 100.0},
        eod_marks_by_instrument={
            1: EodMark(price=95.0, as_of=datetime(2026, 9, 4, 18, 0, tzinfo=UTC), source="EOD"),
        },
    )
    assert snap.valuation_status == ValuationStatus.FULL
    assert snap.nav == 950.0
    assert snap.position_marks[0].mark_source == "EOD"
    assert snap.position_marks[0].freshness == QuoteFreshness.STALE.value
    assert any("eod_fallback" in w for w in snap.warnings)


def test_cash_only_portfolio_is_full() -> None:
    snap = build_live_portfolio_snapshot(
        portfolio_id=1,
        cash=500_000.0,
        positions={},
        quotes_by_instrument={},
        cost_basis_nav=500_000.0,
    )
    assert snap.valuation_status == ValuationStatus.FULL
    assert snap.nav == 500_000.0
    assert snap.unrealized_pnl == 0.0


def test_missing_cost_basis_still_marks_but_upnl_none() -> None:
    snap = build_live_portfolio_snapshot(
        portfolio_id=1,
        cash=0.0,
        positions={"1": {"instrument_id": 1, "ticker": "SBER", "quantity": 10.0}},
        quotes_by_instrument={1: _quote(1, last=110.0)},
        entry_by_instrument={},
    )
    assert snap.valuation_status == ValuationStatus.FULL
    assert snap.nav == 1_100.0
    assert snap.position_marks[0].unrealized_pnl is None
    assert snap.unrealized_pnl is None


def test_refresh_idempotent_for_full_book() -> None:
    kwargs = dict(
        portfolio_id=1,
        cash=10_000.0,
        positions={"1": {"instrument_id": 1, "ticker": "SBER", "quantity": 5.0}},
        quotes_by_instrument={1: _quote(1, last=200.0)},
        entry_by_instrument={1: 180.0},
    )
    a = build_live_portfolio_snapshot(**kwargs)
    b = build_live_portfolio_snapshot(**kwargs)
    assert a.nav == b.nav == 10_000.0 + 1_000.0
    assert a.unrealized_pnl == b.unrealized_pnl == 100.0

