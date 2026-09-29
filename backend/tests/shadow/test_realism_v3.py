"""Shadow Realism V3 — sell economics gate, FeeEngine fees, V2 untouched."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

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
    FeeEngineEstimator,
    resolve_broker_fee_estimator,
)
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
    semantic: str = "EXPECTED_RETURN",
    stale: bool = False,
    in_band: bool = False,
) -> HeldName:
    return HeldName(
        instrument_id=iid,
        ticker=f"T{iid}",
        quantity=qty,
        current_weight=0.2,
        rank=rank,
        prediction_semantic=semantic,
        expected_return=expected if semantic == "EXPECTED_RETURN" else None,
        signal_as_of=date(2026, 9, 1),
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
        signal_as_of=date(2026, 9, 1),
        signal_stale=stale,
    )


def _fee() -> FeeEngineEstimator:
    return FeeEngineEstimator(FeeEngine(sber_investment_builtin_rules()))


def test_v3_configs_distinct_from_v2() -> None:
    a, b = realism_v3_shadow_configs()
    assert a.experiment_group == EXPERIMENT_GROUP_V3 == b.experiment_group
    assert a.execution_version == EXECUTION_VERSION_SELL_ECONOMICS_V3
    assert a.fee_profile_code == FEE_PROFILE_CODE_SBER_INVESTMENT
    assert a.min_net_rotation_edge_bps == 0.0
    assert a.fractional_shares is False
    assert b.risk_name != a.risk_name
    v2a, _ = realism_v2_shadow_configs()
    assert v2a.experiment_group == EXPERIMENT_GROUP_V2
    assert v2a.execution_version == EXECUTION_VERSION_LOT_AWARE_V2
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
        as_of=date(2026, 9, 10),
        instrument_symbol="SBER",
    )
    assert fee is not None
    assert abs(fee - Decimal("300")) < Decimal("0.01")
    raw = FeeEngine(sber_investment_builtin_rules()).estimate_fee(
        FeeEstimateContext(
            as_of=date(2026, 9, 10),
            side="BUY",
            notional=Decimal("100000"),
            instrument_symbol="GAZP",
        )
    )
    assert raw.status == FeeStatus.KNOWN
    assert raw.amount is not None
    assert abs(raw.amount - Decimal("300")) < Decimal("0.01")


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
            as_of=date(2026, 9, 10),
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
            as_of=date(2026, 9, 10),
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
            as_of=date(2026, 9, 10),
        ),
    )
    blocked = apply_sell_gate(
        **common,
        params=SellGateParams(
            slippage_bps=10.0,
            fee_profile_code=FEE_PROFILE_CODE_SBER_INVESTMENT,
            k_entry=1,
            as_of=date(2026, 9, 10),
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


def test_risk_can_force_exit_and_reduce() -> None:
    held = [
        _held(1, expected=0.02, rank=40),
        _held(2, expected=0.03, rank=5, in_band=True),
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
    assert tw == 0.5


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


def test_retained_position_stays_in_targets_no_phantom_funding() -> None:
    held = [
        _held(10, expected=0.02, rank=3, in_band=True),
        _held(1, expected=0.015, rank=40),
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
            as_of=date(2026, 9, 10),
        ),
        fee_estimator=_fee(),
    )
    ids = {t.instrument_id for t in result.targets}
    assert 1 in ids and 10 in ids
    assert 2 not in ids
    assert next(t for t in result.traces if t.instrument_id == 1).decision_action == REVIEW_HOLD


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
            as_of=date(2026, 9, 10),
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


def test_v2_spec_helper_untouched() -> None:
    spec = SimpleNamespace(
        fractional_shares=False,
        payload={"execution_version": EXECUTION_VERSION_LOT_AWARE_V2},
        execution_version=EXECUTION_VERSION_LOT_AWARE_V2,
    )
    assert is_lot_aware_spec(spec)
    assert not is_sell_economics_v3_spec(spec)
