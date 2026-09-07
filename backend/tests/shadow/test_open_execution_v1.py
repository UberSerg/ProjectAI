"""SHADOW_NEXT_SESSION_OPEN_V1 eligibility + open fill service behaviour."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.domain.ports.intraday_market import (
    IntradayQuote,
    MarketSessionStatus,
    QuoteFreshness,
)
from app.modules.shadow.application.open_execution_service import (
    fill_pending_orders_with_session_open,
)
from app.modules.shadow.domain.open_execution import (
    REASON_ELIGIBLE,
    REASON_MIN_EXECUTION_DATE,
    REASON_OPEN_PRICE_NOT_AVAILABLE,
    REASON_ORDER_CREATED_AFTER_OPEN,
    REASON_QUOTE_STALE,
    can_fill_with_session_open,
    session_open_time_utc,
)


def test_friday_decision_monday_session_eligible() -> None:
    # Decision Friday; Monday session open after min_execution_date Saturday.
    created = datetime(2026, 9, 4, 13, 40, tzinfo=UTC)  # Fri
    observed = datetime(2026, 9, 7, 10, 15, tzinfo=UTC)  # Mon after open
    result = can_fill_with_session_open(
        order_created_at=created,
        min_execution_date=date(2026, 9, 5),
        session_date=date(2026, 9, 7),
        open_price=100.0,
        market_status=MarketSessionStatus.OPEN,
        quote_freshness=QuoteFreshness.LIVE,
        observed_at=observed,
    )
    assert result.eligible is True
    assert result.reason == REASON_ELIGIBLE
    assert result.delayed_observation is True


def test_closed_without_open_rejected() -> None:
    result = can_fill_with_session_open(
        order_created_at=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        min_execution_date=date(2026, 9, 5),
        session_date=date(2026, 9, 5),
        open_price=None,
        market_status=MarketSessionStatus.CLOSED,
        quote_freshness=QuoteFreshness.MARKET_CLOSED,
        observed_at=datetime(2026, 9, 5, 18, 0, tzinfo=UTC),
    )
    assert result.eligible is False


def test_no_open_price() -> None:
    result = can_fill_with_session_open(
        order_created_at=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        min_execution_date=date(2026, 9, 5),
        session_date=date(2026, 9, 5),
        open_price=None,
        market_status=MarketSessionStatus.OPEN,
        quote_freshness=QuoteFreshness.LIVE,
        observed_at=datetime(2026, 9, 5, 10, 30, tzinfo=UTC),
    )
    assert result.eligible is False
    assert result.reason == REASON_OPEN_PRICE_NOT_AVAILABLE


def test_late_poll_sets_delayed_flag() -> None:
    open_at = session_open_time_utc(date(2026, 9, 5))
    result = can_fill_with_session_open(
        order_created_at=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        min_execution_date=date(2026, 9, 5),
        session_date=date(2026, 9, 5),
        open_price=101.0,
        market_status=MarketSessionStatus.OPEN,
        quote_freshness=QuoteFreshness.DELAYED,
        observed_at=datetime(2026, 9, 5, 14, 0, tzinfo=UTC),
    )
    assert result.eligible is True
    assert result.delayed_observation is True
    assert result.session_open_time == open_at


def test_order_created_after_open_rejected() -> None:
    result = can_fill_with_session_open(
        order_created_at=datetime(2026, 9, 5, 8, 0, tzinfo=UTC),  # after 07:00 UTC
        min_execution_date=date(2026, 9, 5),
        session_date=date(2026, 9, 5),
        open_price=100.0,
        market_status=MarketSessionStatus.OPEN,
        quote_freshness=QuoteFreshness.LIVE,
        observed_at=datetime(2026, 9, 5, 10, 30, tzinfo=UTC),
    )
    assert result.eligible is False
    assert result.reason == REASON_ORDER_CREATED_AFTER_OPEN


def test_stale_quote_rejected() -> None:
    result = can_fill_with_session_open(
        order_created_at=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        min_execution_date=date(2026, 9, 5),
        session_date=date(2026, 9, 5),
        open_price=100.0,
        market_status=MarketSessionStatus.OPEN,
        quote_freshness=QuoteFreshness.STALE,
        observed_at=datetime(2026, 9, 5, 10, 30, tzinfo=UTC),
    )
    assert result.eligible is False
    assert result.reason == REASON_QUOTE_STALE


def test_min_execution_date_gate() -> None:
    result = can_fill_with_session_open(
        order_created_at=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        min_execution_date=date(2026, 9, 8),
        session_date=date(2026, 9, 5),
        open_price=100.0,
        market_status=MarketSessionStatus.OPEN,
        quote_freshness=QuoteFreshness.LIVE,
        observed_at=datetime(2026, 9, 5, 10, 30, tzinfo=UTC),
    )
    assert result.eligible is False
    assert result.reason == REASON_MIN_EXECUTION_DATE


def _quote(*, open_price: float | None = 100.0) -> IntradayQuote:
    return IntradayQuote(
        secid="SBER",
        board="TQBR",
        trading_date=date(2026, 9, 5),
        observed_at=datetime(2026, 9, 5, 10, 20, tzinfo=UTC),
        source_timestamp=datetime(2026, 9, 5, 10, 1, tzinfo=UTC),
        market_status=MarketSessionStatus.OPEN,
        open_price=open_price,
        last_price=105.0,  # must never be used as fill price
        bid=104.0,
        ask=105.0,
        previous_close=99.0,
        volume=1.0,
        source="MOEX_ISS",
        freshness=QuoteFreshness.LIVE,
        quality="ok",
        instrument_id=1,
    )


def _order(**overrides):  # noqa: ANN003
    base = dict(
        id=10,
        portfolio_id=1,
        instrument_id=1,
        ticker="SBER",
        side="BUY",
        target_weight=0.1,
        target_notional=10_000.0,
        quantity=100.0,
        reason="entry",
        status="PENDING",
        decision_at=datetime(2026, 9, 4, 13, 0, tzinfo=UTC),
        min_execution_date=date(2026, 9, 5),
        created_at=datetime(2026, 9, 4, 13, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 4, 13, 0, tzinfo=UTC),
        execution_date=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _portfolio(*, cash: float = 1_000_000.0) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        spec_id=1,
        cash=cash,
        positions={},
        status="WAITING_FOR_FUTURE_MARKET_OPEN",
        updated_at=datetime(2026, 9, 4, 13, 0, tzinfo=UTC),
    )


def _spec() -> SimpleNamespace:
    return SimpleNamespace(id=1, commission_bps=0.0, slippage_bps=0.0)


def test_fill_uses_open_not_last() -> None:
    order = _order()
    portfolio = _portfolio()
    spec = _spec()
    session = MagicMock()
    session.scalars.return_value = [order]
    session.scalar.side_effect = [order, None]  # lock order, no existing fill
    session.get.side_effect = lambda model, pk: (
        portfolio if "Spec" not in getattr(model, "__name__", "") else spec
    )

    # Fix get properly
    def _get(model, pk):  # noqa: ANN001
        name = getattr(model, "__name__", "")
        if name == "ShadowPortfolioSpec":
            return spec
        if name == "ShadowPortfolio":
            return portfolio
        return None

    session.get.side_effect = _get

    # scalar: first with_for_update → order; then existing fill check → None;
    # then remaining pending check → None
    session.scalar.side_effect = [order, None, None]

    result = fill_pending_orders_with_session_open(
        session,
        quotes=[_quote(open_price=100.0)],
        now=datetime(2026, 9, 5, 10, 20, tzinfo=UTC),
    )
    assert result.filled == 1
    assert session.add.called
    fill_row = session.add.call_args[0][0]
    assert float(fill_row.raw_open) == 100.0
    assert float(fill_row.fill_price) == 100.0
    assert fill_row.metadata_["execution_price_type"] == "OFFICIAL_SESSION_OPEN"
    assert fill_row.metadata_["delayed_observation"] is True
    assert order.status == "FILLED"


def test_duplicate_poll_skips_second_fill() -> None:
    order = _order(status="PENDING")
    portfolio = _portfolio()
    spec = _spec()
    session = MagicMock()
    session.scalars.return_value = [order]

    def _get(model, pk):  # noqa: ANN001
        name = getattr(model, "__name__", "")
        if name == "ShadowPortfolioSpec":
            return spec
        if name == "ShadowPortfolio":
            return portfolio
        return None

    session.get.side_effect = _get
    existing = SimpleNamespace(id=99, order_id=order.id)
    session.scalar.side_effect = [order, existing]

    result = fill_pending_orders_with_session_open(
        session,
        quotes=[_quote()],
        now=datetime(2026, 9, 5, 10, 20, tzinfo=UTC),
    )
    assert result.filled == 0
    assert result.skipped == 1
    assert not session.add.called


def test_insufficient_cash_leaves_pending() -> None:
    order = _order(quantity=1000.0)
    portfolio = _portfolio(cash=10.0)
    spec = _spec()
    session = MagicMock()
    session.scalars.return_value = [order]

    def _get(model, pk):  # noqa: ANN001
        name = getattr(model, "__name__", "")
        if name == "ShadowPortfolioSpec":
            return spec
        if name == "ShadowPortfolio":
            return portfolio
        return None

    session.get.side_effect = _get
    session.scalar.side_effect = [order, None]

    result = fill_pending_orders_with_session_open(
        session,
        quotes=[_quote(open_price=100.0)],
        now=datetime(2026, 9, 5, 10, 20, tzinfo=UTC),
    )
    assert result.filled == 0
    assert any(r.reason == "INSUFFICIENT_CASH" for r in (result.reasons or []))
    assert order.status == "PENDING"


def test_does_not_fill_when_open_missing_even_if_last_present() -> None:
    order = _order()
    portfolio = _portfolio()
    spec = _spec()
    session = MagicMock()
    session.scalars.return_value = [order]

    def _get(model, pk):  # noqa: ANN001
        name = getattr(model, "__name__", "")
        if name == "ShadowPortfolioSpec":
            return spec
        if name == "ShadowPortfolio":
            return portfolio
        return None

    session.get.side_effect = _get
    session.scalar.side_effect = [order, None]

    result = fill_pending_orders_with_session_open(
        session,
        quotes=[_quote(open_price=None)],
        now=datetime(2026, 9, 5, 10, 20, tzinfo=UTC),
    )
    assert result.filled == 0
    assert order.status == "PENDING"
