"""Multi-Portfolio V2 — collection, isolation, DRAFT/ACTIVE lifecycle."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument, InstrumentSource
from app.modules.portfolio.application.daily_personal_decision_service import (
    build_daily_personal_decision,
)
from app.modules.portfolio.application.personal_portfolio_service import (
    PersonalPortfolioError,
    cancel_operation,
    create_operation,
    load_personal_snapshot,
)
from app.modules.portfolio.application.user_portfolio_service import (
    activate_portfolio,
    add_draft_position,
    clear_draft_portfolio,
    create_user_portfolio,
    delete_draft_position,
    delete_user_portfolio,
    list_user_portfolios,
    patch_draft_position,
    rename_user_portfolio,
    reset_portfolio,
    set_draft_cash,
)
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
def mp_db() -> Generator[Session, None, None]:
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
        # Clean user books for isolation within the savepoint transaction.
        session.execute(delete(PersonalOperation))
        session.execute(delete(ManualPosition))
        session.execute(delete(ManualPortfolio).where(ManualPortfolio.is_test.is_(False)))
        session.flush()
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _mk_instrument(session: Session, *, symbol: str, asset_class: str = "equity") -> Instrument:
    row = Instrument(
        symbol=symbol,
        name=symbol,
        asset_class=asset_class,
        exchange="MOEX",
        currency="RUB",
        is_active=True,
        support_level="FULL",
        primary_board="TQBR" if asset_class != "bond" else "TQOB",
    )
    session.add(row)
    session.flush()
    session.add(
        InstrumentSource(
            instrument_id=row.id,
            source="MOEX_ISS",
            external_id=symbol,
            board=row.primary_board,
            source_metadata={"LOTSIZE": 1},
        )
    )
    session.flush()
    return row


@pytest.fixture
def two_books(mp_db: Session):
    a = create_user_portfolio(mp_db, name="Основной", description="A")
    b = create_user_portfolio(mp_db, name="ОФЗ", description="B")
    mp_db.flush()
    return a, b


def test_empty_list(mp_db: Session):
    assert list_user_portfolios(mp_db) == []


def test_create_rename_duplicate_delete(mp_db: Session, two_books):
    a, b = two_books
    cards = list_user_portfolios(mp_db)
    assert len(cards) == 2
    rename_user_portfolio(mp_db, a, name="Дивидендный")
    with pytest.raises(PersonalPortfolioError) as exc:
        create_user_portfolio(mp_db, name="дивидендный")
    assert exc.value.code == "PORTFOLIO_NAME_EXISTS"
    delete_user_portfolio(mp_db, a)
    left = list_user_portfolios(mp_db)
    assert len(left) == 1
    assert left[0]["id"] == b.id
    assert left[0]["name"] == "ОФЗ"


def test_cash_and_asset_isolation(mp_db: Session, two_books):
    a, b = two_books
    sber = _mk_instrument(mp_db, symbol="SBER_MPV2")
    set_draft_cash(mp_db, a, Decimal("100000"))
    set_draft_cash(mp_db, b, Decimal("20000"))
    add_draft_position(
        mp_db, a, instrument_id=int(sber.id), units=Decimal("100"), average_price=Decimal("250"),
        non_standard_lot=True,
    )
    add_draft_position(
        mp_db, b, instrument_id=int(sber.id), units=Decimal("20"), average_price=Decimal("300"),
        non_standard_lot=True,
    )
    sa = load_personal_snapshot(mp_db, a)
    sb = load_personal_snapshot(mp_db, b)
    assert sa.cash_rub == Decimal("100000.000000")
    assert sb.cash_rub == Decimal("20000.000000")
    assert sa.positions[0].units == Decimal("100.00000000")
    assert sb.positions[0].units == Decimal("20.00000000")
    assert sa.positions[0].average_cost_rub == Decimal("250.000000")
    assert sb.positions[0].average_cost_rub == Decimal("300.000000")


def test_bond_unknown_cost_activate(mp_db: Session, two_books):
    a, _ = two_books
    bond = _mk_instrument(mp_db, symbol="OFZ_MPV2", asset_class="bond")
    set_draft_cash(mp_db, a, Decimal("50000"))
    add_draft_position(
        mp_db,
        a,
        instrument_id=int(bond.id),
        units=Decimal("10"),
        cost_basis_total_rub=None,
        non_standard_lot=True,
    )
    snap = load_personal_snapshot(mp_db, a)
    assert snap.positions[0].cost_basis_usable is False
    assert snap.positions[0].unrealized_pnl is None
    assert snap.investment_pnl_rub is None
    summary = activate_portfolio(mp_db, a)
    assert summary["portfolio"]["lifecycle_state"] == "ACTIVE"
    ops = list(
        mp_db.scalars(select(PersonalOperation).where(PersonalOperation.portfolio_id == a.id)).all()
    )
    opening_pos = [o for o in ops if o.operation_type == "OPENING_POSITION"]
    assert len(opening_pos) == 1
    assert opening_pos[0].price is None


def test_draft_clear_and_active_reject(mp_db: Session, two_books):
    a, _ = two_books
    sber = _mk_instrument(mp_db, symbol="SBER2_MPV2")
    set_draft_cash(mp_db, a, Decimal("1000"))
    add_draft_position(
        mp_db, a, instrument_id=int(sber.id), units=Decimal("5"), average_price=Decimal("10"),
        non_standard_lot=True,
    )
    clear_draft_portfolio(mp_db, a)
    snap = load_personal_snapshot(mp_db, a)
    assert snap.cash_rub == 0
    assert snap.positions == []
    activate_portfolio(mp_db, a)
    with pytest.raises(PersonalPortfolioError) as exc:
        set_draft_cash(mp_db, a, Decimal("1"))
    assert exc.value.code == "PORTFOLIO_NOT_DRAFT"


def test_active_ops_and_reset_isolation(mp_db: Session, two_books):
    a, b = two_books
    set_draft_cash(mp_db, a, Decimal("100000"))
    set_draft_cash(mp_db, b, Decimal("777"))
    activate_portfolio(mp_db, a)
    activate_portfolio(mp_db, b)
    create_operation(
        mp_db,
        portfolio=a,
        operation_type="DEPOSIT",
        occurred_at=datetime.now(UTC),
        amount=Decimal("30000"),
        idempotency_key="dep-a-1",
    )
    create_operation(
        mp_db,
        portfolio=b,
        operation_type="DEPOSIT",
        occurred_at=datetime.now(UTC),
        amount=Decimal("1000"),
        idempotency_key="dep-a-1",
    )
    sa = load_personal_snapshot(mp_db, a)
    sb = load_personal_snapshot(mp_db, b)
    assert sa.cash_rub == Decimal("130000.000000")
    assert sa.contributed_rub == Decimal("130000.000000")
    assert sb.cash_rub == Decimal("1777.000000")
    reset_portfolio(mp_db, a)
    assert a.status == "DRAFT"
    assert a.cash_rub == 0
    assert (
        list(mp_db.scalars(select(PersonalOperation).where(PersonalOperation.portfolio_id == a.id)))
        == []
    )
    sb2 = load_personal_snapshot(mp_db, b)
    assert sb2.cash_rub == Decimal("1777.000000")
    assert b.status == "ACTIVE"
    reset_portfolio(mp_db, a)
    assert a.status == "DRAFT"


def test_delete_does_not_touch_other(mp_db: Session, two_books):
    a, b = two_books
    set_draft_cash(mp_db, b, Decimal("42"))
    delete_user_portfolio(mp_db, a)
    remaining = mp_db.scalar(select(ManualPortfolio).where(ManualPortfolio.id == b.id))
    assert remaining is not None
    assert remaining.cash_rub == Decimal("42.000000")
    assert mp_db.scalar(select(ManualPortfolio).where(ManualPortfolio.id == a.id)) is None


def test_cross_book_draft_position_guard(mp_db: Session, two_books):
    """Position in book A cannot be patched or deleted via book B."""
    a, b = two_books
    sber = _mk_instrument(mp_db, symbol="ISO_POS_MPV2")
    pos = add_draft_position(
        mp_db,
        a,
        instrument_id=int(sber.id),
        units=Decimal("10"),
        average_price=Decimal("100"),
        non_standard_lot=True,
    )
    pid = int(pos.id)
    with pytest.raises(PersonalPortfolioError) as exc_patch:
        patch_draft_position(mp_db, b, pid, units=Decimal("5"))
    assert exc_patch.value.code == "POSITION_NOT_FOUND"
    with pytest.raises(PersonalPortfolioError) as exc_del:
        delete_draft_position(mp_db, b, pid)
    assert exc_del.value.code == "POSITION_NOT_FOUND"
    patch_draft_position(mp_db, a, pid, units=Decimal("8"))
    snap = load_personal_snapshot(mp_db, a)
    assert snap.positions[0].units == Decimal("8.00000000")


def test_operation_wrong_portfolio_context(mp_db: Session, two_books):
    a, b = two_books
    set_draft_cash(mp_db, a, Decimal("50000"))
    activate_portfolio(mp_db, a)
    activate_portfolio(mp_db, b)
    dep = create_operation(
        mp_db,
        portfolio=a,
        operation_type="DEPOSIT",
        occurred_at=datetime.now(UTC),
        amount=Decimal("1000"),
        idempotency_key="ctx-dep-a",
    )
    with pytest.raises(PersonalPortfolioError) as exc:
        cancel_operation(mp_db, portfolio=b, operation_id=int(dep.id), idempotency_key="ctx-cancel")
    assert exc.value.code == "OPERATION_NOT_FOUND"


def test_draft_edit_remove_equity_and_add_bond(mp_db: Session, two_books):
    a, _ = two_books
    sber = _mk_instrument(mp_db, symbol="DRFT_ED_MPV2")
    bond = _mk_instrument(mp_db, symbol="DRFT_BD_MPV2", asset_class="bond")
    pos = add_draft_position(
        mp_db,
        a,
        instrument_id=int(sber.id),
        units=Decimal("100"),
        average_price=Decimal("250"),
        non_standard_lot=True,
    )
    patch_draft_position(
        mp_db,
        a,
        int(pos.id),
        units=Decimal("80"),
        average_price=Decimal("260"),
    )
    snap = load_personal_snapshot(mp_db, a)
    assert snap.positions[0].units == Decimal("80.00000000")
    assert snap.positions[0].average_cost_rub == Decimal("260.000000")
    delete_draft_position(mp_db, a, int(pos.id))
    assert load_personal_snapshot(mp_db, a).positions == []
    add_draft_position(
        mp_db,
        a,
        instrument_id=int(bond.id),
        units=Decimal("5"),
        cost_basis_total_rub=Decimal("5125"),
        non_standard_lot=True,
    )
    bond_snap = load_personal_snapshot(mp_db, a).positions[0]
    assert bond_snap.units == Decimal("5.00000000")
    assert bond_snap.average_cost_rub == Decimal("1025.000000")
    assert bond_snap.cost_basis_usable is True


def test_activate_idempotent_no_duplicate_openings(mp_db: Session, two_books):
    a, _ = two_books
    sber = _mk_instrument(mp_db, symbol="IDMP_MPV2")
    set_draft_cash(mp_db, a, Decimal("1000"))
    add_draft_position(
        mp_db,
        a,
        instrument_id=int(sber.id),
        units=Decimal("3"),
        average_price=Decimal("10"),
        non_standard_lot=True,
    )
    first = activate_portfolio(mp_db, a)
    assert first["portfolio"]["lifecycle_state"] == "ACTIVE"
    n_ops = len(
        list(
            mp_db.scalars(
                select(PersonalOperation).where(PersonalOperation.portfolio_id == a.id)
            ).all()
        )
    )
    second = activate_portfolio(mp_db, a)
    assert second["portfolio"]["lifecycle_state"] == "ACTIVE"
    n_ops_after = len(
        list(
            mp_db.scalars(
                select(PersonalOperation).where(PersonalOperation.portfolio_id == a.id)
            ).all()
        )
    )
    assert n_ops_after == n_ops
    opening = [
        o
        for o in mp_db.scalars(
            select(PersonalOperation).where(PersonalOperation.portfolio_id == a.id)
        ).all()
        if o.operation_type == "OPENING_POSITION"
    ]
    assert len(opening) == 1


def test_active_equity_buy_sell_with_commission(mp_db: Session, two_books):
    a, _ = two_books
    sber = _mk_instrument(mp_db, symbol="TRD_MPV2")
    set_draft_cash(mp_db, a, Decimal("100000"))
    activate_portfolio(mp_db, a)
    create_operation(
        mp_db,
        portfolio=a,
        operation_type="BUY",
        occurred_at=datetime.now(UTC),
        instrument_id=int(sber.id),
        units=Decimal("10"),
        price=Decimal("250"),
        commission=Decimal("50"),
        non_standard_lot=True,
        idempotency_key="mpv2-buy-1",
    )
    snap = load_personal_snapshot(mp_db, a)
    assert snap.positions[0].units == Decimal("10.00000000")
    assert snap.cash_rub == Decimal("100000.000000") - Decimal("2500") - Decimal("50")
    create_operation(
        mp_db,
        portfolio=a,
        operation_type="SELL",
        occurred_at=datetime.now(UTC),
        instrument_id=int(sber.id),
        units=Decimal("4"),
        price=Decimal("260"),
        commission=Decimal("20"),
        non_standard_lot=True,
        idempotency_key="mpv2-sell-1",
    )
    snap2 = load_personal_snapshot(mp_db, a)
    assert snap2.positions[0].units == Decimal("6.00000000")
    assert snap2.cash_rub == snap.cash_rub + Decimal("1040") - Decimal("20")


def test_delete_portfolio_keeps_market_instrument(mp_db: Session, two_books):
    a, _ = two_books
    sber = _mk_instrument(mp_db, symbol="KEEP_INST_MPV2")
    iid = int(sber.id)
    set_draft_cash(mp_db, a, Decimal("1"))
    add_draft_position(
        mp_db,
        a,
        instrument_id=iid,
        units=Decimal("1"),
        average_price=Decimal("1"),
        non_standard_lot=True,
    )
    delete_user_portfolio(mp_db, a)
    assert mp_db.get(Instrument, iid) is not None


def test_daily_decision_includes_portfolio_identity(mp_db: Session, two_books):
    a, _ = two_books
    d = build_daily_personal_decision(mp_db, portfolio=a)
    assert d["portfolio"]["id"] == a.id
    assert d["portfolio"]["portfolio_id"] == a.id
    assert d["portfolio"]["name"] == a.name
    assert d["portfolio"]["portfolio_name"] == a.name


def test_list_cards_show_draft_lifecycle(mp_db: Session):
    book = create_user_portfolio(mp_db, name="Карточка DRAFT MPV2")
    cards = list_user_portfolios(mp_db)
    row = next(c for c in cards if c["id"] == book.id)
    assert row["lifecycle_state"] == "DRAFT"


def test_list_many_portfolios(mp_db: Session):
    for i in range(12):
        create_user_portfolio(mp_db, name=f"MPV2 bulk {i:02d}")
    assert len(list_user_portfolios(mp_db)) == 12
