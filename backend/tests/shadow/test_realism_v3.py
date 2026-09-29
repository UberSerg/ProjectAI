"""Shadow Realism V3 — sell economics gate, FeeEngine fees, V2 untouched."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.modules.investment.domain.fixed_income import TransactionCostProfile
from app.modules.portfolio.domain.fee_engine import (
    FeeEngine,
    FeeEstimateContext,
    FeeStatus,
    sber_investment_builtin_rules,
)
from app.modules.shadow.application.lot_aware import (
    EXECUTION_VERSION_SELL_ECONOMICS_V3,
    is_lot_aware_spec,
    is_sell_economics_v3_spec,
)
from app.modules.shadow.config import (
    EXECUTION_VERSION_LOT_AWARE_V2,
    EXPERIMENT_GROUP_V2,
    EXPERIMENT_GROUP_V3,
    FEE_PROFILE_CODE_SBER_INVESTMENT,
    portfolio_a_config,
    realism_v2_shadow_configs,
    realism_v3_shadow_configs,
)
from app.modules.shadow.domain.fee_estimate import (
    BpsFeeEstimator,
    FeeEngineEstimator,
    UnknownFeeEstimator,
    estimate_shadow_fee,
    resolve_broker_fee_estimator,
)
from app.modules.shadow.domain.lot_plan import PlanInstrument, build_lot_order_plan
from app.modules.shadow.domain.sell_gate import (
    DATA_HOLD,
    EXIT_TO_CASH,
    HOLD,
    REVIEW_HOLD,
    RISK_EXIT,
    RISK_REDUCE,
    ROTATE,
    HeldName,
    PolicyTarget,
    ReplacementCandidate,
    SellGateParams,
    apply_sell_gate,
)


def _held(
    iid: int,
    *,
    expected: float,
    rank: int,
    qty: float = 100.0,
    price: float = 100.0,
    weight: float = 0.2,
    semantic: str = "EXPECTED_RETURN",
    stale: bool = False,
    in_band: bool = False,
) -> HeldName:
    return HeldName(
        instrument_id=iid,
        ticker=f"T{iid}",
        quantity=qty,
        current_weight=weight,
        rank=rank,
        prediction_semantic=semantic,
        expected_return=expected if semantic == "EXPECTED_RETURN" else None,
        signal_as_of=date(2026, 9, 15),
        price=price,
        in_exit_band=in_band,
        signal_stale=stale,
        review_trigger=not in_band,
    )


def _cand(
    iid: int,
    *,
    expected: float,
    rank: int,
    price: float = 100.0,
    semantic: str = "EXPECTED_RETURN",
    stale: bool = False,
) -> ReplacementCandidate:
    return ReplacementCandidate(
        instrument_id=iid,
        ticker=f"T{iid}",
        rank=rank,
        prediction_semantic=semantic,
        expected_return=expected if semantic == "EXPECTED_RETURN" else None,
        price=price,
        signal_as_of=date(2026, 9, 15),
        signal_stale=stale,
    )


def _fee() -> FeeEngineEstimator:
    return FeeEngineEstimator(FeeEngine(sber_investment_builtin_rules()))


def _perm_map(result):
    return {p.instrument_id: p for p in result.permissions}


def _plan_from_gate(
    result,
    *,
    held: list[HeldName],
    nav: float | None = None,
    cash: float = 10_000.0,
):
    """End-to-end gate → PlanInstrument → lot plan (unit-level, no DB)."""
    held_by = {h.instrument_id: h for h in held}
    perm_by = _perm_map(result)
    target_by = {t.instrument_id: t for t in result.targets}
    all_ids = set(target_by) | set(held_by)
    # Derive NAV from marks so current_weight matches HeldName weights.
    if nav is None:
        mv = sum(
            float(h.quantity) * float(h.price or 0)
            for h in held
            if h.price and h.price > 0
        )
        nav = mv + float(cash) if mv > 0 else 100_000.0
    instruments: list[PlanInstrument] = []
    for iid in sorted(all_ids):
        h = held_by.get(iid)
        t = target_by.get(iid)
        tw = float(t.target_weight) if t is not None else 0.0
        qty = float(h.quantity) if h is not None else 0.0
        px = h.price if h is not None else None
        if t is not None and px is None:
            px = 100.0
        perm = perm_by.get(iid)
        sell_allowed = True
        max_sell_units = None
        if perm is not None:
            sell_allowed = perm.sell_allowed
            max_sell_units = perm.max_sell_units
        elif qty > 0 and tw <= 0:
            sell_allowed = False
        instruments.append(
            PlanInstrument(
                instrument_id=iid,
                ticker=(t.ticker if t else h.ticker if h else str(iid)),
                target_weight=Decimal(str(tw)),
                current_units=Decimal(str(qty)),
                price=Decimal(str(px)) if px and px > 0 else None,
                lot_size=1,
                rank=t.rank if t is not None else (h.rank if h else None),
                sell_allowed=sell_allowed,
                max_sell_units=max_sell_units,
            )
        )
    return build_lot_order_plan(
        instruments,
        cash=Decimal(str(cash)),
        nav=Decimal(str(nav)),
        costs=TransactionCostProfile(broker_bps=Decimal("0"), slippage_bps=Decimal("0")),
    )


def test_v3_configs_distinct_from_v2() -> None:
    a, b = realism_v3_shadow_configs()
    assert a.experiment_group == EXPERIMENT_GROUP_V3 == b.experiment_group
    assert a.execution_version == EXECUTION_VERSION_SELL_ECONOMICS_V3
    assert a.fee_profile_code == FEE_PROFILE_CODE_SBER_INVESTMENT
    assert a.fee_profile_version == 1
    assert a.commission_bps == 0.0
    assert a.min_net_rotation_edge_bps == 0.0
    assert a.fractional_shares is False
    assert b.risk_name != a.risk_name
    v2a, _ = realism_v2_shadow_configs()
    assert v2a.experiment_group == EXPERIMENT_GROUP_V2
    assert v2a.execution_version == EXECUTION_VERSION_LOT_AWARE_V2
    assert v2a.commission_bps == 0.0
    assert v2a.fee_profile_code is None
    assert a.config_hash() != v2a.config_hash()
    assert portfolio_a_config().experiment_group != EXPERIMENT_GROUP_V3
    assert is_sell_economics_v3_spec(a)
    assert not is_sell_economics_v3_spec(v2a)
    assert is_lot_aware_spec(a)
    assert is_lot_aware_spec(v2a)


def test_fee_engine_sber_point_three_percent() -> None:
    est = resolve_broker_fee_estimator(fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT)
    fee = est.broker_fee_estimate(
        side="SELL",
        notional=Decimal("100000"),
        instrument_id=1,
        as_of=date(2026, 10, 1),
        instrument_symbol="SBER",
    )
    assert fee is not None
    assert abs(fee - Decimal("300")) < Decimal("0.01")
    raw = FeeEngine(sber_investment_builtin_rules()).estimate_fee(
        FeeEstimateContext(
            as_of=date(2026, 10, 1),
            side="BUY",
            notional=Decimal("100000"),
            instrument_symbol="GAZP",
        )
    )
    assert raw.status == FeeStatus.KNOWN
    assert raw.amount is not None
    assert abs(raw.amount - Decimal("300")) < Decimal("0.01")


def test_fee_engine_sber_unknown_before_generic_valid_from() -> None:
    est = resolve_broker_fee_estimator(fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT)
    fee = est.broker_fee_estimate(
        side="BUY",
        notional=Decimal("100000"),
        instrument_id=1,
        as_of=date(2026, 9, 1),
        instrument_symbol="SBER",
    )
    assert fee is None
    raw = FeeEngine(sber_investment_builtin_rules()).estimate_fee(
        FeeEstimateContext(
            as_of=date(2026, 9, 1),
            side="BUY",
            notional=Decimal("100000"),
            instrument_symbol="SBER",
        )
    )
    assert raw.status == FeeStatus.UNKNOWN
    assert raw.amount is None


def test_rank_breach_alone_no_sell_insufficient_edge() -> None:
    held = [_held(1, expected=0.02, rank=40)]
    policy = [
        PolicyTarget(
            instrument_id=2,
            ticker="T2",
            target_weight=0.2,
            rank=1,
            prediction_semantic="EXPECTED_RETURN",
            expected_return=0.024,
            action="ENTER_TOP20",
            price=100.0,
        )
    ]
    result = apply_sell_gate(
        held=held,
        policy_targets=policy,
        replacement_candidates=[_cand(2, expected=0.024, rank=1)],
        params=SellGateParams(
            slippage_bps=0.0,
            min_net_rotation_edge_bps=0.0,
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=1,
            as_of=date(2026, 10, 1),
        ),
        fee_estimator=_fee(),
        eligible_count=50,
    )
    assert 1 in {t.instrument_id for t in result.targets}
    assert 2 not in {t.instrument_id for t in result.targets}
    tr = next(t for t in result.traces if t.instrument_id == 1)
    assert tr.decision_action == REVIEW_HOLD
    assert tr.review_trigger is True
    assert "INSUFFICIENT_NET_EDGE" in tr.limitation_codes
    perm = _perm_map(result)[1]
    assert perm.sell_allowed is False
    assert perm.action == REVIEW_HOLD
    tw = next(t for t in result.targets if t.instrument_id == 1).target_weight
    assert abs(tw - 0.2) < 1e-12


def test_sufficient_edge_rotates() -> None:
    held = [_held(1, expected=0.01, rank=40)]
    policy = [
        PolicyTarget(
            instrument_id=2,
            ticker="T2",
            target_weight=0.2,
            rank=1,
            prediction_semantic="EXPECTED_RETURN",
            expected_return=0.08,
            action="ENTER_TOP20",
            price=100.0,
        )
    ]
    result = apply_sell_gate(
        held=held,
        policy_targets=policy,
        replacement_candidates=[_cand(2, expected=0.08, rank=1)],
        params=SellGateParams(
            slippage_bps=0.0,
            min_net_rotation_edge_bps=0.0,
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=1,
            as_of=date(2026, 10, 1),
        ),
        fee_estimator=_fee(),
        eligible_count=50,
    )
    ids = {t.instrument_id for t in result.targets}
    assert 1 not in ids
    assert 2 in ids
    tr = next(t for t in result.traces if t.instrument_id == 1)
    assert tr.decision_action == ROTATE
    assert tr.replacement_instrument_id == 2
    assert tr.net_edge is not None and tr.net_edge > 0
    assert tr.sell_fee_estimate is not None and tr.buy_fee_estimate is not None
    perm = _perm_map(result)[1]
    assert perm.sell_allowed is True
    assert perm.action == ROTATE
    assert perm.rotate_to == 2
    assert perm.reason == "ROTATE_TO_T2"


def test_slippage_affects_threshold_separately() -> None:
    held = [_held(1, expected=0.01, rank=40, qty=100, price=100)]
    b_exp = 0.017
    common: dict = dict(
        held=held,
        policy_targets=[
            PolicyTarget(
                instrument_id=2,
                ticker="T2",
                target_weight=0.2,
                rank=1,
                prediction_semantic="EXPECTED_RETURN",
                expected_return=b_exp,
                action="ENTER_TOP20",
                price=100.0,
            )
        ],
        replacement_candidates=[_cand(2, expected=b_exp, rank=1)],
        fee_estimator=_fee(),
        eligible_count=40,
    )
    ok = apply_sell_gate(
        **common,
        params=SellGateParams(
            slippage_bps=0.0,
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=1,
            as_of=date(2026, 10, 1),
        ),
    )
    blocked = apply_sell_gate(
        **common,
        params=SellGateParams(
            slippage_bps=10.0,
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=1,
            as_of=date(2026, 10, 1),
        ),
    )
    assert next(t for t in ok.traces if t.instrument_id == 1).decision_action == ROTATE
    assert next(t for t in blocked.traces if t.instrument_id == 1).decision_action == REVIEW_HOLD


def test_non_comparable_prediction_data_hold() -> None:
    held = [_held(1, expected=0.02, rank=40, semantic="RANKING_SCORE")]
    result = apply_sell_gate(
        held=held,
        policy_targets=[],
        replacement_candidates=[_cand(2, expected=0.99, rank=1, semantic="RANKING_SCORE")],
        params=SellGateParams(fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT, k_entry=1),
        fee_estimator=_fee(),
    )
    assert 1 in {t.instrument_id for t in result.targets}
    assert next(t for t in result.traces if t.instrument_id == 1).decision_action == DATA_HOLD
    assert _perm_map(result)[1].sell_allowed is False


def test_stale_signal_no_economic_rotation() -> None:
    held = [_held(1, expected=0.01, rank=40, stale=True)]
    result = apply_sell_gate(
        held=held,
        policy_targets=[],
        replacement_candidates=[_cand(2, expected=0.50, rank=1)],
        params=SellGateParams(fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT, k_entry=1),
        fee_estimator=_fee(),
    )
    tr = next(t for t in result.traces if t.instrument_id == 1)
    assert tr.decision_action == DATA_HOLD
    assert "STALE_SIGNAL" in tr.limitation_codes
    assert 1 in {t.instrument_id for t in result.targets}
    assert _perm_map(result)[1].sell_allowed is False


def test_risk_can_force_exit_and_reduce() -> None:
    held = [
        _held(1, expected=0.02, rank=40),
        _held(2, expected=0.03, rank=5, in_band=True, weight=0.4),
    ]
    policy = [
        PolicyTarget(
            instrument_id=2,
            ticker="T2",
            target_weight=0.2,
            rank=5,
            prediction_semantic="EXPECTED_RETURN",
            expected_return=0.03,
            action="HOLD_WITHIN_EXIT_BAND",
            price=100.0,
        )
    ]
    result = apply_sell_gate(
        held=held,
        policy_targets=policy,
        replacement_candidates=[],
        params=SellGateParams(
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=2,
            exposure_cap=0.5,
        ),
        fee_estimator=_fee(),
        risk_forced={1: RISK_EXIT, 2: RISK_REDUCE},
    )
    ids = {t.instrument_id for t in result.targets}
    assert 1 not in ids
    assert 2 in ids
    actions = {t.instrument_id: t.decision_action for t in result.traces}
    assert actions[1] == RISK_EXIT
    assert actions[2] == RISK_REDUCE
    tw = next(t for t in result.targets if t.instrument_id == 2).target_weight
    assert abs(tw - 0.4 * 0.5) < 1e-12
    perms = _perm_map(result)
    assert perms[1].sell_allowed is True and perms[1].action == RISK_EXIT
    assert perms[2].sell_allowed is True and perms[2].action == RISK_REDUCE
    assert perms[2].max_sell_fraction is not None
    assert abs(perms[2].max_sell_fraction - 0.5) < 1e-12


def test_exit_to_cash_explicit_reason() -> None:
    held = [_held(1, expected=0.02, rank=40)]
    result = apply_sell_gate(
        held=held,
        policy_targets=[],
        replacement_candidates=[],
        params=SellGateParams(k_entry=1),
        fee_estimator=_fee(),
        risk_forced={1: EXIT_TO_CASH},
    )
    assert 1 not in {t.instrument_id for t in result.targets}
    tr = next(t for t in result.traces if t.instrument_id == 1)
    assert tr.decision_action == EXIT_TO_CASH
    assert "EXPLICIT_EXIT_TO_CASH" in tr.reason_codes
    assert _perm_map(result)[1].sell_allowed is True


def test_retained_position_stays_in_targets_no_phantom_funding() -> None:
    held = [
        _held(10, expected=0.02, rank=3, in_band=True, weight=0.5),
        _held(1, expected=0.015, rank=40, weight=0.5),
    ]
    policy = [
        PolicyTarget(
            instrument_id=10,
            ticker="T10",
            target_weight=0.5,
            rank=3,
            prediction_semantic="EXPECTED_RETURN",
            expected_return=0.02,
            action="HOLD_WITHIN_EXIT_BAND",
            price=100.0,
        ),
        PolicyTarget(
            instrument_id=2,
            ticker="T2",
            target_weight=0.5,
            rank=1,
            prediction_semantic="EXPECTED_RETURN",
            expected_return=0.018,
            action="ENTER_TOP20",
            price=100.0,
        ),
    ]
    result = apply_sell_gate(
        held=held,
        policy_targets=policy,
        replacement_candidates=[_cand(2, expected=0.018, rank=1)],
        params=SellGateParams(
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=2,
            as_of=date(2026, 10, 1),
        ),
        fee_estimator=_fee(),
    )
    ids = {t.instrument_id for t in result.targets}
    assert 1 in ids and 10 in ids
    assert 2 not in ids
    assert next(t for t in result.traces if t.instrument_id == 1).decision_action == REVIEW_HOLD
    tws = {t.instrument_id: t.target_weight for t in result.targets}
    assert abs(tws[1] - 0.5) < 1e-12
    assert abs(tws[10] - 0.5) < 1e-12
    assert _perm_map(result)[1].sell_allowed is False
    assert _perm_map(result)[10].sell_allowed is False


def test_rotate_sell_proceeds_fund_buy_long_only() -> None:
    held = [_held(1, expected=0.01, rank=40, qty=50, price=200)]
    result = apply_sell_gate(
        held=held,
        policy_targets=[
            PolicyTarget(
                instrument_id=2,
                ticker="T2",
                target_weight=1.0,
                rank=1,
                prediction_semantic="EXPECTED_RETURN",
                expected_return=0.08,
                action="ENTER_TOP20",
                price=50.0,
            )
        ],
        replacement_candidates=[_cand(2, expected=0.08, rank=1, price=50.0)],
        params=SellGateParams(
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=1,
            as_of=date(2026, 10, 1),
        ),
        fee_estimator=_fee(),
    )
    assert {t.instrument_id for t in result.targets} == {2}
    tr = next(t for t in result.traces if t.instrument_id == 1)
    assert tr.decision_action == ROTATE
    assert all(t.target_weight > 0 for t in result.targets)
    assert all(t.target_weight <= 1.0 + 1e-12 for t in result.targets)


def test_within_band_hold_trace() -> None:
    held = [_held(1, expected=0.02, rank=5, in_band=True)]
    policy = [
        PolicyTarget(
            instrument_id=1,
            ticker="T1",
            target_weight=1.0,
            rank=5,
            prediction_semantic="EXPECTED_RETURN",
            expected_return=0.02,
            action="HOLD_WITHIN_EXIT_BAND",
            price=100.0,
        )
    ]
    result = apply_sell_gate(
        held=held,
        policy_targets=policy,
        replacement_candidates=[],
        params=SellGateParams(k_entry=1),
        fee_estimator=_fee(),
    )
    assert next(t for t in result.traces if t.instrument_id == 1).decision_action == HOLD
    assert _perm_map(result)[1].sell_allowed is False


def test_v2_spec_helper_untouched() -> None:
    spec = SimpleNamespace(
        fractional_shares=False,
        payload={"execution_version": EXECUTION_VERSION_LOT_AWARE_V2},
        execution_version=EXECUTION_VERSION_LOT_AWARE_V2,
    )
    assert is_lot_aware_spec(spec)
    assert not is_sell_economics_v3_spec(spec)


def test_review_hold_zero_sell_through_plan() -> None:
    held = [_held(1, expected=0.02, rank=40, qty=200, price=100, weight=0.6)]
    result = apply_sell_gate(
        held=held,
        policy_targets=[
            PolicyTarget(
                instrument_id=2,
                ticker="T2",
                target_weight=1.0,
                rank=1,
                prediction_semantic="EXPECTED_RETURN",
                expected_return=0.024,
                action="ENTER_TOP20",
                price=100.0,
            )
        ],
        replacement_candidates=[_cand(2, expected=0.024, rank=1)],
        params=SellGateParams(
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=1,
            as_of=date(2026, 10, 1),
        ),
        fee_estimator=_fee(),
    )
    assert next(t for t in result.traces if t.instrument_id == 1).decision_action == REVIEW_HOLD
    plan = _plan_from_gate(result, held=held)
    assert not any(r.action == "SELL" for r in plan.executable)


def test_data_hold_zero_sell_through_plan() -> None:
    held = [_held(1, expected=0.01, rank=40, stale=True, qty=150, weight=0.55)]
    result = apply_sell_gate(
        held=held,
        policy_targets=[],
        replacement_candidates=[_cand(2, expected=0.50, rank=1)],
        params=SellGateParams(fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT, k_entry=1),
        fee_estimator=_fee(),
    )
    assert next(t for t in result.traces if t.instrument_id == 1).decision_action == DATA_HOLD
    plan = _plan_from_gate(result, held=held)
    assert not any(r.action == "SELL" for r in plan.executable)


def test_equal_weight_would_have_sold_review_hold_blocks() -> None:
    """High current weight A + REVIEW_HOLD must not emit SELL even if equal-weight would trim."""
    held = [
        _held(1, expected=0.015, rank=40, qty=800, price=100, weight=0.8),
        _held(10, expected=0.02, rank=3, in_band=True, qty=200, price=100, weight=0.2),
    ]
    policy = [
        PolicyTarget(
            instrument_id=10,
            ticker="T10",
            target_weight=0.5,
            rank=3,
            prediction_semantic="EXPECTED_RETURN",
            expected_return=0.02,
            action="HOLD_WITHIN_EXIT_BAND",
            price=100.0,
        ),
        PolicyTarget(
            instrument_id=2,
            ticker="T2",
            target_weight=0.5,
            rank=1,
            prediction_semantic="EXPECTED_RETURN",
            expected_return=0.018,
            action="ENTER_TOP20",
            price=100.0,
        ),
    ]
    result = apply_sell_gate(
        held=held,
        policy_targets=policy,
        replacement_candidates=[_cand(2, expected=0.018, rank=1)],
        params=SellGateParams(
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=2,
            as_of=date(2026, 10, 1),
        ),
        fee_estimator=_fee(),
    )
    assert next(t for t in result.traces if t.instrument_id == 1).decision_action == REVIEW_HOLD
    tw_a = next(t for t in result.targets if t.instrument_id == 1).target_weight
    assert abs(tw_a - 0.8) < 1e-12  # not equal-weight 0.5
    assert _perm_map(result)[1].sell_allowed is False
    plan = _plan_from_gate(result, held=held, nav=100_000.0)
    assert not any(r.action == "SELL" and r.instrument_id == 1 for r in plan.executable)
    assert not any(r.action == "SELL" for r in plan.executable)


def test_rotate_authorized_sell_and_buy_through_plan() -> None:
    held = [_held(1, expected=0.01, rank=40, qty=100, price=100, weight=1.0)]
    result = apply_sell_gate(
        held=held,
        policy_targets=[
            PolicyTarget(
                instrument_id=2,
                ticker="T2",
                target_weight=1.0,
                rank=1,
                prediction_semantic="EXPECTED_RETURN",
                expected_return=0.08,
                action="ENTER_TOP20",
                price=100.0,
            )
        ],
        replacement_candidates=[_cand(2, expected=0.08, rank=1)],
        params=SellGateParams(
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=1,
            as_of=date(2026, 10, 1),
        ),
        fee_estimator=_fee(),
    )
    assert _perm_map(result)[1].sell_allowed is True
    plan = _plan_from_gate(result, held=held, cash=0.0)
    sells = [r for r in plan.executable if r.action == "SELL"]
    buys = [r for r in plan.executable if r.action == "BUY"]
    assert len(sells) == 1 and sells[0].instrument_id == 1
    assert len(buys) == 1 and buys[0].instrument_id == 2


def test_risk_reduce_and_exit_still_sell() -> None:
    held = [
        _held(1, expected=0.02, rank=40, qty=100, weight=0.3),
        _held(2, expected=0.03, rank=5, in_band=True, qty=200, weight=0.6),
    ]
    policy = [
        PolicyTarget(
            instrument_id=2,
            ticker="T2",
            target_weight=0.5,
            rank=5,
            prediction_semantic="EXPECTED_RETURN",
            expected_return=0.03,
            action="HOLD_WITHIN_EXIT_BAND",
            price=100.0,
        )
    ]
    result = apply_sell_gate(
        held=held,
        policy_targets=policy,
        replacement_candidates=[],
        params=SellGateParams(k_entry=2, exposure_cap=0.5),
        fee_estimator=_fee(),
        risk_forced={1: RISK_EXIT, 2: RISK_REDUCE},
    )
    plan = _plan_from_gate(result, held=held)
    sell_ids = {r.instrument_id for r in plan.executable if r.action == "SELL"}
    assert 1 in sell_ids  # full exit
    assert 2 in sell_ids  # partial reduce


def test_outside_k_entry_cannot_rotate() -> None:
    held = [_held(1, expected=0.01, rank=40)]
    # Candidate rank 5 is outside k_entry=3 → no rotation.
    result = apply_sell_gate(
        held=held,
        policy_targets=[],
        replacement_candidates=[_cand(2, expected=0.99, rank=5)],
        params=SellGateParams(
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=3,
            as_of=date(2026, 10, 1),
        ),
        fee_estimator=_fee(),
    )
    tr = next(t for t in result.traces if t.instrument_id == 1)
    assert tr.decision_action == REVIEW_HOLD
    assert "NO_REPLACEMENT" in tr.limitation_codes
    assert _perm_map(result)[1].sell_allowed is False

    # Same candidate with rank inside k_entry → ROTATE.
    ok = apply_sell_gate(
        held=held,
        policy_targets=[
            PolicyTarget(
                instrument_id=2,
                ticker="T2",
                target_weight=1.0,
                rank=2,
                prediction_semantic="EXPECTED_RETURN",
                expected_return=0.99,
                action="ENTER_TOP20",
                price=100.0,
            )
        ],
        replacement_candidates=[_cand(2, expected=0.99, rank=2)],
        params=SellGateParams(
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=3,
            as_of=date(2026, 10, 1),
        ),
        fee_estimator=_fee(),
    )
    assert next(t for t in ok.traces if t.instrument_id == 1).decision_action == ROTATE


def test_multiple_reviewed_do_not_over_allocate_one_b() -> None:
    held = [
        _held(1, expected=0.01, rank=40, qty=100, weight=0.5),
        _held(2, expected=0.011, rank=41, qty=100, weight=0.5),
    ]
    # Only one strong replacement — second reviewed must not also claim it.
    result = apply_sell_gate(
        held=held,
        policy_targets=[
            PolicyTarget(
                instrument_id=99,
                ticker="T99",
                target_weight=1.0,
                rank=1,
                prediction_semantic="EXPECTED_RETURN",
                expected_return=0.20,
                action="ENTER_TOP20",
                price=100.0,
            )
        ],
        replacement_candidates=[_cand(99, expected=0.20, rank=1)],
        params=SellGateParams(
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=2,
            as_of=date(2026, 10, 1),
        ),
        fee_estimator=_fee(),
    )
    actions = {t.instrument_id: t.decision_action for t in result.traces if t.held_before}
    rotate_from = [a for a, act in actions.items() if act == ROTATE]
    assert len(rotate_from) == 1
    assert rotate_from[0] == 1  # lower id evaluated first among sorted reviewed
    assert actions[2] == REVIEW_HOLD
    assert sum(1 for t in result.targets if t.instrument_id == 99) == 1
    perms = _perm_map(result)
    assert perms[1].sell_allowed is True and perms[1].rotate_to == 99
    assert perms[2].sell_allowed is False


def test_every_v3_sell_has_permission() -> None:
    held = [
        _held(1, expected=0.01, rank=40, qty=100, weight=0.4),
        _held(2, expected=0.03, rank=5, in_band=True, qty=100, weight=0.4),
    ]
    result = apply_sell_gate(
        held=held,
        policy_targets=[
            PolicyTarget(
                instrument_id=2,
                ticker="T2",
                target_weight=0.5,
                rank=5,
                prediction_semantic="EXPECTED_RETURN",
                expected_return=0.03,
                action="HOLD_WITHIN_EXIT_BAND",
                price=100.0,
            ),
            PolicyTarget(
                instrument_id=3,
                ticker="T3",
                target_weight=0.5,
                rank=1,
                prediction_semantic="EXPECTED_RETURN",
                expected_return=0.10,
                action="ENTER_TOP20",
                price=100.0,
            ),
        ],
        replacement_candidates=[_cand(3, expected=0.10, rank=1)],
        params=SellGateParams(
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=2,
            exposure_cap=0.5,
            as_of=date(2026, 10, 1),
        ),
        fee_estimator=_fee(),
        risk_forced={2: RISK_REDUCE},
    )
    plan = _plan_from_gate(result, held=held)
    perm_by = _perm_map(result)
    for row in plan.executable:
        if row.action != "SELL":
            continue
        assert row.instrument_id in perm_by
        assert perm_by[row.instrument_id].sell_allowed is True
        assert perm_by[row.instrument_id].action not in {HOLD, REVIEW_HOLD, DATA_HOLD}


def test_lot_plan_defaults_preserve_v2_sell() -> None:
    """V1/V2 PlanInstrument defaults (sell_allowed=True) still emit SELL."""
    plan = build_lot_order_plan(
        [
            PlanInstrument(1, "AAA", Decimal("0"), Decimal("1000"), Decimal("10"), 100, rank=2),
            PlanInstrument(2, "BBB", Decimal("0.5"), Decimal("0"), Decimal("10"), 100, rank=1),
        ],
        cash=Decimal("0"),
        nav=Decimal("10000"),
        costs=TransactionCostProfile(broker_bps=Decimal("0"), slippage_bps=Decimal("0")),
    )
    assert any(r.action == "SELL" and r.instrument_id == 1 for r in plan.executable)

def _fee_for_engine(as_of: date):
    estimator = FeeEngineEstimator(
        FeeEngine(sber_investment_builtin_rules()),
        fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
        fee_profile_version=1,
    )

    def _fn(side: str, notional: Decimal, inst: PlanInstrument) -> Decimal | None:
        return estimator.broker_fee_estimate(
            side=side,
            notional=notional,
            instrument_id=int(inst.instrument_id),
            as_of=as_of,
            instrument_symbol=str(inst.ticker),
        )

    return _fn


def test_fee_consistency_100k_rub_plan_and_estimate() -> None:
    """Normal 100000 RUB → 300 RUB FeeEngine estimate used by lot plan."""
    as_of = date(2026, 10, 1)
    plan = build_lot_order_plan(
        [
            PlanInstrument(
                1,
                "SBER",
                Decimal("1.0"),
                Decimal("0"),
                Decimal("100"),
                10,
                rank=1,
            )
        ],
        cash=Decimal("100300"),
        nav=Decimal("100300"),
        costs=TransactionCostProfile(broker_bps=Decimal("0"), slippage_bps=Decimal("0")),
        fee_for=_fee_for_engine(as_of),
    )
    buys = [r for r in plan.executable if r.action == "BUY"]
    assert buys
    assert buys[0].estimated_notional == Decimal("100000")
    assert buys[0].estimated_fee == Decimal("300")


def test_sbfr_zero_fee_in_gate_and_plan_during_window() -> None:
    """SBFR temp zero applies in gate estimate and lot-plan fee_for during window."""
    as_of = date(2026, 10, 1)
    gate_fee = _fee().broker_fee_estimate(
        side="SELL",
        notional=Decimal("50000"),
        instrument_id=7,
        as_of=as_of,
        instrument_symbol="SBFR",
    )
    assert gate_fee == Decimal("0")
    plan = build_lot_order_plan(
        [
            PlanInstrument(
                7,
                "SBFR",
                Decimal("0"),
                Decimal("500"),
                Decimal("100"),
                10,
                rank=40,
                sell_allowed=True,
            )
        ],
        cash=Decimal("0"),
        nav=Decimal("50000"),
        costs=TransactionCostProfile(broker_bps=Decimal("30"), slippage_bps=Decimal("0")),
        fee_for=_fee_for_engine(as_of),
    )
    sells = [r for r in plan.executable if r.action == "SELL"]
    assert sells
    assert sells[0].estimated_fee == Decimal("0")
    assert sells[0].estimated_fee != Decimal("150")


def test_sbfr_after_window_falls_back_to_generic() -> None:
    as_of = date(2027, 1, 1)
    fee = _fee().broker_fee_estimate(
        side="BUY",
        notional=Decimal("100000"),
        instrument_id=7,
        as_of=as_of,
        instrument_symbol="SBFR",
    )
    assert fee == Decimal("300")


def test_v2_commission_bps_unchanged_by_fee_profile() -> None:
    v2a, _ = realism_v2_shadow_configs()
    assert v2a.commission_bps == 0.0
    assert v2a.fee_profile_code is None
    assert v2a.fee_profile_version is None
    est = resolve_broker_fee_estimator(fee_profile_code=None, commission_bps=10.0)
    fee = est.broker_fee_estimate(
        side="BUY",
        notional=Decimal("100000"),
        instrument_id=1,
        as_of=date(2026, 10, 1),
        instrument_symbol="SBER",
    )
    assert fee == Decimal("100")


def test_execution_date_selects_fee_rule_across_year_boundary() -> None:
    """Decision fee_date Dec 31 (SBFR zero) vs fill Jan 1 (generic 0.3%)."""
    decision_fee = _fee().broker_fee_estimate(
        side="SELL",
        notional=Decimal("100000"),
        instrument_id=7,
        as_of=date(2026, 12, 31),
        instrument_symbol="SBFR",
    )
    fill_fee = _fee().broker_fee_estimate(
        side="SELL",
        notional=Decimal("100000"),
        instrument_id=7,
        as_of=date(2027, 1, 1),
        instrument_symbol="SBFR",
    )
    assert decision_fee == Decimal("0")
    assert fill_fee == Decimal("300")


def test_lot_plan_skips_when_fee_rule_unavailable() -> None:
    """Pre-2026-09-29 generic UNKNOWN → plan must not invent 0% fee."""
    plan = build_lot_order_plan(
        [
            PlanInstrument(
                1,
                "SBER",
                Decimal("1.0"),
                Decimal("0"),
                Decimal("100"),
                10,
                rank=1,
            )
        ],
        cash=Decimal("100300"),
        nav=Decimal("100300"),
        costs=TransactionCostProfile(broker_bps=Decimal("0"), slippage_bps=Decimal("0")),
        fee_for=_fee_for_engine(date(2026, 9, 1)),
    )
    assert not plan.executable
    assert any(r.reason == "FEE_RULE_UNAVAILABLE" for r in plan.skipped)


def test_v3_unknown_profile_does_not_become_zero_bps() -> None:
    """Missing FeeProfile must be UNKNOWN — not BpsFeeEstimator(0)."""
    est = resolve_broker_fee_estimator(
        fee_profile_code="NON_EXISTENT_PROFILE",
        fee_profile_version=1,
        commission_bps=0.0,
        allow_legacy_bps_fallback=False,
    )
    assert isinstance(est, UnknownFeeEstimator)
    assert not isinstance(est, BpsFeeEstimator)
    quote = estimate_shadow_fee(
        est,
        side="BUY",
        notional=Decimal("100000"),
        instrument_id=1,
        as_of=date(2026, 9, 29),
        fee_profile_code="NON_EXISTENT_PROFILE",
        instrument_symbol="SBER",
    )
    assert quote.is_unknown
    assert quote.amount is None
    assert est.broker_fee_estimate(
        side="BUY",
        notional=Decimal("100000"),
        instrument_id=1,
        as_of=date(2026, 9, 29),
        fee_profile_code="NON_EXISTENT_PROFILE",
        instrument_symbol="SBER",
    ) is None


def test_v3_unknown_profile_blocks_rotate() -> None:
    """Cost-dependent ROTATE cannot assume 0% when profile is unresolved."""
    est = resolve_broker_fee_estimator(
        fee_profile_code="NON_EXISTENT_PROFILE",
        commission_bps=0.0,
        allow_legacy_bps_fallback=False,
    )
    held = [_held(1, expected=0.01, rank=40, qty=100, price=100, weight=0.5)]
    result = apply_sell_gate(
        held=held,
        policy_targets=[
            PolicyTarget(
                instrument_id=2,
                ticker="T2",
                target_weight=1.0,
                rank=1,
                prediction_semantic="EXPECTED_RETURN",
                expected_return=0.99,
                action="ENTER_TOP20",
                price=100.0,
            )
        ],
        replacement_candidates=[_cand(2, expected=0.99, rank=1)],
        params=SellGateParams(
            fee_profile_code="NON_EXISTENT_PROFILE",
            k_entry=1,
            as_of=date(2026, 10, 1),
            min_net_rotation_edge_bps=0.0,
            slippage_bps=0.0,
        ),
        fee_estimator=est,
        eligible_count=5,
    )
    tr = next(t for t in result.traces if t.instrument_id == 1)
    assert tr.decision_action == DATA_HOLD
    assert "FEE_MODEL_MISSING" in (tr.limitation_codes or ())
    assert _perm_map(result)[1].sell_allowed is False


def test_v2_legacy_bps_fallback_still_works() -> None:
    est = resolve_broker_fee_estimator(
        fee_profile_code=None,
        commission_bps=10.0,
        allow_legacy_bps_fallback=True,
    )
    assert isinstance(est, BpsFeeEstimator)
    fee = est.broker_fee_estimate(
        side="BUY",
        notional=Decimal("10000"),
        instrument_id=1,
        as_of=date(2026, 9, 29),
    )
    assert fee == Decimal("10")


def test_v3_sber_builtin_still_resolves_when_fallback_disabled() -> None:
    est = resolve_broker_fee_estimator(
        fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
        fee_profile_version=1,
        commission_bps=0.0,
        allow_legacy_bps_fallback=False,
    )
    assert isinstance(est, FeeEngineEstimator)
    assert est.fee_profile_version == 1
    assert est.broker_fee_estimate(
        side="BUY",
        notional=Decimal("100000"),
        instrument_id=1,
        as_of=date(2026, 9, 29),
        instrument_symbol="SBER",
    ) == Decimal("300")
    assert est.broker_fee_estimate(
        side="BUY",
        notional=Decimal("100000"),
        instrument_id=1,
        as_of=date(2026, 9, 29),
        instrument_symbol="SBFR",
    ) == Decimal("0")
    # Post-expiry SBFR uses generic 0.3%
    assert est.broker_fee_estimate(
        side="BUY",
        notional=Decimal("100000"),
        instrument_id=1,
        as_of=date(2027, 1, 2),
        instrument_symbol="SBFR",
    ) == Decimal("300")


def test_unsupported_sber_version_does_not_use_builtin_v1() -> None:
    """SBER_INVESTMENT/v999 must not impersonate builtin v1 rules."""
    est = resolve_broker_fee_estimator(
        fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
        fee_profile_version=999,
        commission_bps=0.0,
        allow_legacy_bps_fallback=False,
    )
    assert isinstance(est, UnknownFeeEstimator)
    assert est.fee_profile_version == 999
    quote = estimate_shadow_fee(
        est,
        side="BUY",
        notional=Decimal("100000"),
        instrument_id=1,
        as_of=date(2026, 9, 29),
        fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
        fee_profile_version=999,
        instrument_symbol="SBER",
    )
    assert quote.is_unknown
    assert quote.amount is None
    assert quote.fee_profile_version == 999
    # Must not fabricate builtin 0.3% (300 RUB)
    assert quote.amount != Decimal("300")


def test_unsupported_sber_version_blocks_rotate() -> None:
    est = resolve_broker_fee_estimator(
        fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
        fee_profile_version=999,
        commission_bps=0.0,
        allow_legacy_bps_fallback=False,
    )
    held = [_held(1, expected=0.01, rank=40, qty=100, price=100, weight=0.5)]
    result = apply_sell_gate(
        held=held,
        policy_targets=[
            PolicyTarget(
                instrument_id=2,
                ticker="T2",
                target_weight=1.0,
                rank=1,
                prediction_semantic="EXPECTED_RETURN",
                expected_return=0.99,
                action="ENTER_TOP20",
                price=100.0,
            )
        ],
        replacement_candidates=[_cand(2, expected=0.99, rank=1)],
        params=SellGateParams(
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=1,
            as_of=date(2026, 10, 1),
            min_net_rotation_edge_bps=0.0,
            slippage_bps=0.0,
        ),
        fee_estimator=est,
        eligible_count=5,
    )
    tr = next(t for t in result.traces if t.instrument_id == 1)
    assert tr.decision_action == DATA_HOLD
    assert "FEE_MODEL_MISSING" in (tr.limitation_codes or ())
    assert _perm_map(result)[1].sell_allowed is False
    assert not any(t.decision_action == ROTATE for t in result.traces)


def test_db_sber_version_2_uses_db_rules_not_builtin_v1() -> None:
    """Exact SBER_INVESTMENT/v2 from DB must not fall back to builtin v1 0.3%."""
    from sqlalchemy import delete, select

    from app.infrastructure.db.session import core_session
    from app.modules.portfolio.domain.fee_engine import FeeType
    from app.modules.portfolio.infrastructure.models import FeeProfile, FeeRule
    from app.modules.shadow.domain.fee_estimate import load_fee_engine_for_profile

    profile_id: int | None = None
    try:
        with core_session() as session:
            existing = session.scalar(
                select(FeeProfile).where(
                    FeeProfile.code == FEE_PROFILE_CODE_SBER_INVESTMENT,
                    FeeProfile.version == 2,
                )
            )
            if existing is not None:
                session.execute(delete(FeeRule).where(FeeRule.fee_profile_id == existing.id))
                session.execute(delete(FeeProfile).where(FeeProfile.id == existing.id))
                session.flush()

            profile = FeeProfile(
                code=FEE_PROFILE_CODE_SBER_INVESTMENT,
                name="Sber Investment pytest v2",
                broker_code="SBER",
                broker_name="Sber",
                tariff_name="pytest-v2",
                version=2,
                valid_from=date(2026, 9, 29),
                source_note="pytest-only SBER_INVESTMENT v2; distinct 1% rate",
                is_builtin=False,
                read_only=False,
            )
            session.add(profile)
            session.flush()
            profile_id = int(profile.id)
            session.add(
                FeeRule(
                    fee_profile_id=profile_id,
                    code="SBER_MOEX_ONLINE_V2_PYTEST",
                    market="MOEX",
                    execution_channel="ONLINE",
                    side=None,
                    fee_type=FeeType.PERCENTAGE,
                    percentage_rate=Decimal("0.01"),  # 1% — distinct from builtin 0.3%
                    exclude_from_turnover=False,
                    priority=100,
                    valid_from=date(2026, 9, 29),
                    explanation="pytest v2 1% of notional",
                    active=True,
                )
            )
            session.flush()

            engine, code, version = load_fee_engine_for_profile(
                session,
                fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
                fee_profile_version=2,
            )
            assert engine is not None
            assert code == FEE_PROFILE_CODE_SBER_INVESTMENT
            assert version == 2
            est = FeeEngineEstimator(engine, fee_profile_code=code, fee_profile_version=version)
            fee = est.broker_fee_estimate(
                side="BUY",
                notional=Decimal("100000"),
                instrument_id=1,
                as_of=date(2026, 9, 29),
                instrument_symbol="SBER",
            )
            # DB v2 = 1% → 1000; builtin v1 would be 300
            assert fee == Decimal("1000")
            assert fee != Decimal("300")
    finally:
        if profile_id is not None:
            with core_session() as session:
                session.execute(delete(FeeRule).where(FeeRule.fee_profile_id == profile_id))
                session.execute(delete(FeeProfile).where(FeeProfile.id == profile_id))
                session.flush()
