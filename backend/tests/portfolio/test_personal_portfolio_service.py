"""DB-backed Personal Portfolio journal tests (isolated is_test portfolio)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.infrastructure.db.session import core_session
from app.infrastructure.market.models import Instrument
from app.modules.portfolio.application.personal_portfolio_service import (
    PersonalPortfolioError,
    create_operation,
    get_or_create_test_portfolio,
    get_personal_summary,
    reconcile,
)
from app.modules.portfolio.domain.personal_ledger import money
from app.modules.portfolio.infrastructure.models import (
    ManualPortfolio,
    ManualPosition,
    PersonalOperation,
)

TEST_NAME = "TEST — Personal Portfolio V1 pytest"


@pytest.fixture()
def test_portfolio_id() -> int:
    with core_session() as session:
        portfolio = get_or_create_test_portfolio(session, name=TEST_NAME)
        session.execute(
            delete(PersonalOperation).where(PersonalOperation.portfolio_id == portfolio.id)
        )
        session.execute(delete(ManualPosition).where(ManualPosition.portfolio_id == portfolio.id))
        portfolio.cash_rub = Decimal("0")
        portfolio.total_contributed_rub = Decimal("0")
        portfolio.total_withdrawn_rub = Decimal("0")
        portfolio.realized_pnl_rub = Decimal("0")
        portfolio.version = 1
        session.flush()
        return int(portfolio.id)


def _instrument_id() -> int:
    with core_session() as session:
        inst = session.scalar(select(Instrument).where(Instrument.is_active.is_(True)).limit(1))
        if inst is None:
            pytest.skip("no instruments in DB")
        return int(inst.id)


def test_scenario_deposit_buy_fee_deposit_sell(test_portfolio_id: int) -> None:
    instrument_id = _instrument_id()
    with core_session() as session:
        portfolio = session.get(ManualPortfolio, test_portfolio_id)
        assert portfolio is not None

        create_operation(
            session,
            portfolio=portfolio,
            operation_type="DEPOSIT",
            occurred_at=date(2026, 9, 1),
            amount=Decimal("100000"),
            idempotency_key="t-dep-1",
        )
        create_operation(
            session,
            portfolio=portfolio,
            operation_type="BUY",
            occurred_at=date(2026, 9, 2),
            instrument_id=instrument_id,
            units=Decimal("10"),
            price=Decimal("100"),
            commission=Decimal("50"),
            non_standard_lot=True,
            idempotency_key="t-buy-1",
        )
        create_operation(
            session,
            portfolio=portfolio,
            operation_type="COMMISSION",
            occurred_at=date(2026, 9, 2),
            amount=Decimal("25"),
            idempotency_key="t-fee-1",
        )
        create_operation(
            session,
            portfolio=portfolio,
            operation_type="DEPOSIT",
            occurred_at=date(2026, 9, 3),
            amount=Decimal("30000"),
            idempotency_key="t-dep-2",
        )

        summary = get_personal_summary(session, portfolio, owner=True)
        assert money(summary["summary"]["contributed_rub"]) == money("130000")
        assert money(summary["summary"]["cash_rub"]) == money("128925")

        create_operation(
            session,
            portfolio=portfolio,
            operation_type="SELL",
            occurred_at=date(2026, 9, 4),
            instrument_id=instrument_id,
            units=Decimal("5"),
            price=Decimal("120"),
            commission=Decimal("10"),
            non_standard_lot=True,
            idempotency_key="t-sell-1",
        )
        # Duplicate click / retry
        create_operation(
            session,
            portfolio=portfolio,
            operation_type="SELL",
            occurred_at=date(2026, 9, 4),
            instrument_id=instrument_id,
            units=Decimal("5"),
            price=Decimal("120"),
            commission=Decimal("10"),
            non_standard_lot=True,
            idempotency_key="t-sell-1",
        )
        ops = session.scalars(
            select(PersonalOperation).where(
                PersonalOperation.portfolio_id == portfolio.id,
                PersonalOperation.idempotency_key == "t-sell-1",
            )
        ).all()
        assert len(ops) == 1

        # avg cost after buy = (1000+50)/10 = 105; sell 5 → realized (600-10)-525 = 65
        assert money(portfolio.realized_pnl_rub) == money("65")
        summary = get_personal_summary(session, portfolio, owner=True)
        assert summary["reconciliation"]["status"] == "OK"

        with pytest.raises(PersonalPortfolioError) as ei:
            create_operation(
                session,
                portfolio=portfolio,
                operation_type="SELL",
                occurred_at=date(2026, 9, 5),
                instrument_id=instrument_id,
                units=Decimal("999"),
                price=Decimal("1"),
                non_standard_lot=True,
                idempotency_key="t-sell-bad",
            )
        assert ei.value.code == "INSUFFICIENT_UNITS"
        assert reconcile(session, portfolio)["status"] == "OK"


def test_contribution_not_profit_when_only_cash(test_portfolio_id: int) -> None:
    with core_session() as session:
        portfolio = session.get(ManualPortfolio, test_portfolio_id)
        assert portfolio is not None
        create_operation(
            session,
            portfolio=portfolio,
            operation_type="DEPOSIT",
            occurred_at=date(2026, 9, 1),
            amount=Decimal("100000"),
            idempotency_key="cash-only-1",
        )
        create_operation(
            session,
            portfolio=portfolio,
            operation_type="DEPOSIT",
            occurred_at=date(2026, 9, 2),
            amount=Decimal("30000"),
            idempotency_key="cash-only-2",
        )
        summary = get_personal_summary(session, portfolio, owner=False)
        assert money(summary["summary"]["nav_rub"]) == money("130000")
        assert money(summary["summary"]["investment_pnl_rub"]) == money("0")
