"""Shadow Decision Journal read-model tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.modules.shadow.application.decision_journal import (
    LEGACY_TRACE_MESSAGE_RU,
    build_candidate_history,
    build_shadow_journal,
)
from app.modules.shadow.infrastructure.models import (
    ShadowDecision,
    ShadowFill,
    ShadowNavDaily,
    ShadowOrder,
    ShadowPortfolio,
    ShadowPortfolioSpec,
)


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


def _seed_spec(session: Session, *, name: str | None = None) -> ShadowPortfolioSpec:
    spec = ShadowPortfolioSpec(
        experiment_group="SHADOW_TEST_JOURNAL",
        name=name or _unique("spec"),
        version="v2",
        config_hash=_unique("cfg"),
        candidate_name="test",
        candidate_version="v0",
        candidate_config_hash="candhash",
        dataset_values_hash=None,
        policy_name="RankHysteresisLongOnlyV1",
        risk_name="NoRisk",
        entry_quantile=0.2,
        exit_quantile=0.35,
        min_trade_weight_delta=0.02,
        max_single_weight=0.2,
        initial_capital=1_000_000.0,
        commission_bps=30.0,
        slippage_bps=5.0,
        fractional_shares=False,
        dividend_cash=False,
        payload={"execution_version": "LOT_AWARE_V2"},
    )
    session.add(spec)
    session.flush()
    return spec


def _seed_portfolio(session: Session, spec: ShadowPortfolioSpec) -> ShadowPortfolio:
    portfolio = ShadowPortfolio(
        spec_id=spec.id,
        status="ACTIVE",
        activated_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        cash=900_000.0,
        peak_nav=1_000_000.0,
        exposure_cap=1.0,
        risk_mode="normal",
        positions={},
        provenance={},
        warnings=[],
    )
    session.add(portfolio)
    session.flush()
    return portfolio


def _seed_decision(
    session: Session,
    portfolio: ShadowPortfolio,
    *,
    signal_day: date,
    iso_week: str,
    metadata: dict | None = None,
) -> ShadowDecision:
    decision = ShadowDecision(
        portfolio_id=portfolio.id,
        forward_batch_id=1,
        signal_as_of_date=signal_day,
        signal_generated_at=datetime.combine(signal_day, datetime.min.time(), tzinfo=UTC),
        decision_at=datetime.combine(signal_day, datetime.min.time(), tzinfo=UTC).replace(
            hour=18
        ),
        iso_week=iso_week,
        policy_name="RankHysteresisLongOnlyV1",
        risk_name="NoRisk",
        risk_mode="normal",
        exposure_cap=1.0,
        targets=[],
        metadata_=metadata or {},
    )
    session.add(decision)
    session.flush()
    return decision


def _seed_order(
    session: Session,
    portfolio: ShadowPortfolio,
    decision: ShadowDecision,
    *,
    ticker: str,
    side: str,
    instrument_id: int,
    quantity: float = 10.0,
    status: str = "FILLED",
    execution_date: date | None = None,
) -> ShadowOrder:
    order = ShadowOrder(
        portfolio_id=portfolio.id,
        decision_id=decision.id,
        instrument_id=instrument_id,
        ticker=ticker,
        side=side,
        target_weight=0.1,
        target_notional=10_000.0,
        quantity=quantity,
        reason="TEST",
        status=status,
        rank=3,
        predicted_return_20d=0.05,
        eligible_count=40,
        decision_at=decision.decision_at,
        min_execution_date=decision.signal_as_of_date,
        execution_date=execution_date,
        metadata_={},
    )
    session.add(order)
    session.flush()
    return order


def _seed_fill(
    session: Session,
    portfolio: ShadowPortfolio,
    order: ShadowOrder,
    *,
    execution_date: date,
) -> ShadowFill:
    fill = ShadowFill(
        portfolio_id=portfolio.id,
        order_id=order.id,
        instrument_id=order.instrument_id,
        ticker=order.ticker,
        side=order.side,
        quantity=float(order.quantity),
        raw_open=100.0,
        fill_price=100.1,
        notional=float(order.quantity) * 100.1,
        commission=30.0,
        slippage_cost=5.0,
        execution_date=execution_date,
        decision_at=order.decision_at,
        filled_at=datetime.combine(execution_date, datetime.min.time(), tzinfo=UTC),
        metadata_={},
    )
    session.add(fill)
    session.flush()
    return fill


def _seed_nav(
    session: Session,
    portfolio: ShadowPortfolio,
    *,
    as_of: date,
    nav: float = 1_000_000.0,
) -> ShadowNavDaily:
    row = ShadowNavDaily(
        portfolio_id=portfolio.id,
        as_of_date=as_of,
        cash=500_000.0,
        market_value=nav - 500_000.0,
        nav=nav,
        gross_exposure=0.5,
        drawdown=0.0,
        peak_nav=nav,
        position_count=2,
        benchmark_value=None,
    )
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def journal_fixture(core_db: Session):
    """Two portfolios: A with V3 traces, B legacy + cross-leak counterexample."""
    spec_a = _seed_spec(core_db, name=_unique("A"))
    spec_b = _seed_spec(core_db, name=_unique("B"))
    pa = _seed_portfolio(core_db, spec_a)
    pb = _seed_portfolio(core_db, spec_b)

    d1 = _seed_decision(
        core_db,
        pa,
        signal_day=date(2026, 9, 2),
        iso_week="2026-W36",
        metadata={
            "candidate_traces": [
                {
                    "instrument_id": 101,
                    "ticker": "SBER",
                    "rank": 2,
                    "decision_action": "ENTER",
                    "reason_codes": ["TOP_ENTRY_BAND"],
                    "buy_fee_estimate": 30.0,
                    "sell_fee_estimate": 0.0,
                    "slippage_estimate": 5.0,
                    "net_edge": 0.04,
                    "chain_of_thought": "SECRET_MUST_NOT_LEAK",
                },
                {
                    "instrument_id": 202,
                    "ticker": "LKOH",
                    "rank": 18,
                    "decision_action": "HOLD",
                    "reason_codes": ["WITHIN_EXIT_BAND"],
                    "net_edge": 0.0,
                    "review_trigger": False,
                },
                {
                    "instrument_id": 303,
                    "ticker": "GAZP",
                    "rank": 25,
                    "decision_action": "REVIEW_HOLD",
                    "reason_codes": ["EXIT_BAND_INSUFFICIENT_EDGE"],
                    "replacement_ticker": "SBER",
                    "sell_fee_estimate": 40.0,
                    "buy_fee_estimate": 35.0,
                    "slippage_estimate": 8.0,
                    "net_edge": -0.01,
                    "review_trigger": True,
                },
            ]
        },
    )
    o_buy = _seed_order(
        core_db,
        pa,
        d1,
        ticker="SBER",
        side="BUY",
        instrument_id=101,
        execution_date=date(2026, 9, 3),
    )
    _seed_fill(core_db, pa, o_buy, execution_date=date(2026, 9, 3))
    _seed_nav(core_db, pa, as_of=date(2026, 9, 2), nav=1_000_000.0)
    _seed_nav(core_db, pa, as_of=date(2026, 9, 3), nav=1_001_000.0)

    d2 = _seed_decision(
        core_db,
        pa,
        signal_day=date(2026, 9, 9),
        iso_week="2026-W37",
        metadata={
            "candidate_traces": [
                {
                    "instrument_id": 101,
                    "ticker": "SBER",
                    "rank": 4,
                    "decision_action": "HOLD",
                    "reason_codes": ["WITHIN_EXIT_BAND"],
                },
                {
                    "instrument_id": 303,
                    "ticker": "GAZP",
                    "rank": 30,
                    "decision_action": "ROTATE",
                    "reason_codes": ["NET_EDGE_POSITIVE"],
                    "replacement_ticker": "ROSN",
                    "sell_fee_estimate": 40.0,
                    "buy_fee_estimate": 35.0,
                    "slippage_estimate": 8.0,
                    "net_edge": 0.03,
                },
            ]
        },
    )
    o_sell = _seed_order(
        core_db,
        pa,
        d2,
        ticker="GAZP",
        side="SELL",
        instrument_id=303,
        execution_date=date(2026, 9, 10),
    )
    _seed_fill(core_db, pa, o_sell, execution_date=date(2026, 9, 10))
    _seed_nav(core_db, pa, as_of=date(2026, 9, 9), nav=1_002_000.0)

    # Legacy V2 decision on portfolio B — no candidate_traces
    d_legacy = _seed_decision(
        core_db,
        pb,
        signal_day=date(2026, 9, 2),
        iso_week="2026-W36",
        metadata={"eligible_n": 40, "kind": "FORWARD_SHADOW"},
    )
    o_legacy = _seed_order(
        core_db,
        pb,
        d_legacy,
        ticker="SBER",
        side="BUY",
        instrument_id=101,
        execution_date=date(2026, 9, 3),
    )
    _seed_fill(core_db, pb, o_legacy, execution_date=date(2026, 9, 3))
    _seed_nav(core_db, pb, as_of=date(2026, 9, 2), nav=999_000.0)

    # Extra day on A for pagination
    _seed_decision(
        core_db,
        pa,
        signal_day=date(2026, 9, 16),
        iso_week="2026-W38",
        metadata={
            "candidate_traces": [
                {
                    "instrument_id": 101,
                    "ticker": "SBER",
                    "rank": 5,
                    "decision_action": "HOLD",
                    "reason_codes": ["WITHIN_EXIT_BAND"],
                }
            ]
        },
    )
    _seed_nav(core_db, pa, as_of=date(2026, 9, 16), nav=1_003_000.0)

    core_db.flush()
    return {"session": core_db, "portfolio_a": pa, "portfolio_b": pb}


def test_journal_joins_decision_orders_fills_nav(journal_fixture) -> None:
    session = journal_fixture["session"]
    pa = journal_fixture["portfolio_a"]
    payload = build_shadow_journal(session, portfolio_id=int(pa.id))
    assert payload is not None
    assert payload["portfolio_id"] == pa.id
    days = {d["date"]: d for d in payload["days"]}

    day_signal = days["2026-09-02"]
    assert day_signal["detail_available"] is True
    assert day_signal["message_ru"] is None
    assert day_signal["decision"]["id"] is not None
    assert day_signal["nav"]["nav"] == 1_000_000.0
    tickers = {c["ticker"] for c in day_signal["candidates"]}
    assert tickers == {"SBER", "LKOH", "GAZP"}
    assert day_signal["counts"]["buy"] >= 1
    assert day_signal["counts"]["hold"] >= 1
    assert day_signal["counts"]["review"] >= 1
    # CoT must never appear in public trace
    for c in day_signal["candidates"]:
        assert "chain_of_thought" not in c

    day_fill = days["2026-09-03"]
    assert len(day_fill["fills"]) == 1
    assert day_fill["fills"][0]["ticker"] == "SBER"
    assert day_fill["fills"][0]["commission"] == 30.0
    assert day_fill["total_modeled_costs"]["commission"] == 30.0
    assert day_fill["nav"]["nav"] == 1_001_000.0


def test_journal_filters_ticker_and_action(journal_fixture) -> None:
    session = journal_fixture["session"]
    pa = journal_fixture["portfolio_a"]

    by_ticker = build_shadow_journal(session, portfolio_id=int(pa.id), ticker="GAZP")
    assert by_ticker is not None
    assert by_ticker["returned_days"] >= 1
    for day in by_ticker["days"]:
        for c in day["candidates"]:
            assert c["ticker"] == "GAZP"
        for o in day["orders"]:
            assert o["ticker"] == "GAZP"
        for f in day["fills"]:
            assert f["ticker"] == "GAZP"

    by_action = build_shadow_journal(session, portfolio_id=int(pa.id), action="REVIEW")
    assert by_action is not None
    assert by_action["returned_days"] >= 1
    for day in by_action["days"]:
        assert day["candidates"]
        assert all(
            str(c["decision_action"]).upper().startswith("REVIEW") for c in day["candidates"]
        )


def test_journal_date_range_and_pagination(journal_fixture) -> None:
    session = journal_fixture["session"]
    pa = journal_fixture["portfolio_a"]

    ranged = build_shadow_journal(
        session,
        portfolio_id=int(pa.id),
        date_from=date(2026, 9, 3),
        date_to=date(2026, 9, 10),
    )
    assert ranged is not None
    dates = [d["date"] for d in ranged["days"]]
    assert all(date(2026, 9, 3) <= date.fromisoformat(x) <= date(2026, 9, 10) for x in dates)
    assert "2026-09-02" not in dates
    assert "2026-09-16" not in dates

    limited = build_shadow_journal(session, portfolio_id=int(pa.id), limit=2)
    assert limited is not None
    assert limited["returned_days"] == 2
    assert limited["truncated"] is True
    # most recent 2 days, ascending
    assert limited["days"][0]["date"] < limited["days"][1]["date"]
    assert limited["days"][-1]["date"] == "2026-09-16"


def test_journal_no_cross_portfolio_leak(journal_fixture) -> None:
    session = journal_fixture["session"]
    pa = journal_fixture["portfolio_a"]
    pb = journal_fixture["portfolio_b"]

    ja = build_shadow_journal(session, portfolio_id=int(pa.id))
    jb = build_shadow_journal(session, portfolio_id=int(pb.id))
    assert ja is not None and jb is not None

    a_navs = {d["nav"]["nav"] for d in ja["days"] if d.get("nav")}
    b_navs = {d["nav"]["nav"] for d in jb["days"] if d.get("nav")}
    assert 999_000.0 not in a_navs
    assert 1_000_000.0 not in b_navs

    for day in ja["days"]:
        if day.get("decision"):
            assert day["decision"]["id"]  # belongs to A via query scope
    for day in jb["days"]:
        for f in day["fills"]:
            # B only has SBER fill; must not contain A's GAZP fill
            assert f["ticker"] != "GAZP"

    assert build_shadow_journal(session, portfolio_id=9_999_999) is None


def test_legacy_v2_without_candidate_traces_degrades(journal_fixture) -> None:
    session = journal_fixture["session"]
    pb = journal_fixture["portfolio_b"]

    payload = build_shadow_journal(session, portfolio_id=int(pb.id))
    assert payload is not None
    day = next(d for d in payload["days"] if d["date"] == "2026-09-02")
    assert day["detail_available"] is False
    assert day["message_ru"] == LEGACY_TRACE_MESSAGE_RU
    assert day["candidates"] == []
    # Orders/fills still present from real data — not invented
    assert len(day["orders"]) == 1
    assert day["orders"][0]["ticker"] == "SBER"

    hist = build_candidate_history(session, portfolio_id=int(pb.id), ticker="SBER")
    assert hist is not None
    assert hist["events"]
    assert all(e["detail_available"] is False for e in hist["events"])
    assert all(e["message_ru"] == LEGACY_TRACE_MESSAGE_RU for e in hist["events"])
    assert all(e["trace"] is None for e in hist["events"])


def test_candidate_history_lifecycle(journal_fixture) -> None:
    session = journal_fixture["session"]
    pa = journal_fixture["portfolio_a"]

    hist = build_candidate_history(session, portfolio_id=int(pa.id), ticker="sber")
    assert hist is not None
    assert hist["ticker"] == "SBER"
    assert hist["detail_available"] is True
    actions = [e["action"] for e in hist["events"]]
    assert "ENTER" in actions
    assert "HOLD" in actions
    assert hist["summary"]["first_seen"] == "2026-09-02"
    assert hist["summary"]["event_count"] >= 2
    # ENTER event linked to order + fill
    enter = next(e for e in hist["events"] if e["action"] == "ENTER")
    assert enter["order"] is not None
    assert enter["order"]["side"] == "BUY"
    assert enter["fill"] is not None
    assert enter["fill"]["fill_price"] == 100.1
    assert enter["nav_at_signal"]["nav"] == 1_000_000.0

    gazp = build_candidate_history(session, portfolio_id=int(pa.id), ticker="GAZP")
    assert gazp is not None
    gazp_actions = [e["action"] for e in gazp["events"]]
    assert "REVIEW_HOLD" in gazp_actions
    assert "ROTATE" in gazp_actions
    rotate = next(e for e in gazp["events"] if e["action"] == "ROTATE")
    assert rotate["replacement_ticker"] == "ROSN"
    assert rotate["fill"] is not None


def test_candidate_history_no_cross_portfolio_leak(journal_fixture) -> None:
    session = journal_fixture["session"]
    pa = journal_fixture["portfolio_a"]
    pb = journal_fixture["portfolio_b"]

    hist_a = build_candidate_history(session, portfolio_id=int(pa.id), ticker="SBER")
    hist_b = build_candidate_history(session, portfolio_id=int(pb.id), ticker="SBER")
    assert hist_a is not None and hist_b is not None
    assert any(e["detail_available"] for e in hist_a["events"])
    assert all(not e["detail_available"] for e in hist_b["events"])
    # A's ENTER trace must not appear on B
    assert not any(e.get("action") == "ENTER" and e.get("detail_available") for e in hist_b["events"])
    assert build_candidate_history(session, portfolio_id=9_999_999, ticker="SBER") is None
