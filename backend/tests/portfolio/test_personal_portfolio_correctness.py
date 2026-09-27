"""Final correctness: cutover, bond P&L, as-of, cancel idempotency."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument, InstrumentSource
from app.modules.investment.infrastructure.models import BondMarketSnapshot, BondTerm
from app.modules.portfolio.application.manual_portfolio_service import (
    add_position,
    get_or_create_primary,
    update_cash,
)
from app.modules.portfolio.application.personal_portfolio_service import (
    PersonalPortfolioError,
    activate_journal,
    cancel_operation,
    create_operation,
    get_or_create_test_portfolio,
    get_personal_summary,
    journal_cutover_at,
    journal_operation_count,
    journal_state,
)
from app.modules.portfolio.domain.personal_ledger import money
from app.modules.portfolio.infrastructure.models import (
    ManualPortfolio,
    ManualPosition,
    PersonalOperation,
)


def _schema_ready(session: Session) -> bool:
    try:
        session.execute(text("SELECT 1 FROM portfolio.personal_operations LIMIT 0"))
        return True
    except Exception:
        session.rollback()
        return False


@pytest.fixture
def pp_db() -> Generator[Session, None, None]:
    try:
        from app.core.config import get_settings
        from app.infrastructure.db.session import get_core_engine

        get_settings.cache_clear()
        engine = get_core_engine()
        connection = engine.connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"core database unavailable: {exc}")

    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    try:
        if not _schema_ready(session):
            pytest.skip("personal_operations migration not applied")
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _reset_test_portfolio(session: Session, name: str) -> ManualPortfolio:
    portfolio = get_or_create_test_portfolio(session, name=name)
    session.execute(delete(PersonalOperation).where(PersonalOperation.portfolio_id == portfolio.id))
    session.execute(delete(ManualPosition).where(ManualPosition.portfolio_id == portfolio.id))
    portfolio.cash_rub = Decimal("0")
    portfolio.total_contributed_rub = Decimal("0")
    portfolio.total_withdrawn_rub = Decimal("0")
    portfolio.realized_pnl_rub = Decimal("0")
    session.flush()
    return portfolio


def _make_equity(session: Session, symbol: str, *, close: Decimal, as_of: date) -> Instrument:
    inst = Instrument(
        symbol=symbol,
        name=symbol,
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
        support_level="FULL",
        primary_board="TQBR",
    )
    session.add(inst)
    session.flush()
    session.add(
        InstrumentSource(
            instrument_id=inst.id,
            source="MOEX_ISS",
            external_id=symbol,
            board="TQBR",
            source_metadata={"LOTSIZE": 1},
        )
    )
    session.add(
        Candle(
            instrument_id=inst.id,
            timeframe="1d",
            timestamp=datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=Decimal("1000"),
            source="TEST",
        )
    )
    session.flush()
    return inst


def _make_bond(session: Session, symbol: str = "PPCUTB") -> Instrument:
    inst = Instrument(
        symbol=symbol,
        name=symbol,
        asset_class="bond",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
        support_level="PARTIAL",
        primary_board="TQOB",
        instrument_subtype="ofz_gov",
    )
    session.add(inst)
    session.flush()
    session.add(
        BondTerm(
            instrument_id=inst.id,
            bond_type="Government",
            nominal=Decimal("1000"),
            currency="RUB",
            lot_size=1,
            support_status="SUPPORTED",
            credit_quality_status="OBSERVED",
            known_at=date(2026, 1, 1),
            source="TEST",
            raw_fields={},
        )
    )
    session.add(
        BondMarketSnapshot(
            instrument_id=inst.id,
            as_of=date(2026, 9, 20),
            clean_price_percent=Decimal("95.5"),
            accrued_interest=Decimal("12.5"),
            source="TEST",
            observed_fields={},
        )
    )
    session.add(
        Candle(
            instrument_id=inst.id,
            timeframe="1d",
            timestamp=datetime(2026, 9, 20, tzinfo=UTC),
            open=Decimal("95.5"),
            high=Decimal("95.5"),
            low=Decimal("95.5"),
            close=Decimal("95.5"),
            volume=Decimal("10"),
            source="TEST",
        )
    )
    session.flush()
    return inst


def test_cutover_a_legacy_pending(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — cutover A")
    eq = _make_equity(pp_db, "CUTA", close=Decimal("260"), as_of=date(2026, 9, 25))
    portfolio.cash_rub = Decimal("50000")
    pp_db.add(
        ManualPosition(
            portfolio_id=portfolio.id,
            instrument_id=eq.id,
            units=Decimal("100"),
            average_price=Decimal("250"),
        )
    )
    pp_db.flush()
    assert journal_state(pp_db, portfolio) == "LEGACY_PENDING"
    summary = get_personal_summary(pp_db, portfolio)
    assert summary["portfolio"]["journal_state"] == "LEGACY_PENDING"
    assert journal_operation_count(pp_db, portfolio.id) == 0


def test_cutover_b_explicit_activation(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — cutover B")
    eq = _make_equity(pp_db, "CUTB", close=Decimal("260"), as_of=date(2026, 9, 25))
    portfolio.cash_rub = Decimal("50000")
    pp_db.add(
        ManualPosition(
            portfolio_id=portfolio.id,
            instrument_id=eq.id,
            units=Decimal("100"),
            average_price=Decimal("250"),
        )
    )
    pp_db.flush()
    summary = activate_journal(pp_db, portfolio)
    assert summary["portfolio"]["journal_state"] == "ACTIVE"
    assert summary["portfolio"]["journal_cutover_at"] is not None
    assert money(summary["summary"]["cash_rub"]) == money("50000")
    pos = next(p for p in summary["positions"] if p["instrument_id"] == eq.id)
    assert Decimal(pos["units"]) == Decimal("100")
    assert Decimal(pos["average_price"]) == money("250")
    assert summary["reconciliation"]["status"] == "OK"
    openings = pp_db.scalars(
        select(PersonalOperation).where(
            PersonalOperation.portfolio_id == portfolio.id,
            PersonalOperation.source == "LEGACY_BOOTSTRAP",
        )
    ).all()
    assert len(openings) == 2
    assert len({o.occurred_at for o in openings}) == 1


def test_cutover_c_activation_idempotent(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — cutover C")
    portfolio.cash_rub = Decimal("5000")
    pp_db.flush()
    activate_journal(pp_db, portfolio)
    n1 = journal_operation_count(pp_db, portfolio.id)
    activate_journal(pp_db, portfolio)
    assert journal_operation_count(pp_db, portfolio.id) == n1


def test_cutover_d_e_before_after_cutover(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — cutover DE")
    portfolio.cash_rub = Decimal("50000")
    pp_db.flush()
    activate_journal(pp_db, portfolio)
    cutover = journal_cutover_at(pp_db, portfolio.id)
    assert cutover is not None
    with pytest.raises(PersonalPortfolioError) as ei:
        create_operation(
            pp_db,
            portfolio=portfolio,
            operation_type="DEPOSIT",
            occurred_at=cutover - timedelta(days=1),
            amount=Decimal("1000"),
            idempotency_key="before-cut",
        )
    assert ei.value.code == "OPERATION_BEFORE_JOURNAL_CUTOVER"
    assert money(portfolio.cash_rub) == money("50000")

    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=cutover + timedelta(minutes=5),
        amount=Decimal("1000"),
        idempotency_key="after-cut",
    )
    assert money(portfolio.cash_rub) == money("51000")


def test_cutover_f_no_auto_bootstrap(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — cutover F")
    portfolio.cash_rub = Decimal("50000")
    pp_db.flush()
    with pytest.raises(PersonalPortfolioError) as ei:
        create_operation(
            pp_db,
            portfolio=portfolio,
            operation_type="DEPOSIT",
            occurred_at=datetime.now(UTC),
            amount=Decimal("10000"),
            idempotency_key="no-auto",
        )
    assert ei.value.code == "LEGACY_STATE_REQUIRES_CUTOVER"
    assert journal_operation_count(pp_db, portfolio.id) == 0


def test_cutover_g_missing_cost_basis(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — cutover G")
    eq = _make_equity(pp_db, "CUTG", close=Decimal("100"), as_of=date(2026, 9, 25))
    portfolio.cash_rub = Decimal("1000")
    pp_db.add(
        ManualPosition(
            portfolio_id=portfolio.id,
            instrument_id=eq.id,
            units=Decimal("10"),
            average_price=None,
        )
    )
    pp_db.flush()
    with pytest.raises(PersonalPortfolioError) as ei:
        activate_journal(pp_db, portfolio)
    assert ei.value.code == "LEGACY_COST_BASIS_REQUIRED"
    assert journal_operation_count(pp_db, portfolio.id) == 0
    assert money(portfolio.cash_rub) == money("1000")


def test_cutover_h_legacy_bond_rejected(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — cutover H")
    bond = _make_bond(pp_db, "CUTH")
    portfolio.cash_rub = Decimal("1000")
    pp_db.add(
        ManualPosition(
            portfolio_id=portfolio.id,
            instrument_id=bond.id,
            units=Decimal("2"),
            average_price=Decimal("95.5"),
        )
    )
    pp_db.flush()
    with pytest.raises(PersonalPortfolioError) as ei:
        activate_journal(pp_db, portfolio)
    assert ei.value.code == "LEGACY_BOND_COST_BASIS_NOT_READY"
    assert journal_operation_count(pp_db, portfolio.id) == 0
    assert money(portfolio.cash_rub) == money("1000")


def test_bond_valuation_and_null_unrealized(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — bond pnl")
    bond = _make_bond(pp_db, "PPNLB")
    pp_db.add(
        ManualPosition(
            portfolio_id=portfolio.id,
            instrument_id=bond.id,
            units=Decimal("2"),
            average_price=Decimal("95.5"),  # ambiguous % — must NOT invent P&L
        )
    )
    pp_db.flush()
    summary = get_personal_summary(pp_db, portfolio)
    pos = next(p for p in summary["positions"] if p["instrument_id"] == bond.id)
    assert pos["market_value"] == str(money("1935"))
    assert pos["unrealized_pnl"] is None
    assert Decimal(pos["market_value"]) != money(Decimal("95.5") * 2)


def test_valuation_as_of_same_mixed_partial(pp_db: Session) -> None:
    # Same date
    p1 = _reset_test_portfolio(pp_db, "TEST — asof same")
    a = _make_equity(pp_db, "AS1", close=Decimal("10"), as_of=date(2026, 9, 25))
    b = _make_equity(pp_db, "AS2", close=Decimal("20"), as_of=date(2026, 9, 25))
    create_operation(
        pp_db,
        portfolio=p1,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="asof-dep1",
    )
    create_operation(
        pp_db,
        portfolio=p1,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=a.id,
        units=Decimal("1"),
        price=Decimal("10"),
        non_standard_lot=True,
        idempotency_key="asof-b1",
    )
    create_operation(
        pp_db,
        portfolio=p1,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=b.id,
        units=Decimal("1"),
        price=Decimal("20"),
        non_standard_lot=True,
        idempotency_key="asof-b2",
    )
    s1 = get_personal_summary(pp_db, p1)
    assert s1["summary"]["valuation_as_of"] == "2026-09-25"
    assert s1["summary"]["valuation_from"] == "2026-09-25"
    assert s1["summary"]["valuation_to"] == "2026-09-25"

    # Mixed
    p2 = _reset_test_portfolio(pp_db, "TEST — asof mix")
    c = _make_equity(pp_db, "AM1", close=Decimal("10"), as_of=date(2026, 9, 20))
    d = _make_equity(pp_db, "AM2", close=Decimal("20"), as_of=date(2026, 9, 25))
    create_operation(
        pp_db,
        portfolio=p2,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="mix-dep",
    )
    create_operation(
        pp_db,
        portfolio=p2,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=c.id,
        units=Decimal("1"),
        price=Decimal("10"),
        non_standard_lot=True,
        idempotency_key="mix-c",
    )
    create_operation(
        pp_db,
        portfolio=p2,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=d.id,
        units=Decimal("1"),
        price=Decimal("20"),
        non_standard_lot=True,
        idempotency_key="mix-d",
    )
    s2 = get_personal_summary(pp_db, p2)
    assert s2["summary"]["valuation_as_of"] is None
    assert s2["summary"]["valuation_from"] == "2026-09-20"
    assert s2["summary"]["valuation_to"] == "2026-09-25"
    assert "20.09" in s2["summary"]["valuation_label"] and "25.09" in s2["summary"]["valuation_label"]

    # Partial
    p3 = _reset_test_portfolio(pp_db, "TEST — asof partial")
    e = _make_equity(pp_db, "AP1", close=Decimal("10"), as_of=date(2026, 9, 25))
    f = Instrument(
        symbol="AP2",
        name="AP2",
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
        support_level="FULL",
        primary_board="TQBR",
    )
    pp_db.add(f)
    pp_db.flush()
    create_operation(
        pp_db,
        portfolio=p3,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="par-dep",
    )
    create_operation(
        pp_db,
        portfolio=p3,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=e.id,
        units=Decimal("1"),
        price=Decimal("10"),
        non_standard_lot=True,
        idempotency_key="par-e",
    )
    create_operation(
        pp_db,
        portfolio=p3,
        operation_type="OPENING_POSITION",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=f.id,
        units=Decimal("1"),
        price=Decimal("10"),
        non_standard_lot=True,
        idempotency_key="par-f",
    )
    s3 = get_personal_summary(pp_db, p3)
    assert s3["summary"]["valuation_partial"] is True
    assert s3["summary"]["valuation_as_of"] is None
    assert s3["summary"]["investment_pnl_rub"] is None


def test_cancel_idempotency_intent(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — cancel intent")
    a = create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("1000"),
        idempotency_key="c-a",
    )
    b = create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        amount=Decimal("2000"),
        idempotency_key="c-b",
    )
    first = cancel_operation(
        pp_db, portfolio=portfolio, operation_id=a.id, reason="Исправление", idempotency_key="ck"
    )
    second = cancel_operation(
        pp_db, portfolio=portfolio, operation_id=a.id, reason="Исправление", idempotency_key="ck"
    )
    assert first.id == a.id == second.id

    with pytest.raises(PersonalPortfolioError) as ei:
        cancel_operation(
            pp_db, portfolio=portfolio, operation_id=b.id, reason="Исправление", idempotency_key="ck"
        )
    assert ei.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert pp_db.get(PersonalOperation, b.id).status == "ACTIVE"

    with pytest.raises(PersonalPortfolioError) as ei2:
        cancel_operation(
            pp_db, portfolio=portfolio, operation_id=a.id, reason="Другая причина", idempotency_key="ck"
        )
    assert ei2.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_idempotency_and_contribution_and_guards(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — regress")
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="r-1",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        amount=Decimal("30000"),
        idempotency_key="r-2",
    )
    summary = get_personal_summary(pp_db, portfolio)
    assert money(summary["summary"]["contributed_rub"]) == money("130000")
    assert money(summary["summary"]["investment_pnl_rub"]) == money("0")

    with pytest.raises(PersonalPortfolioError) as ei:
        create_operation(
            pp_db,
            portfolio=portfolio,
            operation_type="DEPOSIT",
            occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
            amount=Decimal("50000"),
            idempotency_key="r-1",
        )
    assert ei.value.code == "IDEMPOTENCY_KEY_REUSED"

    # Primary write guard after journal active
    primary = get_or_create_primary(pp_db)
    for pos in list(
        pp_db.scalars(select(ManualPosition).where(ManualPosition.portfolio_id == primary.id)).all()
    ):
        pp_db.delete(pos)
    pp_db.execute(delete(PersonalOperation).where(PersonalOperation.portfolio_id == primary.id))
    primary.cash_rub = Decimal("0")
    pp_db.flush()
    create_operation(
        pp_db,
        portfolio=primary,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("10"),
        idempotency_key="prim-1",
    )
    with pytest.raises(PersonalPortfolioError) as eg:
        update_cash(pp_db, Decimal("999"))
    assert eg.value.code == "PORTFOLIO_JOURNAL_MANAGED"
    eq = _make_equity(pp_db, "GRD1", close=Decimal("1"), as_of=date(2026, 9, 25))
    with pytest.raises(PersonalPortfolioError) as eg2:
        add_position(pp_db, instrument_id=eq.id, units=Decimal("1"), average_price=Decimal("1"))
    assert eg2.value.code == "PORTFOLIO_JOURNAL_MANAGED"


def test_bond_trade_still_blocked(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — bond block")
    bond = _make_bond(pp_db, "BLKB")
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="bb-dep",
    )
    with pytest.raises(PersonalPortfolioError) as ei:
        create_operation(
            pp_db,
            portfolio=portfolio,
            operation_type="BUY",
            occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
            instrument_id=bond.id,
            units=Decimal("1"),
            price=Decimal("95.5"),
            non_standard_lot=True,
            idempotency_key="bb-buy",
        )
    assert ei.value.code == "BOND_TRADE_ACCOUNTING_NOT_READY"
