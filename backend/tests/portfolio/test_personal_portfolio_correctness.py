"""Corrective-pass financial correctness for Personal Portfolio V1."""

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
    cancel_operation,
    create_operation,
    get_or_create_test_portfolio,
    get_personal_summary,
    journal_operation_count,
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


def _make_bond(session: Session, symbol: str = "PPBOND") -> Instrument:
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
    # Misleading equity-style EOD candle — must NOT be used as RUB unit price.
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


def test_bond_valuation_uses_dirty_not_percent_as_rub(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — bond valuation")
    bond = _make_bond(pp_db)
    pp_db.add(
        ManualPosition(
            portfolio_id=portfolio.id,
            instrument_id=bond.id,
            units=Decimal("2"),
            average_price=Decimal("967.5"),
        )
    )
    pp_db.flush()

    summary = get_personal_summary(pp_db, portfolio)
    pos = next(p for p in summary["positions"] if p["instrument_id"] == bond.id)
    # Dirty: 2 * (1000*0.955 + 12.5) = 2 * 967.5 = 1935 — NOT 95.5 × 2
    assert pos["market_value"] == str(money("1935"))
    assert Decimal(pos["market_value"]) != money(Decimal("95.5") * 2)
    assert pos["price_available"] is True
    assert Decimal(pos["current_price"]) == money("967.5")


def test_bond_journal_trade_blocked(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — bond trade block")
    bond = _make_bond(pp_db, "PPBOND2")
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=date(2026, 9, 1),
        amount=Decimal("100000"),
        idempotency_key="bond-block-dep",
    )
    with pytest.raises(PersonalPortfolioError) as ei:
        create_operation(
            pp_db,
            portfolio=portfolio,
            operation_type="BUY",
            occurred_at=date(2026, 9, 2),
            instrument_id=bond.id,
            units=Decimal("1"),
            price=Decimal("95.5"),
            non_standard_lot=True,
            idempotency_key="bond-block-buy",
        )
    assert ei.value.code == "BOND_TRADE_ACCOUNTING_NOT_READY"
    assert journal_operation_count(pp_db, portfolio.id) == 1


def test_legacy_bootstrap_preserves_cash_and_position(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — legacy bootstrap")
    eq = _make_equity(pp_db, "PPLEG1", close=Decimal("260"), as_of=date(2026, 9, 25))
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
    assert journal_operation_count(pp_db, portfolio.id) == 0

    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=date(2026, 9, 10),
        amount=Decimal("10000"),
        idempotency_key="legacy-dep-1",
    )
    assert money(portfolio.cash_rub) == money("60000")
    pos = pp_db.scalar(
        select(ManualPosition).where(
            ManualPosition.portfolio_id == portfolio.id,
            ManualPosition.instrument_id == eq.id,
        )
    )
    assert pos is not None
    assert Decimal(pos.units) == Decimal("100")
    opening = pp_db.scalars(
        select(PersonalOperation).where(
            PersonalOperation.portfolio_id == portfolio.id,
            PersonalOperation.source == "LEGACY_BOOTSTRAP",
        )
    ).all()
    assert len(opening) == 2  # cash + position


def test_legacy_missing_cost_basis_rejected(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — legacy no cost")
    eq = _make_equity(pp_db, "PPLEG2", close=Decimal("100"), as_of=date(2026, 9, 25))
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
        create_operation(
            pp_db,
            portfolio=portfolio,
            operation_type="DEPOSIT",
            occurred_at=date(2026, 9, 10),
            amount=Decimal("100"),
            idempotency_key="legacy-nocost",
        )
    assert ei.value.code == "LEGACY_COST_BASIS_REQUIRED"
    assert journal_operation_count(pp_db, portfolio.id) == 0
    assert money(portfolio.cash_rub) == money("1000")


def test_legacy_bootstrap_idempotent(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — legacy idem")
    portfolio.cash_rub = Decimal("5000")
    pp_db.flush()
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=date(2026, 9, 1),
        amount=Decimal("1000"),
        idempotency_key="legacy-idem-1",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=date(2026, 9, 2),
        amount=Decimal("500"),
        idempotency_key="legacy-idem-2",
    )
    openings = pp_db.scalars(
        select(PersonalOperation).where(
            PersonalOperation.portfolio_id == portfolio.id,
            PersonalOperation.operation_type == "OPENING_CASH",
        )
    ).all()
    assert len(openings) == 1


def test_journal_managed_blocks_legacy_writes(pp_db: Session) -> None:
    primary = get_or_create_primary(pp_db)
    for pos in list(
        pp_db.scalars(select(ManualPosition).where(ManualPosition.portfolio_id == primary.id)).all()
    ):
        pp_db.delete(pos)
    pp_db.execute(delete(PersonalOperation).where(PersonalOperation.portfolio_id == primary.id))
    primary.cash_rub = Decimal("0")
    pp_db.flush()

    # Before journal: legacy write ok
    update_cash(pp_db, Decimal("100"))
    assert money(primary.cash_rub) == money("100")

    create_operation(
        pp_db,
        portfolio=primary,
        operation_type="DEPOSIT",
        occurred_at=date(2026, 9, 1),
        amount=Decimal("50"),
        idempotency_key="primary-journal-1",
    )
    cash_before = money(primary.cash_rub)
    with pytest.raises(PersonalPortfolioError) as ei:
        update_cash(pp_db, Decimal("999999"))
    assert ei.value.code == "PORTFOLIO_JOURNAL_MANAGED"
    assert money(primary.cash_rub) == cash_before

    eq = _make_equity(pp_db, "PPGUARD", close=Decimal("10"), as_of=date(2026, 9, 25))
    with pytest.raises(PersonalPortfolioError) as ei2:
        add_position(pp_db, instrument_id=eq.id, units=Decimal("1"), average_price=Decimal("10"))
    assert ei2.value.code == "PORTFOLIO_JOURNAL_MANAGED"


def test_partial_valuation_nulls_investment_pnl(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — partial pnl")
    a = _make_equity(pp_db, "PPKA", close=Decimal("100"), as_of=date(2026, 9, 25))
    b = Instrument(
        symbol="PPKB",
        name="PPKB",
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
        support_level="FULL",
        primary_board="TQBR",
    )
    pp_db.add(b)
    pp_db.flush()

    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=date(2026, 9, 1),
        amount=Decimal("100000"),
        idempotency_key="partial-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=date(2026, 9, 2),
        instrument_id=a.id,
        units=Decimal("400"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="partial-buy-a",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="OPENING_POSITION",
        occurred_at=date(2026, 9, 2),
        instrument_id=b.id,
        units=Decimal("10"),
        price=Decimal("50"),
        non_standard_lot=True,
        idempotency_key="partial-open-b",
    )
    summary = get_personal_summary(pp_db, portfolio)
    assert summary["summary"]["valuation_partial"] is True
    assert summary["summary"]["missing_price_count"] >= 1
    assert summary["summary"]["investment_pnl_rub"] is None


def test_mixed_price_dates_label(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — mixed dates")
    a = _make_equity(pp_db, "PPDA", close=Decimal("10"), as_of=date(2026, 9, 20))
    b = _make_equity(pp_db, "PPDB", close=Decimal("20"), as_of=date(2026, 9, 25))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=date(2026, 9, 1),
        amount=Decimal("100000"),
        idempotency_key="mix-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=date(2026, 9, 2),
        instrument_id=a.id,
        units=Decimal("1"),
        price=Decimal("10"),
        non_standard_lot=True,
        idempotency_key="mix-buy-a",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=date(2026, 9, 2),
        instrument_id=b.id,
        units=Decimal("1"),
        price=Decimal("20"),
        non_standard_lot=True,
        idempotency_key="mix-buy-b",
    )
    summary = get_personal_summary(pp_db, portfolio)
    label = summary["summary"]["valuation_label"]
    assert "20.09" in label and "25.09" in label
    assert summary["summary"]["valuation_as_of"] != "2026-09-25" or "–" in label or "-" in label
    # Must not claim whole portfolio is valued only on newest date.
    assert label != "Оценка по ценам на 25.09.2026"


def test_idempotency_same_key_different_payload_conflict(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — idem conflict")
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=date(2026, 9, 1),
        amount=Decimal("100000"),
        idempotency_key="same-key",
    )
    with pytest.raises(PersonalPortfolioError) as ei:
        create_operation(
            pp_db,
            portfolio=portfolio,
            operation_type="DEPOSIT",
            occurred_at=date(2026, 9, 1),
            amount=Decimal("50000"),
            idempotency_key="same-key",
        )
    assert ei.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert money(portfolio.cash_rub) == money("100000")


def test_idempotency_same_payload_reuses(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — idem reuse")
    a = create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=date(2026, 9, 1),
        amount=Decimal("100000"),
        idempotency_key="reuse-key",
    )
    b = create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=date(2026, 9, 1),
        amount=Decimal("100000"),
        idempotency_key="reuse-key",
    )
    assert a.id == b.id
    assert money(portfolio.cash_rub) == money("100000")


def test_cancel_retry_returns_original(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — cancel retry")
    op = create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=date(2026, 9, 1),
        amount=Decimal("1000"),
        idempotency_key="cancel-src",
    )
    first = cancel_operation(
        pp_db,
        portfolio=portfolio,
        operation_id=op.id,
        reason="fix",
        idempotency_key="cancel-key-1",
    )
    second = cancel_operation(
        pp_db,
        portfolio=portfolio,
        operation_id=op.id,
        reason="fix",
        idempotency_key="cancel-key-1",
    )
    assert first.id == op.id
    assert second.id == op.id
    assert first.id == second.id


def test_future_dated_operation_rejected(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — future date")
    future = date.today() + timedelta(days=3)
    with pytest.raises(PersonalPortfolioError) as ei:
        create_operation(
            pp_db,
            portfolio=portfolio,
            operation_type="DEPOSIT",
            occurred_at=future,
            amount=Decimal("1000"),
            idempotency_key="future-1",
        )
    assert ei.value.code == "FUTURE_DATED_OPERATION"


def test_contribution_still_not_profit(pp_db: Session) -> None:
    portfolio = _reset_test_portfolio(pp_db, "TEST — contrib")
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=date(2026, 9, 1),
        amount=Decimal("100000"),
        idempotency_key="c-1",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=date(2026, 9, 2),
        amount=Decimal("30000"),
        idempotency_key="c-2",
    )
    summary = get_personal_summary(pp_db, portfolio)
    assert money(summary["summary"]["contributed_rub"]) == money("130000")
    assert money(summary["summary"]["investment_pnl_rub"]) == money("0")
