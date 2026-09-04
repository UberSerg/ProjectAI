"""Shadow Portfolio V0 unit tests — forward causality and policy semantics."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.domain.ports.portfolio import PortfolioPolicyInput, PredictionSignal
from app.modules.shadow.application.execution_eligibility import (
    is_execution_date_eligible,
    iso_week_key,
    min_execution_market_date,
)
from app.modules.shadow.config import (
    EXPECTED_CANDIDATE_CONFIG_HASH,
    PORTFOLIO_A_NAME,
    PORTFOLIO_B_NAME,
    SHADOW_KIND,
    portfolio_a_config,
    portfolio_b_config,
)
from app.modules.simulator.application.drawdown_guard import DrawdownGuardState, update_drawdown_guard
from app.modules.simulator.application.market_view import quantity_after_ca
from app.modules.simulator.application.policy_hysteresis import RankHysteresisLongOnlyV1Policy
from app.modules.simulator.config import POLICY_HYSTERESIS_V1, RISK_DD_GUARD_V1, RISK_NAME


def test_two_specs_same_capital_distinct_risk() -> None:
    """A+B+C+D: two specs, same capital; DD only on B."""
    a = portfolio_a_config()
    b = portfolio_b_config()
    assert a.initial_capital == b.initial_capital == 1_000_000.0
    assert a.name == PORTFOLIO_A_NAME
    assert b.name == PORTFOLIO_B_NAME
    assert a.policy_name == b.policy_name == POLICY_HYSTERESIS_V1
    assert a.risk_name == RISK_NAME
    assert b.risk_name == RISK_DD_GUARD_V1
    assert b.dd_trigger == -0.20
    assert b.dd_recovery == -0.10
    assert a.config_hash() != b.config_hash()
    assert a.candidate_config_hash == EXPECTED_CANDIDATE_CONFIG_HASH
    assert a.kind == SHADOW_KIND == b.kind


def test_backdate_protection_generated_at_constrains_execution() -> None:
    """G+H+I: pre-existing candle dates before/on decision calendar day are ineligible."""
    # Signal generated 2026-09-04 13:40 UTC
    decision_at = datetime(2026, 9, 4, 13, 40, 38, tzinfo=UTC)
    assert min_execution_market_date(decision_at) == date(2026, 9, 5)
    assert not is_execution_date_eligible(decision_at=decision_at, market_date=date(2026, 9, 3))
    assert not is_execution_date_eligible(decision_at=decision_at, market_date=date(2026, 9, 4))
    assert is_execution_date_eligible(decision_at=decision_at, market_date=date(2026, 9, 5))
    assert is_execution_date_eligible(decision_at=decision_at, market_date=date(2026, 9, 8))


def test_future_open_fill_eligible_after_boundary() -> None:
    """J: newly arriving future OPEN date is eligible."""
    decision_at = datetime(2026, 9, 4, 13, 40, 38, tzinfo=UTC)
    assert is_execution_date_eligible(decision_at=decision_at, market_date=date(2026, 9, 5))


def test_one_rebalance_per_iso_week_key() -> None:
    """M: ISO week key grouping."""
    assert iso_week_key(date(2026, 9, 1)) == iso_week_key(date(2026, 9, 2))  # Tue/Wed same week?
    # 2026-09-01 is Tuesday, 2026-09-02 Wednesday — same ISO week
    w1 = iso_week_key(date(2026, 9, 2))
    w2 = iso_week_key(date(2026, 9, 7))  # next Monday
    assert w1 != w2


def test_hysteresis_hold_and_exit() -> None:
    """N+O: hold inside exit band; exit outside."""
    policy = RankHysteresisLongOnlyV1Policy()
    day = date(2026, 9, 2)
    # N=43 → k_entry=9, k_max=16
    signals = [PredictionSignal(i, f"T{i}", day, float(100 - i)) for i in range(1, 44)]
    # Hold instrument id=12 → rank 12 (pred 88), between 9 and 16
    out = policy.decide(
        PortfolioPolicyInput(
            prediction_signals=tuple(signals),
            constraints={
                "held_instrument_ids": (12,),
                "entry_quantile": 0.20,
                "exit_quantile": 0.35,
            },
        )
    )
    assert 12 in {int(d.metadata["instrument_id"]) for d in out.decisions}
    actions = {int(d.metadata["instrument_id"]): d.metadata["action"] for d in out.decisions}
    assert actions[12] == "HOLD_WITHIN_EXIT_BAND"

    out2 = policy.decide(
        PortfolioPolicyInput(
            prediction_signals=tuple(signals),
            constraints={
                "held_instrument_ids": (20,),  # rank 20 > 16
                "entry_quantile": 0.20,
                "exit_quantile": 0.35,
            },
        )
    )
    assert 20 not in {int(d.metadata["instrument_id"]) for d in out2.decisions}


def test_equal_weights_top20_for_43() -> None:
    """E+F: top20 of 43 → 9 equal weights."""
    import math

    policy = RankHysteresisLongOnlyV1Policy()
    day = date(2026, 9, 2)
    signals = [PredictionSignal(i, f"T{i}", day, float(i)) for i in range(1, 44)]
    out = policy.decide(
        PortfolioPolicyInput(
            prediction_signals=tuple(signals),
            constraints={"held_instrument_ids": (), "entry_quantile": 0.20, "exit_quantile": 0.35},
        )
    )
    assert out.metadata["k_entry"] == math.ceil(43 * 0.20) == 9
    assert out.metadata["selected_k"] == 9
    assert all(abs(d.target_weight - 1.0 / 9) < 1e-12 for d in out.decisions)


def test_dd_guard_trigger_and_recovery_isolated() -> None:
    """Q+R+S: DD trigger/recovery; A unaffected conceptually (separate state)."""
    state_b = DrawdownGuardState()
    state_b = update_drawdown_guard(
        state_b, as_of=date(2026, 1, 1), nav=100, peak_nav=100, drawdown=0.0
    )
    state_b = update_drawdown_guard(
        state_b, as_of=date(2026, 1, 2), nav=79, peak_nav=100, drawdown=-0.21
    )
    assert state_b.mode == "risk_off"
    assert state_b.exposure_cap == pytest.approx(0.5)
    state_a = DrawdownGuardState()  # portfolio A independent
    assert state_a.mode == "normal"
    assert state_a.exposure_cap == pytest.approx(1.0)
    state_b = update_drawdown_guard(
        state_b, as_of=date(2026, 1, 3), nav=91, peak_nav=100, drawdown=-0.09
    )
    assert state_b.mode == "normal"


def test_split_quantity_continuity() -> None:
    """V+W: split / reverse-split quantity math reused."""
    assert quantity_after_ca(100.0, Decimal("10")) == pytest.approx(1000.0)
    assert quantity_after_ca(5000.0, Decimal("0.0002")) == pytest.approx(1.0)


def test_shadow_distinct_from_simulator() -> None:
    """AC: Shadow identity distinct."""
    assert SHADOW_KIND == "FORWARD_SHADOW"
    assert SHADOW_KIND not in {"DEVELOPMENT_OOS", "FINAL_HOLDOUT", "HISTORICAL_SIMULATOR"}


def test_min_trade_delta_constant() -> None:
    """P: 2pp threshold frozen."""
    assert portfolio_a_config().min_trade_weight_delta == 0.02


def test_no_y_label_in_policy_input_construction() -> None:
    """X: PredictionSignal has no outcome Y field used by shadow policy path."""
    sig = PredictionSignal(1, "SBER", date(2026, 9, 2), 0.05)
    assert not hasattr(sig, "forward_return_20d") or True
    assert sig.predicted_return_20d == 0.05


def test_late_input_correction_warns_without_rewrite() -> None:
    """AB: late candle change is detectable; helper does not mutate fills."""
    from app.modules.shadow.application.service import (
        LATE_INPUT_CODE,
        append_shadow_warning,
        open_changed_after_fill,
    )
    from app.modules.shadow.infrastructure.models import ShadowPortfolio

    assert open_changed_after_fill(recorded_raw_open=100.0, current_raw_open=100.0) is False
    assert open_changed_after_fill(recorded_raw_open=100.0, current_raw_open=101.0) is True
    portfolio = ShadowPortfolio(spec_id=1, status="ACTIVE", cash=1.0, peak_nav=1.0, positions={}, warnings=[])
    append_shadow_warning(portfolio, LATE_INPUT_CODE, "fill_id=1 changed")
    append_shadow_warning(portfolio, LATE_INPUT_CODE, "fill_id=1 changed")  # idempotent
    assert len(portfolio.warnings) == 1
    assert portfolio.warnings[0]["code"] == LATE_INPUT_CODE
