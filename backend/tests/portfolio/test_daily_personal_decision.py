"""Daily Personal Decision Engine V1 — focused scenarios."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument, InstrumentSource
from app.modules.investment.infrastructure.models import BondMarketSnapshot, BondTerm
from app.modules.portfolio.application.daily_personal_decision_service import (
    build_daily_personal_decision,
)
from app.modules.portfolio.application.personal_portfolio_service import (
    create_operation,
    get_or_create_test_portfolio,
    journal_operation_count,
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


def _equity(session: Session, symbol: str, *, close: Decimal, as_of: date = date(2026, 9, 25)) -> Instrument:
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


def _bond(session: Session, symbol: str = "DPDLB") -> Instrument:
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
    session.flush()
    return inst


def test_empty_needs_setup(pp_db: Session) -> None:
    portfolio = _reset(pp_db, "TEST — DD empty")
    d = build_daily_personal_decision(pp_db, portfolio=portfolio)
    assert d["status"] == "NEEDS_SETUP"
    assert d["actions"][0]["action"] == "SETUP"
    assert not any(a["action"].startswith("CONSIDER_") for a in d["actions"])


def test_legacy_pending_activate(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = _reset(pp_db, "TEST — DD legacy")
    eq = _equity(pp_db, "DDLEG", close=Decimal("100"))
    portfolio.cash_rub = Decimal("50000")
    pp_db.add(
        ManualPosition(
            portfolio_id=portfolio.id,
            instrument_id=eq.id,
            units=Decimal("10"),
            average_price=Decimal("100"),
        )
    )
    pp_db.flush()
    d = build_daily_personal_decision(pp_db, portfolio=portfolio)
    assert d["status"] == "DRAFT_ANALYSIS"
    assert d["actions"][0]["action"] == "ACTIVATE_JOURNAL"
    assert not any(a["action"] in {"CONSIDER_INCREASE", "CONSIDER_REDUCE"} for a in d["actions"])


def test_aligned_no_action(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = _reset(pp_db, "TEST — DD aligned")
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-aln-dep",
    )
    # Cash-only book aligned with cash-heavy candidate — no concentration / no deltas.
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.analyze_manual_portfolio",
        lambda session, portfolio=None: {
            "source": "personal_portfolio",
            "journal_state": "ACTIVE",
            "cash_rub": 100000.0,
            "nav": 100000.0,
            "market_value_supported": 0.0,
            "positions": [],
            "allocation": [],
            "concentration_by_issuer": [],
            "risk_findings": [],
            "coverage_pct": 100.0,
            "quality": "LIVE",
            "valuation_partial": False,
            "valuation_complete": True,
            "investment_pnl_rub": 0.0,
        },
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.compare_to_candidate",
        lambda session, portfolio=None, as_of=None, **kwargs: {
            "actual_source": "personal_portfolio",
            "candidate_source": "preview",
            "candidate_id": "cash",
            "candidate_stale": False,
            "candidate_freshness_known": True,
            "comparisons": [],
            "nav": 100000.0,
        },
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.advisory_rebalance",
        lambda session, portfolio=None: {
            "advisory": True,
            "plan_rows": [],
            "review_rows": [],
            "cash_safe": True,
            "nav": 100000.0,
            "cash": 100000.0,
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {
                "equity_weight": 0.0,
                "fixed_income_weight": 0.0,
                "cash_weight": 1.0,
                "status": "RESEARCH_ONLY",
            }
        },
    )
    d1 = build_daily_personal_decision(pp_db, portfolio=portfolio)
    d2 = build_daily_personal_decision(pp_db, portfolio=portfolio)
    assert d1["status"] == "NO_ACTION"
    assert d1["actions"][0]["action"] in {"HOLD", "KEEP_CASH"}
    assert d1["status"] == d2["status"]
    assert [a["action"] for a in d1["actions"]] == [a["action"] for a in d2["actions"]]


def test_concentration_review_priority(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = _reset(pp_db, "TEST — DD conc")
    eq = _equity(pp_db, "DDCON", close=Decimal("100"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("10000"),
        idempotency_key="dd-c-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq.id,
        units=Decimal("100"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-c-buy",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "more-sber",
            "positions": [{"symbol": "DDCON", "weight": 0.9}],
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {"decision": {"cash_weight": 0.1, "status": "RESEARCH_ONLY"}},
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio)
    codes = {c for a in d["actions"] for c in a["reason_codes"]}
    assert "ISSUER_CONCENTRATION" in codes or any(a["action"] == "REVIEW" for a in d["actions"])
    # Must not lead with blind INCREASE over concentration risk.
    if d["actions"]:
        assert d["actions"][0]["action"] in {"REVIEW", "DATA_QUALITY", "HOLD", "KEEP_CASH", "CONSIDER_REDUCE"}


def test_candidate_mismatch_reduce(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = _reset(pp_db, "TEST — DD mismatch")
    eq = _equity(pp_db, "DDMIS", close=Decimal("100"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-m-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq.id,
        units=Decimal("250"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-m-buy",
    )
    # leftover cash so NAV has room; weight of equity ~25k/100k if we only buy 250*100... wait 25000/100000=0.25
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "low",
            "positions": [{"symbol": "DDMIS", "weight": 0.12}],
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {"decision": {"cash_weight": 0.2, "status": "RESEARCH_ONLY"}},
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio)
    reduce_actions = [a for a in d["actions"] if a["action"] == "CONSIDER_REDUCE" and a.get("symbol") == "DDMIS"]
    assert reduce_actions or any(a["action"] == "REVIEW" for a in d["actions"])


def test_actual_only_holding_is_review_not_sell(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = _reset(pp_db, "TEST — DD only")
    eq = _equity(pp_db, "DDXYZ", close=Decimal("50"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("50000"),
        idempotency_key="dd-o-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq.id,
        units=Decimal("100"),
        price=Decimal("50"),
        non_standard_lot=True,
        idempotency_key="dd-o-buy",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "other",
            "positions": [{"symbol": "OTHER", "weight": 1.0}],
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {"decision": {"cash_weight": 0.1, "status": "RESEARCH_ONLY"}},
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio)
    xyz = [a for a in d["actions"] if a.get("symbol") == "DDXYZ"]
    assert xyz
    assert all(a["action"] != "CONSIDER_REDUCE" or "NOT_IN_CANDIDATE" not in a["reason_codes"] for a in xyz)
    assert any(a["action"] == "REVIEW" and "NOT_IN_CANDIDATE" in a["reason_codes"] for a in xyz)


def test_partial_no_precise_rebalance(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = _reset(pp_db, "TEST — DD partial")
    priced = _equity(pp_db, "DDPRX", close=Decimal("100"))
    dark = Instrument(
        symbol="DDDARK",
        name="No px",
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
            external_id="DDDARK",
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
        idempotency_key="dd-p-dep",
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
        idempotency_key="dd-p-b1",
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
        idempotency_key="dd-p-b2",
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio)
    assert d["status"] == "PARTIAL"
    assert d["portfolio"]["investment_pnl_rub"] is None
    assert not any(a["action"] in {"CONSIDER_INCREASE", "CONSIDER_REDUCE"} for a in d["actions"])
    dark_row = next(p for p in load_personal_snapshot(pp_db, portfolio).positions if p.symbol == "DDDARK")
    assert dark_row.market_value is None


def test_bond_safe_and_contribution(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = _reset(pp_db, "TEST — DD bond")
    bond = _bond(pp_db, "DDBND")
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-b-dep",
    )
    # Projection bond without journal OPENING (blocked) — legacy-like for mark/P&L safety via snapshot.
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
    assert snap.positions
    bond_pos = next(p for p in snap.positions if p.symbol == "DDBND")
    assert bond_pos.market_value is not None
    assert bond_pos.unrealized_pnl is None

    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 4, tzinfo=UTC),
        amount=Decimal("30000"),
        idempotency_key="dd-b-dep2",
    )
    snap2 = load_personal_snapshot(pp_db, portfolio)
    assert money(snap2.contributed_rub) == money("130000")
    # With bond mark + cash, valuation may be complete; investment pnl must not treat deposits as profit alone.
    if snap2.valuation_complete:
        assert snap2.investment_pnl_rub is not None


def test_no_contradictory_actions(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = _reset(pp_db, "TEST — DD contra")
    eq = _equity(pp_db, "DDCTR", close=Decimal("100"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-ct-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq.id,
        units=Decimal("400"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-ct-buy",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "mix",
            "positions": [{"symbol": "DDCTR", "weight": 0.1}],
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {"decision": {"cash_weight": 0.5, "status": "RESEARCH_ONLY"}},
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio)
    by_sym: dict[str, set[str]] = {}
    for a in d["actions"]:
        if a.get("symbol"):
            by_sym.setdefault(a["symbol"], set()).add(a["action"])
    for sym, acts in by_sym.items():
        assert not ({"CONSIDER_INCREASE", "CONSIDER_REDUCE"} <= acts), sym
        assert not ({"CONSIDER_INCREASE", "HOLD"} <= acts), sym
        assert not ({"CONSIDER_REDUCE", "HOLD"} <= acts), sym


def test_uses_personal_nav_not_hardcoded(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = _reset(pp_db, "TEST — DD nav")
    eq = _equity(pp_db, "DDNAV", close=Decimal("100"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("250000"),
        idempotency_key="dd-n-dep",
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
        idempotency_key="dd-n-buy",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {"candidate_id": "x", "positions": [{"symbol": "DDNAV", "weight": 0.05}]},
    )
    seen: dict[str, Decimal] = {}

    def fake_research(session, **kwargs):
        seen["capital"] = kwargs.get("capital")
        return {"decision": {"cash_weight": 0.2, "status": "RESEARCH_ONLY"}}

    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        fake_research,
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio)
    assert d["context"]["research_used_personal_nav"] is True
    assert seen["capital"] != Decimal("100000")
    assert money(seen["capital"]) == money(load_personal_snapshot(pp_db, portfolio).known_nav_rub)


def test_research_unavailable_graceful(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = _reset(pp_db, "TEST — DD resfail")
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("10000"),
        idempotency_key="dd-r-dep",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {"candidate_id": "x", "positions": []},
    )

    def boom(session, **kwargs):
        raise RuntimeError("research down")

    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        boom,
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio)
    assert d["status"] in {"NO_ACTION", "READY", "PARTIAL"}
    assert any("research" in x.lower() for x in d["data_quality"]["degradations"])


def test_endpoint_read_only_no_mutation(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = _reset(pp_db, "TEST — DD ro")
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("1000"),
        idempotency_key="dd-ro-dep",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {"candidate_id": "x", "positions": []},
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {"decision": {"cash_weight": 1.0, "status": "RESEARCH_ONLY"}},
    )
    n0 = journal_operation_count(pp_db, portfolio.id)
    cash0 = money(portfolio.cash_rub)
    build_daily_personal_decision(pp_db, portfolio=portfolio)
    assert journal_operation_count(pp_db, portfolio.id) == n0
    assert money(portfolio.cash_rub) == cash0


def test_candidate_unavailable_not_aligned(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Complete book + failed compare must not claim ALIGNED_WITH_CANDIDATE / NO_ACTION."""
    portfolio = _reset(pp_db, "TEST — DD no-cand")
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("50000"),
        idempotency_key="dd-nc-dep",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.analyze_manual_portfolio",
        lambda session, portfolio=None: {
            "source": "personal_portfolio",
            "journal_state": "ACTIVE",
            "cash_rub": 50000.0,
            "nav": 50000.0,
            "market_value_supported": 0.0,
            "positions": [],
            "allocation": [],
            "concentration_by_issuer": [],
            "risk_findings": [],
            "coverage_pct": 100.0,
            "quality": "LIVE",
            "valuation_partial": False,
            "valuation_complete": True,
            "investment_pnl_rub": 0.0,
        },
    )

    def boom_compare(session, portfolio=None, as_of=None, **kwargs):
        raise RuntimeError("candidate down")

    def boom_rebalance(session, portfolio=None, **kwargs):
        raise RuntimeError("rebalance down")

    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.compare_to_candidate",
        boom_compare,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.advisory_rebalance",
        boom_rebalance,
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {"decision": {"cash_weight": 1.0, "status": "RESEARCH_ONLY"}},
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio)
    assert d["status"] != "NO_ACTION"
    codes = {c for a in d["actions"] for c in a["reason_codes"]}
    assert "ALIGNED_WITH_CANDIDATE" not in codes
    assert "CANDIDATE_CONTEXT_UNAVAILABLE" in codes
    blob = f"{d['headline']} {d['summary']} {' '.join(a['rationale'] for a in d['actions'])}"
    assert "близок к текущему кандидату" not in blob.lower()
    assert "недоступно" in blob.lower() or "не подтверждено" in blob.lower()


def test_test_portfolio_isolation_from_primary(pp_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Daily Decision for TEST book B must not mix holdings/NAV from another user book A."""
    from app.modules.portfolio.application.user_portfolio_service import create_user_portfolio

    primary = create_user_portfolio(pp_db, name="TEST — DD iso A", is_test=True)

    eq_a = _equity(pp_db, "DDPRIMA", close=Decimal("200"))
    create_operation(
        pp_db,
        portfolio=primary,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("200000"),
        idempotency_key="dd-iso-a-dep",
    )
    create_operation(
        pp_db,
        portfolio=primary,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq_a.id,
        units=Decimal("50"),
        price=Decimal("200"),
        non_standard_lot=True,
        idempotency_key="dd-iso-a-buy",
    )
    cash_a = money(primary.cash_rub)
    symbols_a = set(load_personal_snapshot(pp_db, primary).symbols)

    test_book = _reset(pp_db, "TEST — DD iso B")
    eq_b = _equity(pp_db, "DDTESTB", close=Decimal("50"))
    create_operation(
        pp_db,
        portfolio=test_book,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("10000"),
        idempotency_key="dd-iso-b-dep",
    )
    create_operation(
        pp_db,
        portfolio=test_book,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq_b.id,
        units=Decimal("20"),
        price=Decimal("50"),
        non_standard_lot=True,
        idempotency_key="dd-iso-b-buy",
    )

    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "iso",
            "positions": [{"symbol": "DDTESTB", "weight": 0.1}],
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {"decision": {"cash_weight": 0.5, "status": "RESEARCH_ONLY"}},
    )

    d = build_daily_personal_decision(pp_db, portfolio=test_book)
    snap_b = load_personal_snapshot(pp_db, test_book)
    assert d["portfolio"]["id"] == test_book.id
    assert money(Decimal(d["portfolio"]["nav_rub"])) == money(snap_b.known_nav_rub)
    assert money(Decimal(d["portfolio"]["cash_rub"])) == money(snap_b.cash_rub)
    assert "DDTESTB" in d["portfolio"]["symbols"]
    assert "DDPRIMA" not in d["portfolio"]["symbols"]
    assert symbols_a.isdisjoint(set(d["portfolio"]["symbols"]))
    # Primary unchanged
    assert money(primary.cash_rub) == cash_a
    assert journal_operation_count(pp_db, primary.id) >= 2


def test_decision_v2_new_cash_zero_compatible(pp_db, monkeypatch):
    portfolio = _reset(pp_db, "dd-v2-zero")
    eq = _equity(pp_db, "DDV2Z", close=Decimal("100"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-v2-z-dep",
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
        idempotency_key="dd-v2-z-buy",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "v2z",
            "positions": [{"symbol": "DDV2Z", "weight": 0.5}],
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {
                "cash_weight": 0.2,
                "equity_weight": 0.8,
                "status": "RESEARCH_ONLY",
                "cbr_hurdle_annual": 0.16,
            }
        },
    )
    before = load_personal_snapshot(pp_db, portfolio)
    ops_before = journal_operation_count(pp_db, portfolio.id)
    d = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("0"))
    after = load_personal_snapshot(pp_db, portfolio)
    assert d["engine_version"] == "2"
    assert Decimal(d["new_cash_rub"]) == 0
    assert after.cash_rub == before.cash_rub
    assert after.contributed_rub == before.contributed_rub
    assert journal_operation_count(pp_db, portfolio.id) == ops_before


def test_decision_v2_new_cash_plan_readonly(pp_db, monkeypatch):
    portfolio = _reset(pp_db, "dd-v2-30k")
    eq_a = _equity(pp_db, "DDV2A", close=Decimal("100"))
    eq_b = _equity(pp_db, "DDV2B", close=Decimal("50"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-v2-30-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq_a.id,
        units=Decimal("40"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-v2-30-a",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq_b.id,
        units=Decimal("20"),
        price=Decimal("50"),
        non_standard_lot=True,
        idempotency_key="dd-v2-30-b",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "v230",
            "positions": [
                {"symbol": "DDV2A", "weight": 0.2},
                {"symbol": "DDV2B", "weight": 0.5},
            ],
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {
                "cash_weight": 0.1,
                "equity_weight": 0.7,
                "fixed_income_weight": 0.2,
                "status": "RESEARCH_ONLY",
                "cbr_hurdle_annual": 0.16,
            }
        },
    )
    before = load_personal_snapshot(pp_db, portfolio)
    ops_before = journal_operation_count(pp_db, portfolio.id)
    d = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("30000"))
    after = load_personal_snapshot(pp_db, portfolio)
    assert after.cash_rub == before.cash_rub
    assert after.contributed_rub == before.contributed_rub
    assert journal_operation_count(pp_db, portfolio.id) == ops_before
    assert Decimal(d["new_cash_plan"]["requested_new_cash_rub"]) == Decimal("30000")
    ids = {s["id"] for s in d["scenario_comparison"]}
    assert "DO_NOTHING" in ids
    assert "HOLD_CASH" in ids
    assert "TARGET_UNDERWEIGHTS" in ids
    assert "KRAKEN_ALLOCATION" in ids
    for s in d["scenario_comparison"]:
        for purchase in s.get("purchases") or []:
            assert purchase.get("lots") is None or purchase.get("lots") >= 0
    assert d["context"]["dataset_v3_drives_decision"] is False


def test_decision_v2_negative_rejected(pp_db):
    portfolio = _reset(pp_db, "dd-v2-neg")
    try:
        build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("-1"))
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_decision_v2_ab_isolation(pp_db, monkeypatch):
    a = _reset(pp_db, "dd-v2-iso-a")
    b = _reset(pp_db, "dd-v2-iso-b")
    eq_a = _equity(pp_db, "DDISOA", close=Decimal("100"))
    eq_b = _equity(pp_db, "DDISOB", close=Decimal("50"))
    create_operation(
        pp_db,
        portfolio=a,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="iso-a-dep",
    )
    create_operation(
        pp_db,
        portfolio=a,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq_a.id,
        units=Decimal("50"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="iso-a-buy",
    )
    create_operation(
        pp_db,
        portfolio=b,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("50000"),
        idempotency_key="iso-b-dep",
    )
    create_operation(
        pp_db,
        portfolio=b,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq_b.id,
        units=Decimal("10"),
        price=Decimal("50"),
        non_standard_lot=True,
        idempotency_key="iso-b-buy",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {"candidate_id": "iso", "positions": []},
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {"cash_weight": 0.3, "equity_weight": 0.7, "status": "RESEARCH_ONLY"}
        },
    )
    da = build_daily_personal_decision(pp_db, portfolio=a, new_cash_rub=Decimal("30000"))
    db_ = build_daily_personal_decision(pp_db, portfolio=b, new_cash_rub=Decimal("30000"))
    assert da["portfolio"]["id"] == a.id
    assert db_["portfolio"]["id"] == b.id
    assert da["new_cash_plan"]["current_nav_rub"] != db_["new_cash_plan"]["current_nav_rub"]


def _scenario(decision: dict, sid: str) -> dict:
    return next(s for s in decision["scenario_comparison"] if s["id"] == sid)


def _assert_accounting(scenario: dict, new_cash: Decimal) -> None:
    if scenario["id"] == "DO_NOTHING":
        assert Decimal(scenario["external_unallocated_rub"]) == new_cash
        assert Decimal(scenario["executable_notional_rub"]) == 0
        return
    total = (
        Decimal(scenario.get("executable_notional_rub") or 0)
        + Decimal(scenario.get("advisory_only_rub") or 0)
        + Decimal(scenario.get("residual_cash_rub") or 0)
    )
    assert total == new_cash


def test_decision_v2_shortfall_math_and_do_nothing(pp_db, monkeypatch):
    portfolio = _reset(pp_db, "dd-v2-shortfall")
    eq_a = _equity(pp_db, "DDV2SA", close=Decimal("100"))
    eq_b = _equity(pp_db, "DDV2SB", close=Decimal("50"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-sf-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq_a.id,
        units=Decimal("200"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-sf-a",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq_b.id,
        units=Decimal("200"),
        price=Decimal("50"),
        non_standard_lot=True,
        idempotency_key="dd-sf-b",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "sf",
            "positions": [
                {"symbol": "DDV2SA", "weight": 0.3, "instrument_id": eq_a.id, "asset_class": "equity"},
                {"symbol": "DDV2SB", "weight": 0.2, "instrument_id": eq_b.id, "asset_class": "equity"},
            ],
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {
                "cash_weight": 0.1,
                "equity_weight": 0.7,
                "fixed_income_weight": 0.2,
                "status": "RESEARCH_ONLY",
                "cbr_hurdle_annual": 0.16,
            }
        },
    )
    before = load_personal_snapshot(pp_db, portfolio)
    ops_before = journal_operation_count(pp_db, portfolio.id)
    assert before.known_nav_rub == Decimal("100000")
    d = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("100000"))
    after = load_personal_snapshot(pp_db, portfolio)
    assert after.cash_rub == before.cash_rub
    assert after.contributed_rub == before.contributed_rub
    assert journal_operation_count(pp_db, portfolio.id) == ops_before
    assert d["context"]["dataset_v3_drives_decision"] is False
    assert d["context"]["candidate_source"] == "live_preview"
    assert d["context"]["candidate_stale"] is False

    nothing = _scenario(d, "DO_NOTHING")
    assert Decimal(nothing["portfolio_nav_after_rub"]) == Decimal("100000")
    assert nothing["cash_share"] == pytest.approx(0.7)
    assert Decimal(nothing["external_unallocated_rub"]) == Decimal("100000")
    _assert_accounting(nothing, Decimal("100000"))

    hold = _scenario(d, "HOLD_CASH")
    assert Decimal(hold["portfolio_nav_after_rub"]) == Decimal("200000")
    assert hold["cash_share"] == pytest.approx(170000 / 200000)
    _assert_accounting(hold, Decimal("100000"))

    uw = _scenario(d, "TARGET_UNDERWEIGHTS")
    by_sym = {p["symbol"]: p for p in uw["purchases"]}
    assert Decimal(by_sym["DDV2SA"]["target_rub"]) == Decimal("40000")
    assert Decimal(by_sym["DDV2SB"]["target_rub"]) == Decimal("30000")
    assert Decimal(uw["target_allocation_rub"]) == Decimal("70000")
    assert Decimal(uw["residual_cash_rub"]) == Decimal("30000")
    _assert_accounting(uw, Decimal("100000"))

    kraken = _scenario(d, "KRAKEN_ALLOCATION")
    kraken_syms = {p.get("symbol") for p in kraken["purchases"] if p.get("symbol")}
    assert "DDV2SA" in kraken_syms or "DDV2SB" in kraken_syms
    assert Decimal(kraken["advisory_only_rub"]) == Decimal("20000")
    assert Decimal(kraken["executable_notional_rub"]) == Decimal(kraken["deployed_rub"])
    _assert_accounting(kraken, Decimal("100000"))

    fi = _scenario(d, "FIXED_INCOME_ALTERNATIVE")
    assert fi["status"] == "advisory"
    assert Decimal(fi["executable_notional_rub"]) == 0
    assert Decimal(fi["advisory_only_rub"]) == Decimal("100000")
    assert fi["execution_status"] == "ADVISORY_ONLY"
    _assert_accounting(fi, Decimal("100000"))


def test_decision_v2_do_nothing_uses_current_nav(pp_db, monkeypatch):
    portfolio = _reset(pp_db, "dd-v2-dn")
    eq = _equity(pp_db, "DDV2DN", close=Decimal("100"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-dn-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq.id,
        units=Decimal("800"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-dn-buy",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {"candidate_id": "dn", "positions": []},
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {"cash_weight": 0.2, "equity_weight": 0.8, "status": "RESEARCH_ONLY"}
        },
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("30000"))
    nothing = _scenario(d, "DO_NOTHING")
    assert Decimal(nothing["portfolio_nav_after_rub"]) == Decimal("100000")
    assert nothing["cash_share"] == pytest.approx(0.2)
    assert Decimal(nothing["external_unallocated_rub"]) == Decimal("30000")
    hold = _scenario(d, "HOLD_CASH")
    assert Decimal(hold["portfolio_nav_after_rub"]) == Decimal("130000")
    assert hold["cash_share"] == pytest.approx(50000 / 130000)


def test_decision_v2_overweight_zero_and_no_25pct_skip(pp_db, monkeypatch):
    portfolio = _reset(pp_db, "dd-v2-ow")
    eq_a = _equity(pp_db, "DDV2OA", close=Decimal("100"))
    eq_b = _equity(pp_db, "DDV2OB", close=Decimal("100"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-ow-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq_a.id,
        units=Decimal("400"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-ow-a",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq_b.id,
        units=Decimal("100"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-ow-b",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "ow",
            "positions": [
                {"symbol": "DDV2OA", "weight": 0.3, "instrument_id": eq_a.id, "asset_class": "equity"},
                {"symbol": "DDV2OB", "weight": 0.5, "instrument_id": eq_b.id, "asset_class": "equity"},
            ],
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {"cash_weight": 0.2, "equity_weight": 0.8, "status": "RESEARCH_ONLY"}
        },
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("30000"))
    uw = _scenario(d, "TARGET_UNDERWEIGHTS")
    by_sym = {p["symbol"]: p for p in uw["purchases"]}
    assert "DDV2OA" not in by_sym
    assert "DDV2OB" in by_sym
    kraken = _scenario(d, "KRAKEN_ALLOCATION")
    kraken_eq = [p for p in kraken["purchases"] if p.get("symbol")]
    assert all(p["symbol"] != "DDV2OA" for p in kraken_eq)


def test_decision_v2_candidate_only_and_unresolved(pp_db, monkeypatch):
    portfolio = _reset(pp_db, "dd-v2-only")
    held = _equity(pp_db, "DDV2H1", close=Decimal("100"))
    only = _equity(pp_db, "DDV2GZ", close=Decimal("200"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-only-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=held.id,
        units=Decimal("100"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-only-h",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "only",
            "positions": [
                {"symbol": "DDV2GZ", "weight": 0.2},
                {"symbol": "ZZNOPE99", "weight": 0.2},
            ],
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {"cash_weight": 0.6, "equity_weight": 0.4, "status": "RESEARCH_ONLY"}
        },
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("50000"))
    uw = _scenario(d, "TARGET_UNDERWEIGHTS")
    by_sym = {p["symbol"]: p for p in uw["purchases"]}
    assert by_sym["DDV2GZ"]["instrument_id"] == only.id
    assert Decimal(by_sym["DDV2GZ"]["target_rub"]) > 0
    assert "INSTRUMENT_UNRESOLVED" in (by_sym["ZZNOPE99"].get("limitations") or [])
    assert by_sym["ZZNOPE99"].get("lots") is None


def test_decision_v2_stale_candidate_degrades(pp_db, monkeypatch):
    portfolio = _reset(pp_db, "dd-v2-stale")
    eq = _equity(pp_db, "DDV2ST", close=Decimal("100"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-st-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq.id,
        units=Decimal("100"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-st-buy",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: {
            "candidate_id": "stale-1",
            "as_of": "2020-01-01",
            "generated_at": "2020-01-02T00:00:00+00:00",
            "status": "STALE",
            "payload": {
                "candidate_id": "stale-1",
                "positions": [{"symbol": "DDV2ST", "weight": 0.5, "instrument_id": eq.id}],
                "freshness": {"stale": True, "stale_after_days": 10, "market_as_of": "2020-01-01"},
            },
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {"cash_weight": 0.2, "equity_weight": 0.8, "status": "RESEARCH_ONLY"}
        },
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("30000"))
    assert d["context"]["candidate_stale"] is True
    uw = _scenario(d, "TARGET_UNDERWEIGHTS")
    assert uw["status"] != "available"
    assert "CANDIDATE_STALE" in (uw.get("limitations") or [])
    assert uw.get("purchases") == []
    kraken = _scenario(d, "KRAKEN_ALLOCATION")
    assert kraken["status"] in {"degraded", "unavailable"}
    assert not any(p.get("lots") for p in kraken.get("purchases") or [] if p.get("symbol"))


def test_decision_v2_scale_when_shortfalls_exceed_cash(pp_db, monkeypatch):
    portfolio = _reset(pp_db, "dd-v2-scale")
    eq_a = _equity(pp_db, "DDV2XA", close=Decimal("100"))
    eq_b = _equity(pp_db, "DDV2XB", close=Decimal("100"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-sc-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq_a.id,
        units=Decimal("200"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-sc-a",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq_b.id,
        units=Decimal("100"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-sc-b",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "sc",
            "positions": [
                {"symbol": "DDV2XA", "weight": 0.4, "instrument_id": eq_a.id, "asset_class": "equity"},
                {"symbol": "DDV2XB", "weight": 0.4, "instrument_id": eq_b.id, "asset_class": "equity"},
            ],
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {"cash_weight": 0.2, "equity_weight": 0.8, "status": "RESEARCH_ONLY"}
        },
    )
    d = build_daily_personal_decision(pp_db, portfolio=portfolio, new_cash_rub=Decimal("20000"))
    uw = _scenario(d, "TARGET_UNDERWEIGHTS")
    total_target = sum(Decimal(p["target_rub"]) for p in uw["purchases"])
    assert total_target == Decimal("20000")
    _assert_accounting(uw, Decimal("20000"))


def test_decision_v2_confidence_parentheses(pp_db):
    from app.modules.portfolio.application.decision_new_cash import _confidence
    from app.modules.portfolio.application.personal_portfolio_service import PersonalPortfolioSnapshot

    snap = PersonalPortfolioSnapshot(
        portfolio=_reset(pp_db, "dd-v2-conf"),
        journal_state="ACTIVE",
        journal_cutover_at=None,
        cash_rub=Decimal("0"),
        known_nav_rub=Decimal("1"),
        valuation_complete=False,
        valuation_partial=True,
    )
    low = _confidence(
        snap=snap, compare=None, research=None, allow_precise=False, new_cash=Decimal("10")
    )
    assert low["status"] == "LOW"
    snap.valuation_complete = True
    snap.valuation_partial = False
    partial = _confidence(
        snap=snap,
        compare={"candidate_stale": False},
        research=None,
        allow_precise=True,
        new_cash=Decimal("10"),
    )
    assert partial["status"] == "PARTIAL"


def test_evaluate_candidate_freshness_age_overrides_stored_false():
    from app.modules.portfolio.application.manual_portfolio_service import (
        evaluate_candidate_freshness,
    )

    aged = evaluate_candidate_freshness(
        candidate_source="snapshot",
        freshness={
            "stale": False,
            "stale_after_days": 7,
            "market_as_of": "2026-09-01",
        },
        snapshot_status="READY",
        evaluation_date=date(2026, 9, 20),
    )
    assert aged["candidate_stale"] is True
    assert aged["candidate_freshness_known"] is True
    assert aged["candidate_freshness_reason"] == "AGE_EXCEEDED"
    assert aged["age_days"] == 19

    fresh = evaluate_candidate_freshness(
        candidate_source="snapshot",
        freshness={
            "stale": False,
            "stale_after_days": 7,
            "market_as_of": "2026-09-18",
        },
        snapshot_status="READY",
        evaluation_date=date(2026, 9, 20),
    )
    assert fresh["candidate_stale"] is False
    assert fresh["candidate_freshness_known"] is True
    assert fresh["age_days"] == 2

    # Boundary: age == threshold remains fresh (same as Candidate creation: days > stale_days).
    boundary = evaluate_candidate_freshness(
        candidate_source="snapshot",
        freshness={
            "stale": False,
            "stale_after_days": 7,
            "market_as_of": "2026-09-13",
        },
        snapshot_status="READY",
        evaluation_date=date(2026, 9, 20),
    )
    assert boundary["age_days"] == 7
    assert boundary["candidate_stale"] is False
    assert boundary["candidate_freshness_reason"] == "FRESH"

    stored_true = evaluate_candidate_freshness(
        candidate_source="snapshot",
        freshness={
            "stale": True,
            "stale_after_days": 7,
            "market_as_of": "2026-09-19",
        },
        snapshot_status="READY",
        evaluation_date=date(2026, 9, 20),
    )
    assert stored_true["candidate_stale"] is True
    assert stored_true["candidate_freshness_reason"] == "STORED_STALE"

    status_stale = evaluate_candidate_freshness(
        candidate_source="snapshot",
        freshness={
            "stale": False,
            "stale_after_days": 7,
            "market_as_of": "2026-09-19",
        },
        snapshot_status="STALE",
        evaluation_date=date(2026, 9, 20),
    )
    assert status_stale["candidate_stale"] is True
    assert status_stale["candidate_freshness_reason"] == "SNAPSHOT_STATUS_STALE"

    unknown = evaluate_candidate_freshness(
        candidate_source="snapshot",
        freshness={"stale": False, "stale_after_days": 7},
        snapshot_status="READY",
        candidate_as_of=None,
        generated_at=None,
        evaluation_date=date(2026, 9, 20),
    )
    assert unknown["candidate_freshness_known"] is False
    assert unknown["candidate_stale"] is False
    assert unknown["candidate_freshness_reason"] == "CANDIDATE_FRESHNESS_UNKNOWN"

    live = evaluate_candidate_freshness(
        candidate_source="live_preview",
        freshness={},
        snapshot_status=None,
        evaluation_date=date(2026, 9, 20),
    )
    assert live["candidate_stale"] is False
    assert live["candidate_freshness_known"] is True
    assert live["candidate_freshness_reason"] == "LIVE_PREVIEW"


def test_decision_v2_aged_stored_false_blocks_precise_lots(pp_db, monkeypatch):
    """Stored stale=false must not stay fresh forever after stale_after_days."""
    portfolio = _reset(pp_db, "dd-v2-age")
    eq = _equity(pp_db, "DDV2AGE", close=Decimal("100"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-age-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq.id,
        units=Decimal("100"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-age-buy",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: {
            "candidate_id": "aged-1",
            "as_of": "2026-09-01",
            "generated_at": "2026-09-01T12:00:00+00:00",
            "status": "READY",
            "payload": {
                "candidate_id": "aged-1",
                "as_of": "2026-09-01",
                "positions": [
                    {
                        "symbol": "DDV2AGE",
                        "weight": 0.5,
                        "instrument_id": eq.id,
                        "asset_class": "equity",
                    }
                ],
                "freshness": {
                    "stale": False,
                    "stale_after_days": 7,
                    "market_as_of": "2026-09-01",
                    "generated_at": "2026-09-01T12:00:00+00:00",
                },
            },
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {"cash_weight": 0.2, "equity_weight": 0.8, "status": "RESEARCH_ONLY"}
        },
    )
    d = build_daily_personal_decision(
        pp_db,
        portfolio=portfolio,
        as_of=date(2026, 9, 20),
        new_cash_rub=Decimal("30000"),
    )
    assert d["context"]["candidate_stale"] is True
    assert d["context"]["candidate_freshness_known"] is True
    assert d["context"]["candidate_age_days"] == 19
    uw = _scenario(d, "TARGET_UNDERWEIGHTS")
    assert uw["status"] != "available"
    assert "CANDIDATE_STALE" in (uw.get("limitations") or [])
    assert uw.get("purchases") == []
    kraken = _scenario(d, "KRAKEN_ALLOCATION")
    assert not any(p.get("lots") for p in kraken.get("purchases") or [] if p.get("symbol"))


def test_decision_v2_fresh_within_threshold(pp_db, monkeypatch):
    portfolio = _reset(pp_db, "dd-v2-fr")
    eq = _equity(pp_db, "DDV2FR", close=Decimal("100"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-fr-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq.id,
        units=Decimal("100"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-fr-buy",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: {
            "candidate_id": "fresh-1",
            "as_of": "2026-09-18",
            "generated_at": "2026-09-18T12:00:00+00:00",
            "status": "READY",
            "payload": {
                "candidate_id": "fresh-1",
                "positions": [
                    {
                        "symbol": "DDV2FR",
                        "weight": 0.4,
                        "instrument_id": eq.id,
                        "asset_class": "equity",
                    }
                ],
                "freshness": {
                    "stale": False,
                    "stale_after_days": 7,
                    "market_as_of": "2026-09-18",
                },
            },
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {"cash_weight": 0.2, "equity_weight": 0.8, "status": "RESEARCH_ONLY"}
        },
    )
    d = build_daily_personal_decision(
        pp_db,
        portfolio=portfolio,
        as_of=date(2026, 9, 20),
        new_cash_rub=Decimal("30000"),
    )
    assert d["context"]["candidate_stale"] is False
    assert d["context"]["candidate_freshness_known"] is True
    uw = _scenario(d, "TARGET_UNDERWEIGHTS")
    assert uw["status"] == "available"
    assert "CANDIDATE_STALE" not in (uw.get("limitations") or [])


def test_decision_v2_unknown_freshness_blocks_precise_lots(pp_db, monkeypatch):
    portfolio = _reset(pp_db, "dd-v2-unk")
    eq = _equity(pp_db, "DDV2UNK", close=Decimal("100"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-unk-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq.id,
        units=Decimal("100"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-unk-buy",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: {
            "candidate_id": "unk-1",
            "as_of": None,
            "generated_at": None,
            "status": "READY",
            "payload": {
                "candidate_id": "unk-1",
                "positions": [
                    {
                        "symbol": "DDV2UNK",
                        "weight": 0.5,
                        "instrument_id": eq.id,
                        "asset_class": "equity",
                    }
                ],
                "freshness": {"stale": False, "stale_after_days": 7},
            },
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {"cash_weight": 0.2, "equity_weight": 0.8, "status": "RESEARCH_ONLY"}
        },
    )
    d = build_daily_personal_decision(
        pp_db,
        portfolio=portfolio,
        as_of=date(2026, 9, 20),
        new_cash_rub=Decimal("30000"),
    )
    assert d["context"]["candidate_freshness_known"] is False
    assert d["context"]["candidate_stale"] is False
    uw = _scenario(d, "TARGET_UNDERWEIGHTS")
    assert uw["status"] != "available"
    assert "CANDIDATE_FRESHNESS_UNKNOWN" in (uw.get("limitations") or [])
    assert uw.get("purchases") == []


def test_decision_v2_live_preview_not_falsely_stale(pp_db, monkeypatch):
    portfolio = _reset(pp_db, "dd-v2-lp")
    eq = _equity(pp_db, "DDV2LP", close=Decimal("100"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-lp-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq.id,
        units=Decimal("100"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-lp-buy",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: None,
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.preview_portfolio_candidate",
        lambda session, **kwargs: {
            "candidate_id": "live",
            "positions": [
                {
                    "symbol": "DDV2LP",
                    "weight": 0.4,
                    "instrument_id": eq.id,
                    "asset_class": "equity",
                }
            ],
            "freshness": {"stale": False, "stale_after_days": 7},
        },
    )
    monkeypatch.setattr(
        "app.modules.investment.application.risk_opportunity_service.run_investment_decision",
        lambda session, **kwargs: {
            "decision": {"cash_weight": 0.2, "equity_weight": 0.8, "status": "RESEARCH_ONLY"}
        },
    )
    d = build_daily_personal_decision(
        pp_db,
        portfolio=portfolio,
        as_of=date(2026, 9, 20),
        new_cash_rub=Decimal("30000"),
    )
    assert d["context"]["candidate_source"] == "live_preview"
    assert d["context"]["candidate_stale"] is False
    assert d["context"]["candidate_freshness_known"] is True
    uw = _scenario(d, "TARGET_UNDERWEIGHTS")
    assert uw["status"] == "available"


def test_compare_preserves_zero_candidate_weight(pp_db, monkeypatch):
    portfolio = _reset(pp_db, "dd-v2-zw")
    eq = _equity(pp_db, "DDV2ZW", close=Decimal("100"))
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="DEPOSIT",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        amount=Decimal("100000"),
        idempotency_key="dd-zw-dep",
    )
    create_operation(
        pp_db,
        portfolio=portfolio,
        operation_type="BUY",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        instrument_id=eq.id,
        units=Decimal("100"),
        price=Decimal("100"),
        non_standard_lot=True,
        idempotency_key="dd-zw-buy",
    )
    monkeypatch.setattr(
        "app.modules.portfolio.application.manual_portfolio_service.get_latest_candidate_snapshot",
        lambda session: {
            "candidate_id": "zw-1",
            "as_of": "2026-09-18",
            "status": "READY",
            "payload": {
                "candidate_id": "zw-1",
                "positions": [
                    {
                        "symbol": "DDV2ZW",
                        "weight": 0,
                        "instrument_id": eq.id,
                        "asset_class": "equity",
                    }
                ],
                "freshness": {
                    "stale": False,
                    "stale_after_days": 7,
                    "market_as_of": "2026-09-18",
                },
            },
        },
    )
    from app.modules.portfolio.application.manual_portfolio_service import compare_to_candidate

    compare = compare_to_candidate(pp_db, portfolio=portfolio, as_of=date(2026, 9, 20))
    row = next(r for r in compare["comparisons"] if r["symbol"] == "DDV2ZW")
    assert row["candidate_weight"] == 0.0
    assert row["status"] == "BOTH"
    assert row["status"] != "NOT_IN_CANDIDATE"
