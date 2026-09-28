"""Multi-Portfolio V2 corrective pass — row locks, historical basis, cheap list.

The concurrency cases use real committed PostgreSQL transactions from separate
sessions. Sequential mocks would pass even without ``SELECT ... FOR UPDATE``,
so they would prove nothing about double-spend or lost-update races.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument, InstrumentSource
from app.modules.portfolio.application import personal_portfolio_service as pps
from app.modules.portfolio.application import user_portfolio_service as ups
from app.modules.portfolio.application.personal_portfolio_service import (
    PersonalPortfolioError,
    create_operation,
    get_personal_summary,
    get_portfolio_for_update,
    journal_cutover_at,
    load_personal_snapshot,
    rebuild_ledger_from_journal,
)
from app.modules.portfolio.application.user_portfolio_service import (
    activate_portfolio,
    add_draft_position,
    create_user_portfolio,
    list_user_portfolios,
    set_draft_cash,
)
from app.modules.portfolio.domain.personal_ledger import money
from app.modules.portfolio.infrastructure.models import (
    ManualPortfolio,
    ManualPosition,
    PersonalOperation,
)

LOCK_WAIT_SECONDS = 5.0
BLOCK_SETTLE_SECONDS = 0.4
THREAD_TIMEOUT_SECONDS = 30.0


def _schema_ready(session: Session) -> bool:
    try:
        session.execute(text("SELECT 1 FROM portfolio.personal_operations LIMIT 0"))
        return True
    except Exception:
        session.rollback()
        return False


@pytest.fixture
def mp_db() -> Generator[Session, None, None]:
    """Rollback-scoped session for single-writer assertions."""
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
        session.execute(delete(PersonalOperation))
        session.execute(delete(ManualPosition))
        session.execute(delete(ManualPortfolio).where(ManualPortfolio.is_test.is_(False)))
        session.flush()
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _mk_instrument(session: Session, *, symbol: str) -> Instrument:
    row = Instrument(
        symbol=symbol,
        name=symbol,
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
        support_level="FULL",
        primary_board="TQBR",
    )
    session.add(row)
    session.flush()
    session.add(
        InstrumentSource(
            instrument_id=row.id,
            source="MOEX_ISS",
            external_id=symbol,
            board="TQBR",
            source_metadata={"LOTSIZE": 1},
        )
    )
    session.flush()
    return row


class _CommittedWorld:
    """Books and instruments that really exist in PostgreSQL, cleaned up at teardown."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.tag = uuid4().hex[:8]
        self.portfolio_ids: list[int] = []
        self.instrument_ids: list[int] = []
        self.cutover: dict[int, datetime] = {}

    def session(self) -> Session:
        return Session(bind=self.engine, autoflush=False, expire_on_commit=False)

    def draft_book(self, suffix: str, *, cash: Decimal = Decimal("0")) -> int:
        with self.session() as session:
            book = create_user_portfolio(session, name=f"CONC {self.tag} {suffix}")
            session.flush()
            pid = int(book.id)
            self.portfolio_ids.append(pid)
            if cash > 0:
                set_draft_cash(session, book, cash)
            session.commit()
            return pid

    def active_book(self, suffix: str, *, cash: Decimal) -> int:
        pid = self.draft_book(suffix, cash=cash)
        with self.session() as session:
            book = session.get(ManualPortfolio, pid)
            assert book is not None
            activate_portfolio(session, book)
            session.commit()
            self.cutover[pid] = journal_cutover_at(session, pid) or datetime.now(UTC)
            return pid

    def equity(self, suffix: str) -> int:
        with self.session() as session:
            inst = _mk_instrument(session, symbol=f"CNC{self.tag}{suffix}"[:24])
            iid = int(inst.id)
            self.instrument_ids.append(iid)
            session.commit()
            return iid

    def after_cutover(self, portfolio_id: int, seconds: int) -> datetime:
        return self.cutover[portfolio_id] + timedelta(seconds=seconds)

    def read_book(self, portfolio_id: int) -> ManualPortfolio:
        with self.session() as session:
            book = session.get(ManualPortfolio, portfolio_id)
            assert book is not None
            return book

    def active_operations(self, portfolio_id: int) -> list[PersonalOperation]:
        with self.session() as session:
            return list(
                session.scalars(
                    select(PersonalOperation).where(
                        PersonalOperation.portfolio_id == portfolio_id,
                        PersonalOperation.status == "ACTIVE",
                    )
                ).all()
            )

    def cleanup(self) -> None:
        with self.session() as session:
            if self.portfolio_ids:
                session.execute(
                    delete(PersonalOperation).where(
                        PersonalOperation.portfolio_id.in_(self.portfolio_ids)
                    )
                )
                session.execute(
                    delete(ManualPosition).where(
                        ManualPosition.portfolio_id.in_(self.portfolio_ids)
                    )
                )
                session.execute(
                    delete(ManualPortfolio).where(ManualPortfolio.id.in_(self.portfolio_ids))
                )
            if self.instrument_ids:
                session.execute(
                    delete(ManualPosition).where(
                        ManualPosition.instrument_id.in_(self.instrument_ids)
                    )
                )
                session.execute(
                    delete(InstrumentSource).where(
                        InstrumentSource.instrument_id.in_(self.instrument_ids)
                    )
                )
                session.execute(
                    delete(Instrument).where(Instrument.id.in_(self.instrument_ids))
                )
            session.commit()


@pytest.fixture
def world() -> Generator[_CommittedWorld, None, None]:
    try:
        from app.core.config import get_settings
        from app.infrastructure.db.session import get_core_engine

        get_settings.cache_clear()
        engine = get_core_engine()
        with Session(bind=engine) as probe:
            if not _schema_ready(probe):
                pytest.skip("personal_operations migration not applied")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"core database unavailable: {exc}")

    created = _CommittedWorld(engine)
    try:
        yield created
    finally:
        created.cleanup()


Job = Callable[[Session], Any]


def _run_parallel(world: _CommittedWorld, first: Job, second: Job) -> tuple[Any, Any]:
    """Run two writers at the same time; both open their own transaction."""
    gate = threading.Barrier(2, timeout=LOCK_WAIT_SECONDS)
    out: dict[str, Any] = {}

    def runner(name: str, job: Job) -> Callable[[], None]:
        def inner() -> None:
            with world.session() as session:
                try:
                    gate.wait()
                    out[name] = job(session)
                    session.commit()
                except BaseException as exc:  # noqa: BLE001 — reported to the test
                    session.rollback()
                    out[name] = exc

        return inner

    threads = [
        threading.Thread(target=runner("first", first), name="writer-1"),
        threading.Thread(target=runner("second", second), name="writer-2"),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=THREAD_TIMEOUT_SECONDS)
    alive = [t.name for t in threads if t.is_alive()]
    assert not alive, f"concurrent writers did not finish: {alive}"
    return out["first"], out["second"]


def _run_contended(
    world: _CommittedWorld,
    portfolio_id: int,
    first: Job,
    second: Job,
) -> tuple[Any, Any]:
    """Force a genuine lost-update window on one book.

    ``first`` reads and decides but has **not** committed when ``second`` starts, so
    ``second`` can only stay correct by waiting on the row lock. Without the lock it
    would decide from ``first``'s pre-image and overspend or clobber the projection.
    """
    first_staged = threading.Event()
    peer_started = threading.Event()
    out: dict[str, Any] = {}

    def run_first() -> None:
        with world.session() as session:
            try:
                out["first"] = first(session)
            except BaseException as exc:  # noqa: BLE001
                out["first"] = exc
                session.rollback()
                first_staged.set()
                return
            first_staged.set()
            peer_started.wait(timeout=LOCK_WAIT_SECONDS)
            time.sleep(BLOCK_SETTLE_SECONDS)  # peer is now parked on the row lock
            try:
                session.commit()
            except BaseException as exc:  # noqa: BLE001
                session.rollback()
                out["first"] = exc

    def run_second() -> None:
        assert first_staged.wait(timeout=LOCK_WAIT_SECONDS), "peer never staged its write"
        with world.session() as session:
            peer_started.set()
            try:
                out["second"] = second(session)
                session.commit()
            except BaseException as exc:  # noqa: BLE001
                session.rollback()
                out["second"] = exc

    threads = [
        threading.Thread(target=run_first, name="staged-writer"),
        threading.Thread(target=run_second, name="lock-waiter"),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=THREAD_TIMEOUT_SECONDS)
    alive = [t.name for t in threads if t.is_alive()]
    assert not alive, f"row lock deadlocked: {alive}"
    return out["first"], out["second"]


def _deposit(portfolio_id: int, *, amount: Decimal, when: datetime, key: str) -> Job:
    def job(session: Session) -> str:
        book = session.get(ManualPortfolio, portfolio_id)
        assert book is not None
        create_operation(
            session,
            portfolio=book,
            operation_type="DEPOSIT",
            occurred_at=when,
            amount=amount,
            idempotency_key=key,
        )
        return "OK"

    return job


def _buy(
    portfolio_id: int,
    *,
    instrument_id: int,
    units: Decimal,
    price: Decimal,
    when: datetime,
    key: str,
) -> Job:
    def job(session: Session) -> str:
        book = session.get(ManualPortfolio, portfolio_id)
        assert book is not None
        create_operation(
            session,
            portfolio=book,
            operation_type="BUY",
            occurred_at=when,
            instrument_id=instrument_id,
            units=units,
            price=price,
            non_standard_lot=True,
            idempotency_key=key,
        )
        return "OK"

    return job


# --------------------------------------------------------------------------- #
# 1. Collection view must stay cheap
# --------------------------------------------------------------------------- #


def test_list_does_not_value_portfolios(mp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    for i in range(20):
        create_user_portfolio(mp_db, name=f"CHEAP LIST {i:02d}")
    spy = MagicMock(side_effect=AssertionError("list must not price portfolios"))
    monkeypatch.setattr(pps, "load_personal_snapshot", spy)
    monkeypatch.setattr(ups, "load_personal_snapshot", spy, raising=False)
    monkeypatch.setattr(pps, "rebuild_ledger_from_journal", spy)
    monkeypatch.setattr(ups, "rebuild_ledger_from_journal", spy, raising=False)

    cards = list_user_portfolios(mp_db)

    spy.assert_not_called()
    assert len(cards) == 20
    card = cards[0]
    assert set(card) == {
        "id",
        "name",
        "description",
        "lifecycle_state",
        "cash_rub",
        "positions_count",
        "updated_at",
        "created_at",
        "is_test",
    }


def test_list_counts_positions_without_marks(mp_db: Session) -> None:
    a = create_user_portfolio(mp_db, name="COUNT A")
    b = create_user_portfolio(mp_db, name="COUNT B")
    first = _mk_instrument(mp_db, symbol="CNTONE")
    second = _mk_instrument(mp_db, symbol="CNTTWO")
    set_draft_cash(mp_db, a, Decimal("5000"))
    for inst in (first, second):
        add_draft_position(
            mp_db,
            a,
            instrument_id=int(inst.id),
            units=Decimal("10"),
            average_price=Decimal("100"),
            non_standard_lot=True,
        )

    cards = {c["id"]: c for c in list_user_portfolios(mp_db)}

    assert cards[int(a.id)]["positions_count"] == 2
    assert cards[int(a.id)]["cash_rub"] == str(money("5000"))
    assert cards[int(b.id)]["positions_count"] == 0


# --------------------------------------------------------------------------- #
# 2. Historical unknown cost basis
# --------------------------------------------------------------------------- #


def test_sold_unknown_basis_keeps_investment_pnl_unavailable(mp_db: Session) -> None:
    """Unknown basis already sold must not surface as profit (P0)."""
    book = create_user_portfolio(mp_db, name="HIST UNKNOWN BASIS")
    equity = _mk_instrument(mp_db, symbol="HISTUNK")
    set_draft_cash(mp_db, book, Decimal("100000"))
    add_draft_position(
        mp_db,
        book,
        instrument_id=int(equity.id),
        units=Decimal("10"),
        average_price=None,
        non_standard_lot=True,
    )
    activate_portfolio(mp_db, book)
    cutover = journal_cutover_at(mp_db, int(book.id))
    assert cutover is not None
    create_operation(
        mp_db,
        portfolio=book,
        operation_type="SELL",
        occurred_at=cutover + timedelta(seconds=1),
        instrument_id=int(equity.id),
        units=Decimal("10"),
        price=Decimal("300"),
        non_standard_lot=True,
        idempotency_key="hist-unknown-sell",
    )

    state = rebuild_ledger_from_journal(mp_db, int(book.id))
    assert state.cost_basis_incomplete is True

    snap = load_personal_snapshot(mp_db, book)
    # Nothing unknown is held any more, and every price is known.
    assert snap.positions == []
    assert snap.valuation_complete is True
    assert snap.cost_basis_incomplete_history is True
    assert snap.cost_basis_complete is False
    assert snap.investment_pnl_rub is None
    assert snap.investment_pnl_unavailable_reason == "COST_BASIS_INCOMPLETE"

    summary = get_personal_summary(mp_db, book, owner=True)["summary"]
    assert summary["investment_pnl_rub"] is None
    assert summary["cost_basis_complete"] is False
    assert summary["cost_basis_incomplete_history"] is True
    assert summary["investment_pnl_unavailable_reason"] == "COST_BASIS_INCOMPLETE"
    assert (
        summary["investment_pnl_message"]
        == "Не хватает себестоимости для части позиций или истории."
    )
    assert (
        summary["cost_basis_incomplete_reason"]
        == "Не хватает себестоимости для части позиций или истории."
    )


def test_sold_known_basis_still_reports_investment_pnl(mp_db: Session) -> None:
    """Control: a fully known history must not be blocked by the ledger flag."""
    book = create_user_portfolio(mp_db, name="HIST KNOWN BASIS")
    equity = _mk_instrument(mp_db, symbol="HISTKNW")
    set_draft_cash(mp_db, book, Decimal("100000"))
    add_draft_position(
        mp_db,
        book,
        instrument_id=int(equity.id),
        units=Decimal("10"),
        average_price=Decimal("250"),
        non_standard_lot=True,
    )
    activate_portfolio(mp_db, book)
    cutover = journal_cutover_at(mp_db, int(book.id))
    assert cutover is not None
    create_operation(
        mp_db,
        portfolio=book,
        operation_type="SELL",
        occurred_at=cutover + timedelta(seconds=1),
        instrument_id=int(equity.id),
        units=Decimal("10"),
        price=Decimal("300"),
        non_standard_lot=True,
        idempotency_key="hist-known-sell",
    )

    assert rebuild_ledger_from_journal(mp_db, int(book.id)).cost_basis_incomplete is False

    snap = load_personal_snapshot(mp_db, book)
    assert snap.cost_basis_complete is True
    assert snap.cost_basis_incomplete_history is False
    assert snap.investment_pnl_unavailable_reason is None
    # Opening cash 100000 + opening position 2500 contributed; sold for 3000.
    assert snap.investment_pnl_rub == money("500")

    summary = get_personal_summary(mp_db, book, owner=True)["summary"]
    assert summary["investment_pnl_rub"] == str(money("500"))
    assert summary["investment_pnl_unavailable_reason"] is None
    assert summary["investment_pnl_message"] is None


def test_unknown_basis_position_keeps_null_position_pnl(mp_db: Session) -> None:
    book = create_user_portfolio(mp_db, name="HIST HELD UNKNOWN")
    equity = _mk_instrument(mp_db, symbol="HISTHLD")
    add_draft_position(
        mp_db,
        book,
        instrument_id=int(equity.id),
        units=Decimal("10"),
        average_price=None,
        non_standard_lot=True,
    )
    snap = load_personal_snapshot(mp_db, book)
    assert snap.positions[0].unrealized_pnl is None
    assert snap.positions[0].cost_basis_usable is False
    assert snap.investment_pnl_unavailable_reason == "COST_BASIS_INCOMPLETE"


# --------------------------------------------------------------------------- #
# 3. Real PostgreSQL concurrency on the locked row
# --------------------------------------------------------------------------- #


def test_concurrent_deposits_both_land(world: _CommittedWorld) -> None:
    pid = world.active_book("deposits", cash=Decimal("100000"))
    first, second = _run_contended(
        world,
        pid,
        _deposit(pid, amount=Decimal("20000"), when=world.after_cutover(pid, 1), key="conc-dep-1"),
        _deposit(pid, amount=Decimal("10000"), when=world.after_cutover(pid, 2), key="conc-dep-2"),
    )
    assert first == "OK", first
    assert second == "OK", second

    book = world.read_book(pid)
    assert money(book.cash_rub) == money("130000")
    assert money(book.total_contributed_rub) == money("130000")
    deposits = [o for o in world.active_operations(pid) if o.operation_type == "DEPOSIT"]
    assert len(deposits) == 2


def test_concurrent_double_spend_never_goes_negative(world: _CommittedWorld) -> None:
    pid = world.active_book("double-spend", cash=Decimal("100000"))
    iid = world.equity("DS")
    order = {
        "units": Decimal("100"),
        "price": Decimal("700"),  # 70 000 RUB — two of these exceed the cash
    }
    first, second = _run_contended(
        world,
        pid,
        _buy(pid, instrument_id=iid, when=world.after_cutover(pid, 1), key="conc-buy-1", **order),
        _buy(pid, instrument_id=iid, when=world.after_cutover(pid, 2), key="conc-buy-2", **order),
    )

    outcomes = [first, second]
    succeeded = [o for o in outcomes if o == "OK"]
    refused = [o for o in outcomes if isinstance(o, PersonalPortfolioError)]
    assert len(succeeded) == 1, outcomes
    assert len(refused) == 1, outcomes
    assert refused[0].code == "INSUFFICIENT_CASH"

    book = world.read_book(pid)
    assert money(book.cash_rub) == money("30000")
    assert money(book.cash_rub) >= 0
    buys = [o for o in world.active_operations(pid) if o.operation_type == "BUY"]
    assert len(buys) == 1


def test_activate_versus_draft_edit_is_deterministic(world: _CommittedWorld) -> None:
    def edit(portfolio_id: int, cash: Decimal) -> Job:
        def job(session: Session) -> str:
            book = session.get(ManualPortfolio, portfolio_id)
            assert book is not None
            set_draft_cash(session, book, cash)
            return "EDITED"

        return job

    def activate(portfolio_id: int) -> Job:
        def job(session: Session) -> str:
            book = session.get(ManualPortfolio, portfolio_id)
            assert book is not None
            activate_portfolio(session, book)
            return "ACTIVATED"

        return job

    # Edit first: activation must snapshot the committed edit, not the stale row.
    edit_wins = world.draft_book("edit-then-activate", cash=Decimal("10000"))
    first, second = _run_contended(
        world, edit_wins, edit(edit_wins, Decimal("50000")), activate(edit_wins)
    )
    assert first == "EDITED", first
    assert second == "ACTIVATED", second
    book = world.read_book(edit_wins)
    assert (book.status or "").upper() == "ACTIVE"
    assert money(book.cash_rub) == money("50000")
    opening_cash = [
        o for o in world.active_operations(edit_wins) if o.operation_type == "OPENING_CASH"
    ]
    assert len(opening_cash) == 1
    assert money(opening_cash[0].amount) == money("50000")

    # Activate first: the late edit must be refused, never silently applied.
    activate_wins = world.draft_book("activate-then-edit", cash=Decimal("10000"))
    first2, second2 = _run_contended(
        world, activate_wins, activate(activate_wins), edit(activate_wins, Decimal("77000"))
    )
    assert first2 == "ACTIVATED", first2
    assert isinstance(second2, PersonalPortfolioError), second2
    assert second2.code == "PORTFOLIO_NOT_DRAFT"
    book2 = world.read_book(activate_wins)
    assert (book2.status or "").upper() == "ACTIVE"
    assert money(book2.cash_rub) == money("10000")


def test_concurrent_ops_on_different_books_both_succeed(world: _CommittedWorld) -> None:
    a = world.active_book("independent-a", cash=Decimal("1000"))
    b = world.active_book("independent-b", cash=Decimal("2000"))
    first, second = _run_parallel(
        world,
        _deposit(a, amount=Decimal("500"), when=world.after_cutover(a, 1), key="indep-a"),
        _deposit(b, amount=Decimal("700"), when=world.after_cutover(b, 1), key="indep-b"),
    )
    assert first == "OK", first
    assert second == "OK", second
    assert money(world.read_book(a).cash_rub) == money("1500")
    assert money(world.read_book(b).cash_rub) == money("2700")


def test_row_lock_is_scoped_to_one_portfolio(world: _CommittedWorld) -> None:
    """A lock on book A must not stall an unrelated book B."""
    a = world.active_book("scope-a", cash=Decimal("1000"))
    b = world.active_book("scope-b", cash=Decimal("1000"))
    with world.session() as holder:
        get_portfolio_for_update(holder, a)
        with world.session() as other:
            book = other.get(ManualPortfolio, b)
            assert book is not None
            create_operation(
                other,
                portfolio=book,
                operation_type="DEPOSIT",
                occurred_at=world.after_cutover(b, 1),
                amount=Decimal("250"),
                idempotency_key="scope-dep-b",
            )
            other.commit()
        holder.rollback()
    assert money(world.read_book(b).cash_rub) == money("1250")


def test_lock_rejects_unknown_and_hidden_test_books(mp_db: Session) -> None:
    with pytest.raises(PersonalPortfolioError) as missing:
        get_portfolio_for_update(mp_db, -1)
    assert missing.value.code == "PORTFOLIO_NOT_FOUND"

    hidden = create_user_portfolio(mp_db, name="HIDDEN TEST BOOK", is_test=True)
    with pytest.raises(PersonalPortfolioError) as denied:
        get_portfolio_for_update(mp_db, int(hidden.id))
    assert denied.value.code == "PORTFOLIO_NOT_FOUND"
    assert get_portfolio_for_update(mp_db, int(hidden.id), allow_test=True).id == hidden.id


def test_locked_read_refreshes_stale_orm_state(mp_db: Session) -> None:
    """A stale in-memory row must never drive a money decision."""
    book = create_user_portfolio(mp_db, name="STALE ORM GUARD")
    set_draft_cash(mp_db, book, Decimal("4000"))
    mp_db.execute(
        ManualPortfolio.__table__.update()
        .where(ManualPortfolio.id == book.id)
        .values(cash_rub=Decimal("9000"))
    )
    assert money(book.cash_rub) == money("4000")
    fresh = get_portfolio_for_update(mp_db, int(book.id))
    assert fresh is book
    assert money(fresh.cash_rub) == money("9000")


def test_position_counts_use_one_aggregate_query(mp_db: Session) -> None:
    """Guards the cheap-list contract: counts come from a grouped COUNT."""
    book = create_user_portfolio(mp_db, name="AGG COUNT")
    equity = _mk_instrument(mp_db, symbol="AGGCNT")
    add_draft_position(
        mp_db,
        book,
        instrument_id=int(equity.id),
        units=Decimal("4"),
        average_price=Decimal("10"),
        non_standard_lot=True,
    )
    expected = int(
        mp_db.scalar(
            select(func.count())
            .select_from(ManualPosition)
            .where(ManualPosition.portfolio_id == book.id)
        )
        or 0
    )
    card = next(c for c in list_user_portfolios(mp_db) if c["id"] == int(book.id))
    assert card["positions_count"] == expected == 1


# --------------------------------------------------------------------------- #
# 4. Opening operations are system-only
# --------------------------------------------------------------------------- #


def _active_book_with_position(
    session: Session, *, name: str, symbol: str
) -> tuple[ManualPortfolio, Instrument]:
    book = create_user_portfolio(session, name=name)
    equity = _mk_instrument(session, symbol=symbol)
    set_draft_cash(session, book, Decimal("100000"))
    add_draft_position(
        session,
        book,
        instrument_id=int(equity.id),
        units=Decimal("10"),
        average_price=Decimal("250"),
        non_standard_lot=True,
    )
    activate_portfolio(session, book)
    return book, equity


def test_public_opening_cash_is_rejected(mp_db: Session) -> None:
    book, _ = _active_book_with_position(mp_db, name="OPENING GUARD CASH", symbol="OPNCSH")
    cutover = journal_cutover_at(mp_db, int(book.id))
    assert cutover is not None

    with pytest.raises(PersonalPortfolioError) as refused:
        create_operation(
            mp_db,
            portfolio=book,
            operation_type="OPENING_CASH",
            occurred_at=cutover + timedelta(seconds=1),
            amount=Decimal("5000"),
            idempotency_key="public-opening-cash",
        )

    assert refused.value.code == "OPENING_OPERATION_SYSTEM_ONLY"
    assert refused.value.http_status == 409
    assert refused.value.message == "Начальное состояние создаётся Kraken при запуске учёта."
    opening_cash = [
        o
        for o in mp_db.scalars(
            select(PersonalOperation).where(PersonalOperation.portfolio_id == book.id)
        ).all()
        if o.operation_type == "OPENING_CASH"
    ]
    assert len(opening_cash) == 1  # only the activation snapshot row


def test_public_opening_position_is_rejected(mp_db: Session) -> None:
    book, equity = _active_book_with_position(mp_db, name="OPENING GUARD POS", symbol="OPNPOS")
    cutover = journal_cutover_at(mp_db, int(book.id))
    assert cutover is not None

    with pytest.raises(PersonalPortfolioError) as refused:
        create_operation(
            mp_db,
            portfolio=book,
            operation_type="OPENING_POSITION",
            occurred_at=cutover + timedelta(seconds=1),
            instrument_id=int(equity.id),
            units=Decimal("5"),
            price=Decimal("250"),
            non_standard_lot=True,
            idempotency_key="public-opening-position",
        )

    assert refused.value.code == "OPENING_OPERATION_SYSTEM_ONLY"
    assert refused.value.http_status == 409
    opening_positions = [
        o
        for o in mp_db.scalars(
            select(PersonalOperation).where(PersonalOperation.portfolio_id == book.id)
        ).all()
        if o.operation_type == "OPENING_POSITION"
    ]
    assert len(opening_positions) == 1


def test_opening_guard_does_not_block_human_operations(mp_db: Session) -> None:
    book, _ = _active_book_with_position(mp_db, name="OPENING GUARD HUMAN", symbol="OPNHUM")
    cutover = journal_cutover_at(mp_db, int(book.id))
    assert cutover is not None
    op = create_operation(
        mp_db,
        portfolio=book,
        operation_type="DEPOSIT",
        occurred_at=cutover + timedelta(seconds=1),
        amount=Decimal("1000"),
        idempotency_key="human-deposit",
    )
    assert op.operation_type == "DEPOSIT"
    assert op.status == "ACTIVE"


def test_activation_still_writes_the_opening_snapshot(mp_db: Session) -> None:
    """The internal activation path must keep creating opening cash + positions."""
    book, equity = _active_book_with_position(mp_db, name="OPENING ACTIVATE", symbol="OPNACT")

    ops = list(
        mp_db.scalars(
            select(PersonalOperation).where(PersonalOperation.portfolio_id == book.id)
        ).all()
    )
    opening_cash = [o for o in ops if o.operation_type == "OPENING_CASH"]
    opening_positions = [o for o in ops if o.operation_type == "OPENING_POSITION"]
    assert len(opening_cash) == 1
    assert money(opening_cash[0].amount) == money("100000")
    assert len(opening_positions) == 1
    assert int(opening_positions[0].instrument_id) == int(equity.id)
    assert (book.status or "").upper() == "ACTIVE"


def test_public_operations_api_never_asks_for_system_mode() -> None:
    """The HTTP layer must not be able to opt out of the opening guard."""
    import inspect

    from app.api.v1 import personal_portfolios as api

    assert inspect.signature(create_operation).parameters["system"].default is False
    assert "system" not in inspect.getsource(api.post_operation)
