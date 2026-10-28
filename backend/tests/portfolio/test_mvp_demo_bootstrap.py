"""DEMO/TEST Investor Journey bootstrap — opt-in, idempotent, reversible."""

from __future__ import annotations

from collections.abc import Generator
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument
from app.modules.portfolio.application.demo_bootstrap_service import (
    DEMO_PORTFOLIO_NAME,
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
        bootstrap_demo_portfolio(pp_db, confirm=False)
    assert ei.value.code == "DEMO_CONFIRM_REQUIRED"
    assert find_demo_portfolio(pp_db) is None


def test_bootstrap_resolves_by_symbol_never_hardcodes_ids(pp_db: Session) -> None:
    universe = _master_or_skip(pp_db, ("SBER", "LKOH", "MGNT"))
    candles_before = int(pp_db.scalar(select(func.count()).select_from(Candle)) or 0)

    result = bootstrap_demo_portfolio(pp_db, confirm=True, activate=True)
    assert result.portfolio_id is not None
    assert result.is_test is True
    assert result.lifecycle_state == "ACTIVE"
    assert result.created is True
    assert {p["symbol"] for p in result.positions} == {"SBER", "LKOH", "MGNT"}
    for row in result.positions:
        assert row["instrument_id"] == int(universe[row["symbol"]].id)
        assert Decimal(row["average_price"]) > 0
        assert row["eod_as_of"] is not None

    candles_after = int(pp_db.scalar(select(func.count()).select_from(Candle)) or 0)
    assert candles_after == candles_before

    book = get_portfolio(pp_db, int(result.portfolio_id), allow_test=True)
    assert book.name == DEMO_PORTFOLIO_NAME
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
    first = bootstrap_demo_portfolio(pp_db, confirm=True)
    pid = int(first.portfolio_id)
    ops_n = int(
        pp_db.scalar(
            select(func.count())
            .select_from(PersonalOperation)
            .where(PersonalOperation.portfolio_id == pid)
        )
        or 0
    )

    second = bootstrap_demo_portfolio(pp_db, confirm=True)
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

    rebuilt = bootstrap_demo_portfolio(pp_db, confirm=True, reset=True)
    assert rebuilt.reset is True
    assert rebuilt.portfolio_id == pid
    assert rebuilt.lifecycle_state == "ACTIVE"

    wiped = reset_demo_portfolio(pp_db, confirm=True)
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

    deleted = reset_demo_portfolio(pp_db, confirm=True, delete=True)
    assert deleted["status"] == "DELETED"
    assert demo_status(pp_db)["status"] == "ABSENT"


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
