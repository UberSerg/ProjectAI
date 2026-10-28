"""MVP Investor Journey — backend reliability invariants (focused).

Covers: hypothetical cash immutability, decision fingerprint, memory idempotency,
portfolio isolation, no execution writes, and backend failure modes that belong
in Decision V2 / journal (empty, missing quote, stale candidate, unknown lot,
bond execution unavailable, duplicate save, isolation).
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.modules.portfolio.application.daily_personal_decision_service import (
    ENGINE_VERSION,
    build_daily_personal_decision,
)
from app.modules.portfolio.application.personal_portfolio_service import (
    PersonalPortfolioError,
    create_operation,
    journal_operation_count,
    load_personal_snapshot,
)
from app.modules.portfolio.application.user_portfolio_service import create_user_portfolio
from app.modules.portfolio.domain.decision_identity import decision_fingerprint
from app.modules.portfolio.domain.personal_ledger import money
from app.modules.portfolio.infrastructure.models import ManualPosition, PersonalOperation
from tests.portfolio.mvp_helpers import make_bond, make_equity, schema_ready, stub_decision_deps, wipe_portfolio


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


def _fund(session: Session, name: str, *, symbol: str, cash: Decimal, units: Decimal, price: Decimal):
    portfolio = wipe_portfolio(session, name)
    eq = make_equity(session, symbol, close=price, lot_size=1)
    create_operation(
        session,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=cash,
        idempotency_key=f"{name}-dep",
    )
    create_operation(
        session,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq.id,
        units=units,
        price=price,
        non_standard_lot=True,
        idempotency_key=f"{name}-buy",
    )
    return portfolio, eq


def test_hypothetical_cash_does_not_mutate_portfolio(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio, eq = _fund(
        pp_db, "TEST — MVP cash", symbol="MVPCSH", cash=Decimal("100000"), units=Decimal("10"), price=Decimal("100")
    )
    stub_decision_deps(
        monkeypatch,
        positions=[{"symbol": "MVPCSH", "weight": 0.5, "instrument_id": eq.id, "asset_class": "equity"}],
    )
    before = load_personal_snapshot(pp_db, portfolio)
    ops_before = journal_operation_count(pp_db, portfolio.id)
    pos_before = list(
        pp_db.scalars(select(ManualPosition).where(ManualPosition.portfolio_id == portfolio.id)).all()
    )

    d = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("30000"))

    after = load_personal_snapshot(pp_db, portfolio)
    assert after.cash_rub == before.cash_rub
    assert after.contributed_rub == before.contributed_rub
    assert after.known_nav_rub == before.known_nav_rub
    assert journal_operation_count(pp_db, portfolio.id) == ops_before
    assert Decimal(d["new_cash_plan"]["requested_new_cash_rub"]) == Decimal("30000")
    assert {s["id"] for s in d["scenario_comparison"]} >= {
        "DO_NOTHING",
        "HOLD_CASH",
        "TARGET_UNDERWEIGHTS",
        "KRAKEN_ALLOCATION",
        "FIXED_INCOME_ALTERNATIVE",
    }
    # Projection rows unchanged (no execution / journal side-effects).
    pos_after = list(
        pp_db.scalars(select(ManualPosition).where(ManualPosition.portfolio_id == portfolio.id)).all()
    )
    assert [(p.instrument_id, money(p.units)) for p in pos_after] == [
        (p.instrument_id, money(p.units)) for p in pos_before
    ]


def test_decision_fingerprint_captured_and_stable(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio, eq = _fund(
        pp_db, "TEST — MVP fp", symbol="MVPFP", cash=Decimal("100000"), units=Decimal("10"), price=Decimal("100")
    )
    stub_decision_deps(
        monkeypatch,
        positions=[{"symbol": "MVPFP", "weight": 0.4, "instrument_id": eq.id, "asset_class": "equity"}],
    )
    d1 = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("10000"))
    assert d1["engine_version"] == ENGINE_VERSION
    assert isinstance(d1["decision_fingerprint"], str) and len(d1["decision_fingerprint"]) == 64
    assert decision_fingerprint(d1) == d1["decision_fingerprint"]

    # Key reorder of a copy must not change identity; fingerprint field itself excluded.
    reordered = {k: d1[k] for k in sorted(d1.keys())}
    assert decision_fingerprint(reordered) == d1["decision_fingerprint"]
    stamped = {**d1, "decision_fingerprint": "ignored"}
    assert decision_fingerprint(stamped) == d1["decision_fingerprint"]

    d2 = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("10000"))
    assert d2["decision_fingerprint"] == d1["decision_fingerprint"]


def test_portfolio_isolation_between_books(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    a, eq_a = _fund(
        pp_db, "TEST — MVP iso A", symbol="MVPISA", cash=Decimal("200000"), units=Decimal("50"), price=Decimal("200")
    )
    b, eq_b = _fund(
        pp_db, "TEST — MVP iso B", symbol="MVPISB", cash=Decimal("10000"), units=Decimal("20"), price=Decimal("50")
    )
    stub_decision_deps(
        monkeypatch,
        positions=[{"symbol": "MVPISB", "weight": 0.2, "instrument_id": eq_b.id, "asset_class": "equity"}],
    )
    cash_a = money(a.cash_rub)
    d = build_daily_personal_decision(pp_db, portfolio=b, new_cash_rub=Decimal("5000"))
    assert d["portfolio"]["id"] == b.id
    assert "MVPISB" in d["portfolio"]["symbols"]
    assert "MVPISA" not in d["portfolio"]["symbols"]
    assert money(a.cash_rub) == cash_a
    assert journal_operation_count(pp_db, a.id) >= 2
    # Decision for B must not create ops on A.
    assert (
        pp_db.scalar(
            select(func.count())
            .select_from(PersonalOperation)
            .where(PersonalOperation.portfolio_id == a.id, PersonalOperation.idempotency_key.like("%iso B%"))
        )
        or 0
    ) == 0
    _ = eq_a  # funded book A stays untouched


def test_empty_portfolio_decision_needs_setup(pp_db: Session) -> None:
    portfolio = wipe_portfolio(pp_db, "TEST — MVP empty")
    d = build_daily_personal_decision(pp_db, portfolio=portfolio)
    assert d["status"] == "NEEDS_SETUP"
    assert d["actions"][0]["action"] == "SETUP"
    assert journal_operation_count(pp_db, portfolio.id) == 0
    assert Decimal(portfolio.cash_rub or 0) == 0


def test_missing_quote_does_not_fake_executable_lots(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = wipe_portfolio(pp_db, "TEST — MVP noquote")
    # Equity in master without candle / mark.
    eq = make_equity(pp_db, "MVPNQ", close=None, lot_size=10)
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="mvp-nq-dep",
    )
    stub_decision_deps(
        monkeypatch,
        positions=[
            {
                "symbol": "MVPNQ",
                "weight": 0.5,
                "instrument_id": eq.id,
                "asset_class": "equity",
                "unit_price": None,
            }
        ],
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("50000"))
    uw = next(s for s in d["scenario_comparison"] if s["id"] == "TARGET_UNDERWEIGHTS")
    purchases = {p["symbol"]: p for p in uw.get("purchases") or []}
    if "MVPNQ" in purchases:
        row = purchases["MVPNQ"]
        assert row.get("lots") is None or "PRICE_MISSING" in (row.get("limitations") or [])
        assert row.get("execution_status") in {None, "RUB_ONLY", "ADVISORY_ONLY"} or row.get("lots") in {
            None,
            0,
        }


def test_stale_candidate_degrades_precision(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio, eq = _fund(
        pp_db, "TEST — MVP stale", symbol="MVPST", cash=Decimal("100000"), units=Decimal("10"), price=Decimal("100")
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: {
            "candidate_id": "stale-mvp",
            "as_of": "2020-01-01",
            "generated_at": "2020-01-02T00:00:00+00:00",
            "status": "STALE",
            "payload": {
                "candidate_id": "stale-mvp",
                "positions": [{"symbol": "MVPST", "weight": 0.5, "instrument_id": eq.id}],
                "freshness": {"stale": True, "stale_after_days": 10, "market_as_of": "2020-01-01"},
            },
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {"decision": {"cash_weight": 0.2, "equity_weight": 0.8, "status": "RESEARCH_ONLY"}},
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("20000"))
    assert d["context"]["candidate_stale"] is True
    uw = next(s for s in d["scenario_comparison"] if s["id"] == "TARGET_UNDERWEIGHTS")
    assert uw["status"] != "available"
    assert "CANDIDATE_STALE" in (uw.get("limitations") or [])
    assert uw.get("purchases") == []


def test_unknown_lot_size_never_fakes_lot_one(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = wipe_portfolio(pp_db, "TEST — MVP lot")
    eq = make_equity(pp_db, "MVPLOT", close=Decimal("100"), lot_size=None)
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="mvp-lot-dep",
    )
    stub_decision_deps(
        monkeypatch,
        positions=[
            {
                "symbol": "MVPLOT",
                "weight": 0.5,
                "instrument_id": eq.id,
                "asset_class": "equity",
                "unit_price": "100",
            }
        ],
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("50000"))
    uw = next(s for s in d["scenario_comparison"] if s["id"] == "TARGET_UNDERWEIGHTS")
    by_sym = {p["symbol"]: p for p in uw.get("purchases") or []}
    assert "MVPLOT" in by_sym
    row = by_sym["MVPLOT"]
    assert row.get("lots") is None
    assert "LOT_SIZE_UNKNOWN" in (row.get("limitations") or [])


def test_bond_execution_unavailable_in_journal_and_advisory_in_plan(
    pp_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    portfolio = wipe_portfolio(pp_db, "TEST — MVP bond")
    bond = make_bond(pp_db, "MVPBND")
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="mvp-bnd-dep",
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
            idempotency_key="mvp-bnd-buy",
        )
    assert ei.value.code == "BOND_TRADE_ACCOUNTING_NOT_READY"

    stub_decision_deps(monkeypatch, positions=[])
    d = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("40000"))
    fi = next(s for s in d["scenario_comparison"] if s["id"] == "FIXED_INCOME_ALTERNATIVE")
    assert fi["execution_status"] == "ADVISORY_ONLY"
    assert Decimal(fi["executable_notional_rub"]) == 0


def test_duplicate_operation_save_is_idempotent(pp_db: Session) -> None:
    portfolio = wipe_portfolio(pp_db, "TEST — MVP dup")
    first = create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("1000"),
        idempotency_key="mvp-dup-dep",
    )
    second = create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("1000"),
        idempotency_key="mvp-dup-dep",
    )
    assert first.id == second.id
    assert (
        int(
            pp_db.scalar(
                select(func.count())
                .select_from(PersonalOperation)
                .where(PersonalOperation.portfolio_id == portfolio.id)
            )
            or 0
        )
        == 1
    )


def test_decision_and_memory_paths_do_not_write_execution_adapters() -> None:
    root = Path(__file__).resolve().parents[2] / "app" / "modules"
    decision_src = (root / "portfolio" / "application" / "daily_personal_decision_service.py").read_text(
        encoding="utf-8"
    )
    new_cash_src = (root / "portfolio" / "application" / "decision_new_cash.py").read_text(encoding="utf-8")
    memory_src = (root / "memory" / "application" / "decision_memory_service.py").read_text(encoding="utf-8")
    for src in (decision_src, new_cash_src, memory_src):
        assert "app.modules.shadow" not in src
        assert "broker_execution" not in src
        assert "execute_order" not in src
        assert "ShadowOrder" not in src


def test_memory_capture_idempotent_when_db_available() -> None:
    """Idempotent memory save — skip cleanly if memory DB / migrations absent."""
    try:
        from sqlalchemy import text

        import app.infrastructure.db.session as db_session
        from app.core.config import get_settings
        from app.infrastructure.db.session import get_core_engine, get_memory_engine
        from app.modules.memory.application.decision_memory_service import capture_decision
        from app.modules.memory.domain.decision_memory import decision_fingerprint as mem_fp
        from app.modules.memory.infrastructure.models import PersonalDecisionRecord

        get_settings.cache_clear()
        # Drop cached engines so host overrides (localhost ports/passwords) apply.
        db_session._core_engine = None
        db_session._memory_engine = None
        db_session._CoreSessionLocal = None
        db_session._MemorySessionLocal = None
        core_engine = get_core_engine()
        mem_engine = get_memory_engine()
        core_conn = core_engine.connect()
        mem_conn = mem_engine.connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"databases unavailable: {exc}")

    core_tx = core_conn.begin()
    mem_tx = mem_conn.begin()
    core = Session(bind=core_conn, autoflush=False, expire_on_commit=False)
    mem = Session(bind=mem_conn, autoflush=False, expire_on_commit=False)
    try:
        try:
            mem.execute(text("SELECT 1 FROM memory.personal_decision_records LIMIT 0"))
        except Exception:
            mem.rollback()
            pytest.skip("memory migration not applied")
        if not schema_ready(core):
            pytest.skip("core portfolio schema not ready")

        pf = create_user_portfolio(core, name="TEST — MVP mem", is_test=True)
        payload = {
            "engine_version": ENGINE_VERSION,
            "as_of": "2026-09-21",
            "status": "READY",
            "headline": "mvp",
            "portfolio": {"id": pf.id, "name": pf.name},
            "actions": [],
            "context": {"candidate_source": "TEST"},
        }
        payload["decision_fingerprint"] = mem_fp(payload)
        first = capture_decision(
            mem,
            core,
            portfolio_id=pf.id,
            decision_payload=payload,
            idempotency_key="mvp-mem-1",
            new_cash_rub=None,
            expected_decision_fingerprint=payload["decision_fingerprint"],
        )
        n1 = int(
            mem.scalar(
                select(func.count())
                .select_from(PersonalDecisionRecord)
                .where(PersonalDecisionRecord.portfolio_id == pf.id)
            )
            or 0
        )
        second = capture_decision(
            mem,
            core,
            portfolio_id=pf.id,
            decision_payload={**payload, "headline": "changed-display"},
            idempotency_key="mvp-mem-1",
            new_cash_rub=None,
            expected_decision_fingerprint=payload["decision_fingerprint"],
        )
        n2 = int(
            mem.scalar(
                select(func.count())
                .select_from(PersonalDecisionRecord)
                .where(PersonalDecisionRecord.portfolio_id == pf.id)
            )
            or 0
        )
        assert second["idempotent_replay"] is True
        assert second["id"] == first["id"]
        assert n2 == n1 == 1
        # Capture must not create portfolio journal ops.
        assert journal_operation_count(core, pf.id) == 0
    finally:
        core.close()
        mem.close()
        core_tx.rollback()
        mem_tx.rollback()
        core_conn.close()
        mem_conn.close()


def test_test_books_do_not_leak_into_default_list(pp_db: Session) -> None:
    from app.modules.portfolio.application.user_portfolio_service import list_user_portfolios

    hidden = create_user_portfolio(pp_db, name="TEST — MVP list hide", is_test=True)
    visible = create_user_portfolio(pp_db, name="MVP list show", is_test=False)
    # Clean non-test noise from other parallel suites is hard; assert membership only.
    default_ids = {i["id"] for i in list_user_portfolios(pp_db, include_test=False)}
    assert hidden.id not in default_ids
    assert visible.id in default_ids
    # Avoid leaving accidental ACTIVE journals — delete draft residue for isolation of counts.
    pp_db.execute(delete(ManualPosition).where(ManualPosition.portfolio_id.in_([hidden.id, visible.id])))
