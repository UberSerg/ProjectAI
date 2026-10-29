"""P0: historical Shadow NAV must not treat missing EOD closes as zero."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.modules.shadow.application.service import (
    REASON_MISSING_EOD_CLOSE,
    STATUS_NAV_BLOCKED,
    STATUS_NAV_OK,
    _mark_nav,
    process_shadow_market_day,
)
from app.modules.simulator.config import RISK_DD_GUARD_V1


def _portfolio(*, cash: float = 100_000.0, positions: dict | None = None, peak: float = 100_000.0):
    return SimpleNamespace(
        id=7,
        cash=cash,
        peak_nav=peak,
        risk_mode="normal",
        exposure_cap=1.0,
        positions=positions or {},
        last_processed_market_date=date(2026, 9, 1),
        activated_at=datetime(2026, 8, 1, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, tzinfo=UTC),
        status="ACTIVE",
        last_decision_id=None,
    )


def _spec(*, risk: str = "RISK_GUARDRAILS_V0"):
    return SimpleNamespace(
        risk_name=risk,
        dd_trigger=-0.20,
        dd_recovery=-0.10,
        dd_risk_off_gross=0.50,
        dd_normal_gross=1.0,
        fractional_shares=True,
        payload={},
    )


def test_full_marks_persist_nav_and_advance_watermark() -> None:
    day = date(2026, 9, 8)
    portfolio = _portfolio(
        positions={
            "1": {"instrument_id": 1, "ticker": "A", "quantity": 10},
            "2": {"instrument_id": 2, "ticker": "B", "quantity": 5},
        },
        peak=100_000.0,
    )
    session = MagicMock()
    session.scalar.return_value = None  # no existing ShadowNavDaily

    def _close(_session, iid, _day):  # noqa: ANN001
        return 100.0, {1: 100.0, 2: 200.0}[iid]

    with patch("app.modules.shadow.application.service._candle_open_close", side_effect=_close):
        out = _mark_nav(session, portfolio, _spec(), day, now=datetime(2026, 9, 8, 18, tzinfo=UTC))

    assert out["status"] == STATUS_NAV_OK
    assert out["nav"] == 100_000.0 + 10 * 100.0 + 5 * 200.0
    assert portfolio.last_processed_market_date == day
    assert portfolio.peak_nav == out["nav"]
    assert session.add.called


def test_partial_2_of_9_does_not_write_nav_or_move_watermark() -> None:
    day = date(2026, 9, 8)
    positions = {
        str(i): {"instrument_id": i, "ticker": f"T{i}", "quantity": 10.0} for i in range(1, 10)
    }
    portfolio = _portfolio(positions=positions, peak=1_000_000.0, cash=200_000.0)
    prior_peak = portfolio.peak_nav
    prior_wm = portfolio.last_processed_market_date
    session = MagicMock()

    def _close(_session, iid, _day):  # noqa: ANN001
        if iid in (1, 2):
            return 10.0, 10.0
        return None, None

    with patch("app.modules.shadow.application.service._candle_open_close", side_effect=_close):
        out = _mark_nav(
            session, portfolio, _spec(risk=RISK_DD_GUARD_V1), day, now=datetime(2026, 9, 8, 18, tzinfo=UTC)
        )

    assert out["status"] == STATUS_NAV_BLOCKED
    assert out["reason"] == REASON_MISSING_EOD_CLOSE
    assert set(out["missing_instrument_ids"]) == set(range(3, 10))
    assert out["nav"] is None
    assert portfolio.peak_nav == prior_peak
    assert portfolio.last_processed_market_date == prior_wm
    assert portfolio.risk_mode == "normal"
    assert not session.add.called


def test_zero_of_nine_blocked() -> None:
    day = date(2026, 9, 8)
    positions = {
        str(i): {"instrument_id": i, "ticker": f"T{i}", "quantity": 1.0} for i in range(1, 10)
    }
    portfolio = _portfolio(positions=positions)
    session = MagicMock()
    with patch(
        "app.modules.shadow.application.service._candle_open_close",
        return_value=(None, None),
    ):
        out = _mark_nav(session, portfolio, _spec(), day, now=datetime(2026, 9, 8, 18, tzinfo=UTC))
    assert out["status"] == STATUS_NAV_BLOCKED
    assert len(out["missing_instrument_ids"]) == 9


def test_cash_only_portfolio_marks_ok() -> None:
    day = date(2026, 9, 8)
    portfolio = _portfolio(positions={}, cash=500_000.0, peak=500_000.0)
    session = MagicMock()
    session.scalar.return_value = None
    with patch(
        "app.modules.shadow.application.service._candle_open_close",
        return_value=(None, None),
    ):
        out = _mark_nav(session, portfolio, _spec(), day, now=datetime(2026, 9, 8, 18, tzinfo=UTC))
    assert out["status"] == STATUS_NAV_OK
    assert out["nav"] == 500_000.0
    assert portfolio.last_processed_market_date == day


def test_process_day_rolls_back_when_mark_blocked() -> None:
    day = date(2026, 9, 8)
    portfolio = _portfolio(
        positions={"1": {"instrument_id": 1, "ticker": "A", "quantity": 10}},
        peak=100_000.0,
    )
    session = MagicMock()
    nested = MagicMock()
    session.begin_nested.return_value = nested

    with (
        patch("app.modules.shadow.application.service._apply_ca_for_day"),
        patch("app.modules.shadow.application.service._fill_pending_orders", return_value=2),
        patch(
            "app.modules.shadow.application.service._mark_nav",
            return_value={
                "status": STATUS_NAV_BLOCKED,
                "reason": REASON_MISSING_EOD_CLOSE,
                "missing_instrument_ids": [1],
            },
        ),
    ):
        out = process_shadow_market_day(
            session, portfolio, _spec(), day, now=datetime(2026, 9, 8, 18, tzinfo=UTC)
        )

    assert out["status"] == STATUS_NAV_BLOCKED
    assert out["fills"] == 0
    assert out["blocker"]["missing_instrument_ids"] == [1]
    nested.rollback.assert_called_once()
    nested.commit.assert_not_called()
