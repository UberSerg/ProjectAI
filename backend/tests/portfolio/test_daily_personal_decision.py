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
        lambda session, portfolio=None: {
            "actual_source": "personal_portfolio",
            "candidate_source": "preview",
            "candidate_id": "cash",
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

    def boom_compare(session, portfolio=None):
        raise RuntimeError("candidate down")

    def boom_rebalance(session, portfolio=None):
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
