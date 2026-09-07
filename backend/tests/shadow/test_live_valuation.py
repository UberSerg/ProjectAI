"""Live valuation math from LAST / previous close."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.domain.ports.intraday_market import (
    IntradayQuote,
    MarketSessionStatus,
    QuoteFreshness,
)
from app.modules.shadow.application.live_valuation import build_live_portfolio_snapshot


def test_live_nav_from_last() -> None:
    quote = IntradayQuote(
        secid="SBER",
        board="TQBR",
        trading_date=date(2026, 9, 5),
        observed_at=datetime(2026, 9, 5, 11, 0, tzinfo=UTC),
        source_timestamp=None,
        market_status=MarketSessionStatus.OPEN,
        open_price=100.0,
        last_price=110.0,
        bid=None,
        ask=None,
        previous_close=99.0,
        volume=1.0,
        source="MOEX_ISS",
        freshness=QuoteFreshness.LIVE,
        quality="ok",
        instrument_id=1,
    )
    snap = build_live_portfolio_snapshot(
        portfolio_id=1,
        cash=50_000.0,
        positions={"1": {"instrument_id": 1, "ticker": "SBER", "quantity": 100.0}},
        quotes_by_instrument={1: quote},
        entry_by_instrument={1: 100.0},
    )
    assert snap.market_value == 11_000.0
    assert snap.nav == 61_000.0
    assert snap.invested_cost == 10_000.0
    assert snap.unrealized_pnl == 1_000.0
    assert snap.position_marks[0].entry_price == 100.0
    assert snap.position_marks[0].unrealized_pnl == 1_000.0
    assert snap.position_marks[0].mark_source == "LAST"
    assert snap.quote_coverage == 1.0


def test_fallback_previous_close_is_stale() -> None:
    quote = IntradayQuote(
        secid="SBER",
        board="TQBR",
        trading_date=date(2026, 9, 5),
        observed_at=datetime(2026, 9, 5, 11, 0, tzinfo=UTC),
        source_timestamp=None,
        market_status=MarketSessionStatus.CLOSED,
        open_price=None,
        last_price=None,
        bid=None,
        ask=None,
        previous_close=99.0,
        volume=None,
        source="MOEX_ISS",
        freshness=QuoteFreshness.MARKET_CLOSED,
        quality="closed",
        instrument_id=1,
    )
    snap = build_live_portfolio_snapshot(
        portfolio_id=1,
        cash=0.0,
        positions={"1": {"instrument_id": 1, "ticker": "SBER", "quantity": 10.0}},
        quotes_by_instrument={1: quote},
    )
    assert snap.market_value == 990.0
    assert snap.position_marks[0].mark_source == "PREVIOUS_CLOSE"
    assert snap.position_marks[0].freshness == QuoteFreshness.STALE.value
