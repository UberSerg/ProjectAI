"""PERSONAL-ANALYTICS-01: Personal Portfolio is the sole analytics book source."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument, InstrumentSource
from app.modules.investment.application.portfolio_cashflow_service import (
    build_manual_portfolio_cashflows,
)
from app.modules.investment.infrastructure.models import (
    BondCashflow,
    BondMarketSnapshot,
    BondTerm,
)
from app.modules.portfolio.application.manual_portfolio_service import (
    advisory_rebalance,
    analyze_manual_portfolio,
    compare_to_candidate,
)
from app.modules.portfolio.application.personal_portfolio_service import (
    create_operation,
    get_or_create_test_portfolio,
    get_personal_summary,
    load_personal_snapshot,
)
from app.modules.portfolio.domain.personal_ledger import money
from app.modules.portfolio.infrastructure.models import ManualPosition, PersonalOperation


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


def _reset(session: Session, name: str):
    portfolio = get_or_create_test_portfolio(session, name=name)
    session.execute(delete(PersonalOperation).where(PersonalOperation.portfolio_id == portfolio.id))
    session.execute(delete(ManualPosition).where(ManualPosition.portfolio_id == portfolio.id))
    portfolio.cash_rub = Decimal("0")
    portfolio.total_contributed_rub = Decimal("0")
    portfolio.total_withdrawn_rub = Decimal("0")
    portfolio.realized_pnl_rub = Decimal("0")
    session.flush()
    return portfolio


def _equity(session: Session, symbol: str, *, close: Decimal, as_of: date) -> Instrument:
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


def _bond(
    session: Session,
    symbol: str = "PANLB",
    *,
    maturity: date | None = None,
    coupon_amount: Decimal | None = None,
    coupon_date: date | None = None,
) -> Instrument:
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
            maturity_date=maturity,
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
    if coupon_amount is not None and coupon_date is not None:
        session.add(
            BondCashflow(
                instrument_id=inst.id,
                cashflow_date=coupon_date,
                cashflow_type="COUPON",
                amount=coupon_amount,
                currency="RUB",
                known_at=date(2026, 1, 1),
                source="TEST",
                raw_fields={},
            )
        )
    session.flush()
    return inst


def test_a_personal_state_drives_analytics(pp_db: Session) -> None:
    portfolio = _reset(pp_db, "TEST — analytics A")
    sber = _equity(pp_db, "PASBER", close=Decimal("250"), as_of=date(2026, 9, 25))
    lkoh = _equity(pp_db, "PALKOH", close=Decimal("7000"), as_of=date(2026, 9, 25))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("1000000"),
        idempotency_key="pa-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=sber.id,
        units=Decimal("10"),
        price=Decimal("250"),
        non_standard_lot=True,
        idempotency_key="pa-sber",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 3, tzinfo=UTC),
        instrument_id=lkoh.id,
        units=Decimal("2"),
        price=Decimal("7000"),
        non_standard_lot=True,
        idempotency_key="pa-lkoh",
    )

    snap = load_personal_snapshot(pp_db, portfolio)
    assert snap.journal_state == "ACTIVE"
    assert {p.symbol for p in snap.positions} == {"PASBER", "PALKOH"}
    assert money(snap.cash_rub) == money("1000000") - money("2500") - money("14000")

    analysis = analyze_manual_portfolio(pp_db, portfolio)
    assert analysis["source"] == "personal_portfolio"
    assert analysis["journal_state"] == "ACTIVE"
    assert {r["symbol"] for r in analysis["positions"]} == {"PASBER", "PALKOH"}
    assert money(Decimal(str(analysis["cash_rub"]))) == money(snap.cash_rub)
    assert money(Decimal(str(analysis["nav"]))) == money(snap.known_nav_rub)

    summary = get_personal_summary(pp_db, portfolio)
    assert money(Decimal(summary["summary"]["nav_rub"])) == money(Decimal(str(analysis["nav"])))
    assert money(Decimal(summary["summary"]["cash_rub"])) == money(Decimal(str(analysis["cash_rub"])))


def test_c_contribution_not_profit(pp_db: Session) -> None:
    portfolio = _reset(pp_db, "TEST — analytics C")
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="pc-1",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        amount=Decimal("30000"),
        idempotency_key="pc-2",
    )
    analysis = analyze_manual_portfolio(pp_db, portfolio)
    assert money(Decimal(str(analysis["contributed_rub"]))) == money("130000")
    assert analysis["investment_pnl_rub"] == 0.0
    assert money(Decimal(str(analysis["nav"]))) == money("130000")


def test_d_partial_valuation(pp_db: Session) -> None:
    portfolio = _reset(pp_db, "TEST — analytics D")
    priced = _equity(pp_db, "PAPRX", close=Decimal("100"), as_of=date(2026, 9, 25))
    dark = Instrument(
        symbol="PADARK",
        name="No price",
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
        support_level="FULL",
        primary_board="TQBR",
    )
    pp_db.add(dark)
    pp_db.flush()
    pp_db.add(
        InstrumentSource(
            instrument_id=dark.id,
            source="MOEX_ISS",
            external_id="PADARK",
            board="TQBR",
            source_metadata={"LOTSIZE": 1},
        )
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("50000"),
        idempotency_key="pd-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=priced.id,
        units=Decimal("10"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="pd-buy1",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 3, tzinfo=UTC),
        instrument_id=dark.id,
        units=Decimal("5"),
        price=Decimal("10"),
        non_standard_lot=True,
        idempotency_key="pd-buy2",
    )
    analysis = analyze_manual_portfolio(pp_db, portfolio)
    assert analysis["valuation_partial"] is True
    assert analysis["investment_pnl_rub"] is None
    dark_row = next(r for r in analysis["positions"] if r["symbol"] == "PADARK")
    assert dark_row["market_value"] is None
    assert dark_row["supported"] is False


def test_e_bond_pnl_not_fabricated(pp_db: Session) -> None:
    portfolio = _reset(pp_db, "TEST — analytics E")
    bond = _bond(pp_db, "PABND")
    # Legacy-like projection row with % average (must not become RUB cost in analytics).
    portfolio.cash_rub = Decimal("0")
    pp_db.add(
        ManualPosition(
            portfolio_id=portfolio.id,
            instrument_id=bond.id,
            units=Decimal("2"),
            average_price=None,
        )
    )
    pp_db.flush()
    snap = load_personal_snapshot(pp_db, portfolio)
    assert len(snap.positions) == 1
    assert snap.positions[0].market_value is not None
    assert snap.positions[0].unrealized_pnl is None
    assert snap.positions[0].cost_basis_usable is False

    analysis = analyze_manual_portfolio(pp_db, portfolio)
    row = analysis["positions"][0]
    assert row["market_value"] is not None
    assert row["unrealized_pnl"] is None
    assert row["cost_basis_usable"] is False
    assert analysis["portfolio"]["positions"][0]["average_price"] is None


def test_f_compare_actual_is_personal(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = _reset(pp_db, "TEST — analytics F")
    eq = _equity(pp_db, "PACMP", close=Decimal("100"), as_of=date(2026, 9, 25))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="pf-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq.id,
        units=Decimal("10"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="pf-buy",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "cand-test",
            "positions": [{"symbol": "PACMP", "weight": 0.5}, {"symbol": "OTHER", "weight": 0.5}],
        },
    )
    compare = compare_to_candidate(pp_db, portfolio)
    assert compare["actual_source"] == "personal_portfolio"
    assert compare["journal_state"] == "ACTIVE"
    by_sym = {c["symbol"]: c for c in compare["comparisons"]}
    assert by_sym["PACMP"]["manual_weight"] is not None
    assert by_sym["OTHER"]["status"] == "NOT_IN_MANUAL"


def test_g_journal_states(pp_db: Session) -> None:
    empty = _reset(pp_db, "TEST — analytics G empty")
    a_empty = analyze_manual_portfolio(pp_db, empty)
    assert a_empty["journal_state"] == "EMPTY"
    assert a_empty["positions"] == []

    legacy = _reset(pp_db, "TEST — analytics G legacy")
    eq = _equity(pp_db, "PALEG", close=Decimal("10"), as_of=date(2026, 9, 25))
    legacy.cash_rub = Decimal("5000")
    pp_db.add(
        ManualPosition(
            portfolio_id=legacy.id,
            instrument_id=eq.id,
            units=Decimal("3"),
            average_price=Decimal("10"),
        )
    )
    pp_db.flush()
    a_legacy = analyze_manual_portfolio(pp_db, legacy)
    assert a_legacy["journal_state"] == "DRAFT"
    assert len(a_legacy["positions"]) == 1


def test_h_cashflows_use_personal_snapshot_units(pp_db: Session) -> None:
    """Cashflows must scale from snap.positions, not a second ManualPosition scan.

    Bond BUY via journal is blocked (ADVISORY_ONLY). Seed a DRAFT ManualPosition instead.
    """
    portfolio = _reset(pp_db, "TEST — analytics H cashflows")
    bond = _bond(
        pp_db,
        "PACF1",
        maturity=date(2028, 6, 1),
        coupon_amount=Decimal("35.4"),
        coupon_date=date(2026, 12, 1),
    )
    pp_db.add(
        ManualPosition(
            portfolio_id=portfolio.id,
            instrument_id=bond.id,
            units=Decimal("3"),
            average_price=Decimal("967.5"),
        )
    )
    portfolio.cash_rub = Decimal("100000")
    pp_db.flush()

    snap = load_personal_snapshot(pp_db, portfolio)
    assert len(snap.positions) == 1
    assert money(snap.positions[0].units) == money("3")

    result = build_manual_portfolio_cashflows(
        pp_db, as_of=date(2026, 9, 28), portfolio=portfolio
    )
    assert result["source"] == "personal_portfolio"
    assert result["portfolio_id"] == portfolio.id
    assert result["analysis"]["bond_position_count"] == 1
    row = result["positions"][0]
    assert row["symbol"] == "PACF1"
    assert money(Decimal(str(row["units"]))) == money("3")
    assert row["cashflow_count"] == 1
    assert row["next_payment"] is not None
    # 3 units × 35.4 coupon = 106.2 gross for the next payment
    assert money(Decimal(str(row["next_payment"]["gross_amount"]))) == money("106.2")
    assert money(Decimal(str(row["next_payment"]["units"]))) == money("3")


def test_i_rebalance_uses_snapshot_positions(
    pp_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rebalance current_units come from snap.positions (Personal SoT)."""
    portfolio = _reset(pp_db, "TEST — analytics I rebalance")
    eq = _equity(pp_db, "PAREB", close=Decimal("100"), as_of=date(2026, 9, 25))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="pi-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq.id,
        units=Decimal("10"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="pi-buy",
    )

    snap = load_personal_snapshot(pp_db, portfolio)
    assert money(snap.positions[0].units) == money("10")
    analysis = analyze_manual_portfolio(pp_db, portfolio)
    assert money(Decimal(str(analysis["nav"]))) == money(snap.known_nav_rub)

    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "cand-reb",
            "positions": [{"symbol": "PAREB", "weight": 0.5}, {"symbol": "OTHER", "weight": 0.5}],
        },
    )
    plan = advisory_rebalance(pp_db, portfolio)
    assert plan["actual_source"] == "personal_portfolio"
    assert plan["journal_state"] == "ACTIVE"
    assert plan["advisory"] is True
    assert plan["persisted_orders"] is False
    assert plan["cash_safe"] is True
    # Plan must see the Personal holding of 10 units as current side.
    by_ticker = {r["ticker"]: r for r in plan["plan_rows"]}
    assert "PAREB" in by_ticker
    # current_weight derived from 10 units × price vs NAV — financially tied to snapshot.
    assert money(Decimal(str(plan["nav"]))) == money(snap.known_nav_rub)
    assert money(Decimal(str(plan["cash"]))) == money(snap.cash_rub)
