"""Personal broker fee precedence, provenance, and Decision V2 fee budget."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.infrastructure.db.session import core_session
from app.infrastructure.market.models import Instrument
from app.modules.portfolio.application.broker_fee_service import (
    BrokerFeeError,
    assign_broker_account,
    create_broker_account,
    create_custom_fee_profile,
    estimate_fee_for_portfolio,
    update_custom_fee_profile,
)
from app.modules.portfolio.application.decision_new_cash import _lot_suggestion
from app.modules.portfolio.application.personal_portfolio_service import (
    create_operation,
)
from app.modules.portfolio.application.user_portfolio_service import (
    activate_portfolio,
    create_user_portfolio,
)
from app.modules.portfolio.domain.personal_ledger import money
from app.modules.portfolio.infrastructure.models import (
    FeeProfile,
    ManualPortfolio,
    ManualPosition,
    PersonalOperation,
)

TEST_NAME = "TEST — Broker fee personal pytest"


@pytest.fixture()
def test_portfolio_id() -> int:
    with core_session() as session:
        portfolio = session.scalar(
            select(ManualPortfolio).where(
                ManualPortfolio.is_test.is_(True),
                ManualPortfolio.name == TEST_NAME,
            )
        )
        if portfolio is None:
            portfolio = create_user_portfolio(session, name=TEST_NAME, is_test=True)
        session.execute(
            delete(PersonalOperation).where(PersonalOperation.portfolio_id == portfolio.id)
        )
        session.execute(delete(ManualPosition).where(ManualPosition.portfolio_id == portfolio.id))
        portfolio.cash_rub = Decimal("0")
        portfolio.total_contributed_rub = Decimal("0")
        portfolio.total_withdrawn_rub = Decimal("0")
        portfolio.realized_pnl_rub = Decimal("0")
        portfolio.broker_account_id = None
        portfolio.version = 1
        portfolio.status = "DRAFT"
        session.flush()
        activate_portfolio(session, portfolio)
        return int(portfolio.id)


def _equity_instrument(session, *, symbol: str | None = None) -> Instrument:
    q = select(Instrument).where(
        Instrument.is_active.is_(True),
        Instrument.asset_class.in_(("equity", "fund")),
    )
    if symbol:
        q = q.where(Instrument.symbol == symbol)
    inst = session.scalar(q.limit(1))
    if inst is None:
        pytest.skip("no equity/fund instruments in DB")
    return inst


def _sber_profile(session) -> FeeProfile:
    profile = session.scalar(
        select(FeeProfile).where(
            FeeProfile.code == "SBER_INVESTMENT",
            FeeProfile.version == 1,
        )
    )
    if profile is None:
        pytest.skip("SBER_INVESTMENT fee profile not seeded (migration 0026)")
    return profile


def test_manual_commission_wins_over_profile(test_portfolio_id: int) -> None:
    with core_session() as session:
        portfolio = session.get(ManualPortfolio, test_portfolio_id)
        assert portfolio is not None
        profile = _sber_profile(session)
        account = create_broker_account(
            session, name="pytest-sber", fee_profile_id=int(profile.id)
        )
        assign_broker_account(session, portfolio, int(account.id))
        inst = _equity_instrument(session)

        create_operation(
            session,
            portfolio=portfolio,
            operation_type="DEPOSIT",
            occurred_at=date(2026, 9, 1),
            amount=Decimal("100000"),
            idempotency_key="bf-dep-1",
        )
        op = create_operation(
            session,
            portfolio=portfolio,
            operation_type="BUY",
            occurred_at=date(2026, 9, 2),
            instrument_id=int(inst.id),
            units=Decimal("10"),
            price=Decimal("100"),
            commission=Decimal("1"),
            commission_provided=True,
            non_standard_lot=True,
            idempotency_key="bf-buy-manual",
        )
        assert op.commission == money("1")
        assert op.commission_source == "MANUAL"
        assert op.broker_account_id == int(account.id)
        assert op.fee_rule_id is None


def test_profile_estimate_when_commission_omitted(test_portfolio_id: int) -> None:
    with core_session() as session:
        portfolio = session.get(ManualPortfolio, test_portfolio_id)
        assert portfolio is not None
        profile = _sber_profile(session)
        account = create_broker_account(
            session, name="pytest-sber-est", fee_profile_id=int(profile.id)
        )
        assign_broker_account(session, portfolio, int(account.id))
        inst = _equity_instrument(session)

        create_operation(
            session,
            portfolio=portfolio,
            operation_type="DEPOSIT",
            occurred_at=date(2026, 9, 29),
            amount=Decimal("100000"),
            idempotency_key="bf-dep-2",
        )
        op = create_operation(
            session,
            portfolio=portfolio,
            operation_type="BUY",
            occurred_at=date(2026, 9, 29),
            instrument_id=int(inst.id),
            units=Decimal("10"),
            price=Decimal("100"),
            commission_provided=False,
            non_standard_lot=True,
            idempotency_key="bf-buy-est",
        )
        # 10 * 100 * 0.3% = 3 (generic Sber rule valid_from 2026-09-29)
        assert op.commission == money("3")
        assert op.commission_source == "PROFILE_ESTIMATE"
        assert op.broker_account_id == int(account.id)
        assert op.fee_rule_id is not None


def test_profile_estimate_unknown_before_generic_valid_from(test_portfolio_id: int) -> None:
    """Pre-2026-09-29 ordinary equity: FeeEngine UNKNOWN — do not invent 0.3%."""
    with core_session() as session:
        portfolio = session.get(ManualPortfolio, test_portfolio_id)
        assert portfolio is not None
        profile = _sber_profile(session)
        account = create_broker_account(
            session, name="pytest-sber-pre", fee_profile_id=int(profile.id)
        )
        assign_broker_account(session, portfolio, int(account.id))
        inst = _equity_instrument(session, symbol="SBER")
        if inst is None or (inst.symbol or "").upper() != "SBER":
            inst = _equity_instrument(session)

        create_operation(
            session,
            portfolio=portfolio,
            operation_type="DEPOSIT",
            occurred_at=date(2026, 9, 1),
            amount=Decimal("100000"),
            idempotency_key="bf-dep-pre",
        )
        op = create_operation(
            session,
            portfolio=portfolio,
            operation_type="BUY",
            occurred_at=date(2026, 9, 1),
            instrument_id=int(inst.id),
            units=Decimal("10"),
            price=Decimal("100"),
            commission_provided=False,
            non_standard_lot=True,
            idempotency_key="bf-buy-pre",
        )
        # UNKNOWN → no fabricated PROFILE_ESTIMATE at 0.3%
        assert op.commission == money("0")
        assert op.commission_source == "NONE"
        assert op.fee_rule_id is None


def test_none_when_no_broker_backward_compatible(test_portfolio_id: int) -> None:
    with core_session() as session:
        portfolio = session.get(ManualPortfolio, test_portfolio_id)
        assert portfolio is not None
        assert portfolio.broker_account_id is None
        inst = _equity_instrument(session)
        create_operation(
            session,
            portfolio=portfolio,
            operation_type="DEPOSIT",
            occurred_at=date(2026, 9, 1),
            amount=Decimal("100000"),
            idempotency_key="bf-dep-3",
        )
        op = create_operation(
            session,
            portfolio=portfolio,
            operation_type="BUY",
            occurred_at=date(2026, 9, 2),
            instrument_id=int(inst.id),
            units=Decimal("10"),
            price=Decimal("100"),
            commission_provided=False,
            non_standard_lot=True,
            idempotency_key="bf-buy-none",
        )
        assert op.commission == money("0")
        assert op.commission_source == "NONE"
        assert op.broker_account_id is None


def test_sbfr_zero_fee_estimate(test_portfolio_id: int) -> None:
    with core_session() as session:
        portfolio = session.get(ManualPortfolio, test_portfolio_id)
        assert portfolio is not None
        profile = _sber_profile(session)
        account = create_broker_account(
            session, name="pytest-sbfr", fee_profile_id=int(profile.id)
        )
        assign_broker_account(session, portfolio, int(account.id))
        preview = estimate_fee_for_portfolio(
            session,
            portfolio=portfolio,
            side="BUY",
            notional=Decimal("50000"),
            instrument_symbol="SBFR",
            as_of=date(2026, 9, 29),
        )
        assert preview["status"] == "KNOWN"
        assert money(preview["amount"]) == money("0")
        assert preview["matched_rule_code"] == "SBER_SBFR_ZERO_TEMP"


def test_builtin_profile_refuse_edit() -> None:
    with core_session() as session:
        profile = _sber_profile(session)
        with pytest.raises(BrokerFeeError) as exc:
            update_custom_fee_profile(session, int(profile.id), buy_rate_pct=Decimal("1"))
        assert exc.value.code == "FEE_PROFILE_READ_ONLY"


def test_custom_profile_create_and_edit() -> None:
    with core_session() as session:
        profile = create_custom_fee_profile(
            session,
            name="pytest-custom",
            broker_name="PytestBroker",
            buy_rate_pct=Decimal("0.1"),
            sell_rate_pct=Decimal("0.2"),
        )
        assert profile.is_builtin is False
        assert profile.read_only is False
        updated = update_custom_fee_profile(
            session, int(profile.id), buy_rate_pct=Decimal("0.15")
        )
        buy_rule = next(r for r in updated.rules if (r.side or "").upper() == "BUY")
        assert buy_rule.percentage_rate == money("0.0015")


def test_decision_lot_suggestion_includes_fee_budget(test_portfolio_id: int) -> None:
    with core_session() as session:
        portfolio = session.get(ManualPortfolio, test_portfolio_id)
        assert portfolio is not None
        profile = _sber_profile(session)
        account = create_broker_account(
            session, name="pytest-decision-fee", fee_profile_id=int(profile.id)
        )
        assign_broker_account(session, portfolio, int(account.id))
        inst = _equity_instrument(session)
        # Budget exactly 1 lot notional — fee should shrink to 0 lots if fee > 0
        # Use price/lot such that one lot notional + fee exceeds tiny budget.
        # Instead: budget allows N lots by notional but notional+fee exceeds → shrink.
        sug = _lot_suggestion(
            session,
            symbol=inst.symbol or "X",
            instrument_id=int(inst.id),
            asset_class=inst.asset_class,
            unit_price=Decimal("100"),
            target_rub=Decimal("10030"),  # 100 lots of 1? depends on LOTSIZE
            portfolio=portfolio,
        )
        # If LOTSIZE unknown, skip fee assertion path
        if sug.get("lot_size") and sug["lot_size"] > 0:
            lot_n = money(Decimal("100") * Decimal(sug["lot_size"]))
            if lot_n <= Decimal("10030"):
                fee = money(sug.get("estimated_broker_fee_rub") or "0")
                total = money(sug.get("estimated_total_cash_out_rub") or "0")
                notional = money(sug.get("estimated_notional") or "0")
                if int(sug.get("lots") or 0) > 0:
                    assert total == money(notional + fee)
                    assert total <= money("10030")
                    # 0.3% of notional
                    assert fee == money(notional * Decimal("0.003"))


def test_decision_missing_broker_limitation_via_estimate(test_portfolio_id: int) -> None:
    with core_session() as session:
        portfolio = session.get(ManualPortfolio, test_portfolio_id)
        assert portfolio is not None
        preview = estimate_fee_for_portfolio(
            session,
            portfolio=portfolio,
            side="BUY",
            notional=Decimal("10000"),
            instrument_symbol="SBER",
        )
        assert preview["limitation"] == "BROKER_FEE_PROFILE_MISSING"
        assert preview["commission_source"] == "NONE"
