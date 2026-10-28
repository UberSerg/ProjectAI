"""DEMO/TEST Investor Journey bootstrap — opt-in, idempotent, reversible."""

from __future__ import annotations

from collections.abc import Generator
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument
from app.modules.portfolio.application.demo_bootstrap_service import (
    bootstrap_demo_portfolio,
    demo_status,
    find_demo_portfolio,
    reset_demo_portfolio,
)
from app.modules.portfolio.application.personal_portfolio_service import PersonalPortfolioError
from app.modules.portfolio.application.user_portfolio_service import get_portfolio, list_user_portfolios
from app.modules.portfolio.domain.valuation import latest_eod_close
from app.modules.portfolio.infrastructure.models import ManualPosition, PersonalOperation
from tests.portfolio.mvp_helpers import make_equity, schema_ready


@pytest.fixture
def pp_db() -> Generator[Session, None, None]:
    try:
        from app.core.config import get_settings
        from app.infrastructure.db.session import get_core_engine

        get_settings.cache_clear()
        import app.infrastructure.db.session as db_session

        db_session._core_engine = None
        db_session._CoreSessionLocal = None
        engine = get_core_engine()
        connection = engine.connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"core database unavailable: {exc}")

    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    try:
        if not schema_ready(session):
            pytest.skip("personal_operations migration not applied")
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _master_or_skip(session: Session, symbols: tuple[str, ...]) -> dict[str, Instrument]:
    out: dict[str, Instrument] = {}
    for symbol in symbols:
        inst = make_equity(session, symbol, reuse_existing=True)
        close, _ = latest_eod_close(session, int(inst.id))
        if close is None:
            pytest.skip(f"{symbol} has no EOD close — refusing silent fake prices in DEMO test")
        out[symbol] = inst
    return out


def test_bootstrap_requires_confirm(pp_db: Session) -> None:
    with pytest.raises(PersonalPortfolioError) as ei:
        bootstrap_demo_portfolio(pp_db, confirm=False, name="DEMO — confirm gate")
    assert ei.value.code == "DEMO_CONFIRM_REQUIRED"
    assert find_demo_portfolio(pp_db, name="DEMO — confirm gate") is None


def test_bootstrap_resolves_by_symbol_never_hardcodes_ids(pp_db: Session) -> None:
    from app.modules.portfolio.application.demo_bootstrap_service import DEMO_SOURCE

    universe = _master_or_skip(pp_db, ("SBER", "LKOH", "MGNT"))
    candles_before = int(pp_db.scalar(select(func.count()).select_from(Candle)) or 0)
    name = "DEMO — symbol resolve V1"

    result = bootstrap_demo_portfolio(pp_db, confirm=True, activate=True, name=name)
    assert result.portfolio_id is not None
    assert result.is_test is True
    assert result.lifecycle_state == "ACTIVE"
    assert result.created is True
    assert result.source == DEMO_SOURCE
    assert {p["symbol"] for p in result.positions} == {"SBER", "LKOH", "MGNT"}
    for row in result.positions:
        assert row["instrument_id"] == int(universe[row["symbol"]].id)
        assert Decimal(row["average_price"]) > 0
        assert row["eod_as_of"] is not None

    candles_after = int(pp_db.scalar(select(func.count()).select_from(Candle)) or 0)
    assert candles_after == candles_before

    book = get_portfolio(pp_db, int(result.portfolio_id), allow_test=True)
    assert book.name == name
    assert book.source == DEMO_SOURCE
    assert book.is_test is True
    assert "DEMO" in (book.note or "")
    ops = list(
        pp_db.scalars(select(PersonalOperation).where(PersonalOperation.portfolio_id == book.id)).all()
    )
    assert any(o.operation_type == "OPENING_CASH" for o in ops)
    assert sum(1 for o in ops if o.operation_type == "OPENING_POSITION") == 3


def test_bootstrap_partial_when_symbol_or_price_missing(pp_db: Session) -> None:
    make_equity(pp_db, "MVPDBA", close=Decimal("280"), lot_size=10)
    make_equity(pp_db, "MVPDBB", close=None, lot_size=1)  # resolvable, no EOD
    # MVPDBc absent

    result = bootstrap_demo_portfolio(
        pp_db,
        confirm=True,
        activate=False,
        symbols=("MVPDBA", "MVPDBB", "MVPDBC"),
        name="DEMO — partial coverage",
    )
    assert {p["symbol"] for p in result.positions} == {"MVPDBA"}
    reasons = {s["symbol"]: s["reason"] for s in result.skipped}
    assert reasons["MVPDBB"] == "EOD_PRICE_MISSING"
    assert reasons["MVPDBC"] == "SYMBOL_NOT_IN_MASTER"
    assert any("refusing fake price" in w for w in result.warnings)


def test_bootstrap_unknown_lot_uses_non_standard_units(pp_db: Session) -> None:
    make_equity(pp_db, "MVPDL1", close=Decimal("100"), lot_size=None)
    make_equity(pp_db, "MVPDL2", close=Decimal("100"), lot_size=None)
    make_equity(pp_db, "MVPDL3", close=Decimal("100"), lot_size=None)

    result = bootstrap_demo_portfolio(
        pp_db,
        confirm=True,
        activate=True,
        symbols=("MVPDL1", "MVPDL2", "MVPDL3"),
        name="DEMO — unknown lots",
    )
    assert len(result.positions) == 3
    assert all(p["non_standard_lot"] is True for p in result.positions)
    assert any("LOT_SIZE_UNKNOWN" in w for w in result.warnings)


def test_bootstrap_idempotent_and_reset_reversible(pp_db: Session) -> None:
    _master_or_skip(pp_db, ("SBER", "LKOH", "MGNT"))
    name = "DEMO — idempotent reset V1"
    first = bootstrap_demo_portfolio(pp_db, confirm=True, name=name)
    pid = int(first.portfolio_id)
    ops_n = int(
        pp_db.scalar(
            select(func.count())
            .select_from(PersonalOperation)
            .where(PersonalOperation.portfolio_id == pid)
        )
        or 0
    )

    second = bootstrap_demo_portfolio(pp_db, confirm=True, name=name)
    assert second.status == "ALREADY_READY"
    assert second.portfolio_id == pid
    assert (
        int(
            pp_db.scalar(
                select(func.count())
                .select_from(PersonalOperation)
                .where(PersonalOperation.portfolio_id == pid)
            )
            or 0
        )
        == ops_n
    )

    rebuilt = bootstrap_demo_portfolio(pp_db, confirm=True, reset=True, name=name)
    assert rebuilt.reset is True
    assert rebuilt.portfolio_id == pid
    assert rebuilt.lifecycle_state == "ACTIVE"

    wiped = reset_demo_portfolio(pp_db, confirm=True, name=name)
    assert wiped["status"] == "RESET"
    book = get_portfolio(pp_db, pid, allow_test=True)
    assert (book.status or "").upper() == "DRAFT"
    assert Decimal(book.cash_rub) == 0
    assert (
        int(
            pp_db.scalar(
                select(func.count()).select_from(ManualPosition).where(ManualPosition.portfolio_id == pid)
            )
            or 0
        )
        == 0
    )

    deleted = reset_demo_portfolio(pp_db, confirm=True, delete=True, name=name)
    assert deleted["status"] == "DELETED"
    assert demo_status(pp_db, name=name)["status"] == "ABSENT"


def test_demo_hidden_from_default_collection_unless_ui_visible(pp_db: Session) -> None:
    make_equity(pp_db, "MVPDH1", close=Decimal("100"), lot_size=1)
    hidden = bootstrap_demo_portfolio(
        pp_db, confirm=True, name="DEMO — hidden A", symbols=("MVPDH1",)
    )
    assert hidden.is_test is True
    ids_default = {i["id"] for i in list_user_portfolios(pp_db, include_test=False)}
    assert hidden.portfolio_id not in ids_default
    ids_test = {i["id"] for i in list_user_portfolios(pp_db, include_test=True)}
    assert hidden.portfolio_id in ids_test

    make_equity(pp_db, "MVPDV1", close=Decimal("100"), lot_size=1)
    visible = bootstrap_demo_portfolio(
        pp_db, confirm=True, ui_visible=True, name="DEMO — visible B", symbols=("MVPDV1",)
    )
    assert visible.is_test is False
    ids_default2 = {i["id"] for i in list_user_portfolios(pp_db, include_test=False)}
    assert visible.portfolio_id in ids_default2


def test_api_resolve_allow_test_by_id() -> None:
    """Tiny shared contract: ?test=true means allow_test on the given id."""
    import inspect

    from app.api.v1 import personal_portfolios as api

    src = inspect.getsource(api._resolve)
    assert "get_or_create_test_portfolio" not in src
    assert "allow_test=test" in src


def test_demo_commands_refuse_ordinary_portfolio_name_collision(pp_db: Session) -> None:
    """Ordinary personal book with DEMO display name must never be reset/deleted/adopted."""
    from app.modules.portfolio.application.demo_bootstrap_service import DEMO_SOURCE
    from app.modules.portfolio.application.user_portfolio_service import (
        activate_portfolio,
        add_draft_position,
        create_user_portfolio,
        set_draft_cash,
    )

    collide_name = "DEMO — Collision Guard V1"
    inst = make_equity(pp_db, "MVPCOL1", close=Decimal("250"), lot_size=1)
    ordinary = create_user_portfolio(
        pp_db,
        name=collide_name,
        description="Real personal book - not DEMO",
        is_test=False,
    )
    assert ordinary.source == "MANUAL"
    assert ordinary.source != DEMO_SOURCE
    set_draft_cash(pp_db, ordinary, Decimal("777000"))
    add_draft_position(
        pp_db,
        ordinary,
        instrument_id=int(inst.id),
        units=Decimal("3"),
        lots=None,
        average_price=Decimal("250"),
        note="real holding",
        non_standard_lot=True,
    )
    activate_portfolio(pp_db, ordinary)
    pp_db.refresh(ordinary)

    cash_before = Decimal(ordinary.cash_rub)
    ops_before = list(
        pp_db.scalars(select(PersonalOperation).where(PersonalOperation.portfolio_id == ordinary.id)).all()
    )
    pos_before = list(
        pp_db.scalars(select(ManualPosition).where(ManualPosition.portfolio_id == ordinary.id)).all()
    )
    assert cash_before == Decimal("777000.000000") or cash_before == Decimal("777000")
    assert len(ops_before) >= 1
    assert len(pos_before) == 1
    identity = (int(ordinary.id), ordinary.name, ordinary.source, bool(ordinary.is_test))

    with pytest.raises(PersonalPortfolioError) as ei_boot:
        bootstrap_demo_portfolio(pp_db, confirm=True, reset=True, name=collide_name)
    assert ei_boot.value.code == "DEMO_NAME_COLLISION"

    # Reset/delete without a DEMO-sourced book must be a no-op (ABSENT), never mutate MANUAL.
    wiped = reset_demo_portfolio(pp_db, confirm=True, name=collide_name)
    assert wiped["status"] == "ABSENT"
    deleted = reset_demo_portfolio(pp_db, confirm=True, delete=True, name=collide_name)
    assert deleted["status"] == "ABSENT"

    pp_db.refresh(ordinary)
    assert (int(ordinary.id), ordinary.name, ordinary.source, bool(ordinary.is_test)) == identity
    assert Decimal(ordinary.cash_rub) == cash_before
    ops_after = list(
        pp_db.scalars(select(PersonalOperation).where(PersonalOperation.portfolio_id == ordinary.id)).all()
    )
    pos_after = list(
        pp_db.scalars(select(ManualPosition).where(ManualPosition.portfolio_id == ordinary.id)).all()
    )
    assert [o.id for o in ops_after] == [o.id for o in ops_before]
    assert [(p.id, p.units, p.instrument_id) for p in pos_after] == [
        (p.id, p.units, p.instrument_id) for p in pos_before
    ]
    status = demo_status(pp_db, name=collide_name)
    assert status["status"] == "DEMO_NAME_COLLISION"
    assert int(ordinary.id) in status["colliding_ids"]


def test_bootstrap_stamps_durable_demo_source(pp_db: Session) -> None:
    from app.modules.portfolio.application.demo_bootstrap_service import DEMO_SOURCE

    make_equity(pp_db, "MVPDS1", close=Decimal("100"), lot_size=1)
    result = bootstrap_demo_portfolio(
        pp_db, confirm=True, name="DEMO - source stamp", symbols=("MVPDS1",), activate=False
    )
    book = get_portfolio(pp_db, int(result.portfolio_id), allow_test=True)
    assert book.source == DEMO_SOURCE
    assert result.source == DEMO_SOURCE

def test_reclaim_legacy_refuses_similar_note_and_delete_combo(pp_db: Session) -> None:
    """Ordinary book with a similar DEMO-like note must never be reclaimed or deleted."""
    from app.modules.portfolio.application.demo_bootstrap_service import DEMO_SOURCE
    from app.modules.portfolio.application.user_portfolio_service import create_user_portfolio

    name = "DEMO — lookalike note V1"
    ordinary = create_user_portfolio(
        pp_db,
        name=name,
        description=(
            "DEMO/TEST — Investor Journey V1 seed. "
            "This is my real personal book, not a fixture."
        ),
        is_test=False,
    )
    assert ordinary.source == "MANUAL"
    oid = int(ordinary.id)

    with pytest.raises(PersonalPortfolioError) as ei_boot:
        bootstrap_demo_portfolio(pp_db, confirm=True, name=name, reclaim_legacy=True)
    assert ei_boot.value.code == "DEMO_NAME_COLLISION"

    with pytest.raises(PersonalPortfolioError) as ei_del:
        reset_demo_portfolio(pp_db, confirm=True, name=name, delete=True, reclaim_legacy=True)
    assert ei_del.value.code == "DEMO_RECLAIM_DELETE_FORBIDDEN"

    # Soft reclaim without delete still must not stamp/adopt the lookalike.
    absent = reset_demo_portfolio(pp_db, confirm=True, name=name, reclaim_legacy=True)
    assert absent["status"] == "ABSENT"

    pp_db.refresh(ordinary)
    assert int(ordinary.id) == oid
    assert ordinary.source == "MANUAL"
    assert ordinary.source != DEMO_SOURCE
