"""Shadow Realism V2 config, consistency, daily ops, order-build wiring."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.modules.shadow.application.consistency import check_shadow_consistency
from app.modules.shadow.application.daily_operations import (
    READY_FOR_NEXT_SESSION,
    WAITING_FOR_MARKET_COMPLETE,
    evaluate_eod_readiness,
)
from app.modules.shadow.application.lot_aware import is_lot_aware_spec
from app.modules.shadow.config import (
    EXPERIMENT_GROUP,
    EXPERIMENT_GROUP_V2,
    EXECUTION_VERSION_LOT_AWARE_V2,
    portfolio_a_config,
    realism_v2_shadow_configs,
)


def test_v2_configs_lot_aware_fresh_capital() -> None:
    a, b = realism_v2_shadow_configs()
    assert a.experiment_group == EXPERIMENT_GROUP_V2 == b.experiment_group
    assert a.fractional_shares is False
    assert b.fractional_shares is False
    assert a.execution_version == EXECUTION_VERSION_LOT_AWARE_V2
    assert a.initial_capital == 1_000_000.0
    assert a.version == "v2"
    v1 = portfolio_a_config()
    assert v1.experiment_group == EXPERIMENT_GROUP
    assert v1.fractional_shares is True
    assert a.config_hash() != v1.config_hash()
    assert a.candidate_config_hash == v1.candidate_config_hash
    assert a.policy_name == v1.policy_name


def test_is_lot_aware_spec_helpers() -> None:
    assert is_lot_aware_spec(SimpleNamespace(fractional_shares=False, payload={}))
    assert is_lot_aware_spec(
        SimpleNamespace(
            fractional_shares=True,
            payload={"execution_version": EXECUTION_VERSION_LOT_AWARE_V2},
        )
    )
    assert not is_lot_aware_spec(SimpleNamespace(fractional_shares=True, payload={}))


def test_consistency_negative_cash_and_fractional_v2() -> None:
    session = MagicMock()
    portfolio = SimpleNamespace(
        id=1,
        cash=-10.0,
        positions={
            "7": {
                "instrument_id": 7,
                "ticker": "X",
                "quantity": 15.5,
                "lot_size": 10,
                "lots": 1,
            }
        },
    )
    spec = SimpleNamespace(
        fractional_shares=False, payload={"execution_version": EXECUTION_VERSION_LOT_AWARE_V2}
    )
    session.execute.return_value.all.return_value = [(portfolio, spec)]

    def _scalars(stmt):  # noqa: ANN001
        return MagicMock(all=lambda: [], __iter__=lambda self: iter([]))

    session.scalars.side_effect = _scalars
    session.scalar.return_value = 0

    issues = check_shadow_consistency(session, portfolio_ids=[1])
    codes = {i.code for i in issues}
    assert "NEGATIVE_CASH" in codes
    assert "FRACTIONAL_UNITS" in codes or "UNITS_NOT_DIVISIBLE_BY_LOT" in codes


def test_consistency_units_not_divisible() -> None:
    session = MagicMock()
    portfolio = SimpleNamespace(
        id=2,
        cash=100.0,
        positions={
            "8": {
                "instrument_id": 8,
                "ticker": "Y",
                "quantity": 15,
                "lot_size": 10,
                "lots": 1,
            }
        },
    )
    spec = SimpleNamespace(fractional_shares=False, payload={})
    session.execute.return_value.all.return_value = [(portfolio, spec)]

    def _scalars(stmt):  # noqa: ANN001
        return MagicMock(all=lambda: [], __iter__=lambda self: iter([]))

    session.scalars.side_effect = _scalars
    session.scalar.return_value = 0
    issues = check_shadow_consistency(session, portfolio_ids=[2])
    assert any(i.code == "UNITS_NOT_DIVISIBLE_BY_LOT" for i in issues)


def test_eod_readiness_waiting_when_incomplete() -> None:
    session = MagicMock()
    with patch(
        "app.modules.shadow.application.daily_operations.select_latest_complete_as_of"
    ) as sel, patch(
        "app.modules.shadow.application.daily_operations._collect_watermarks"
    ) as wm:
        sel.return_value = SimpleNamespace(
            complete=False,
            as_of=None,
            reason="ratio_below_threshold",
            to_dict=lambda: {"complete": False},
        )
        wm.return_value = {"raw_market_latest_date": date(2026, 9, 5)}
        readiness = evaluate_eod_readiness(session)
    assert readiness.ready is False
    assert readiness.blocker_code == WAITING_FOR_MARKET_COMPLETE


def test_eod_readiness_ready_when_complete() -> None:
    session = MagicMock()
    d = date(2026, 9, 5)
    with patch(
        "app.modules.shadow.application.daily_operations.select_latest_complete_as_of"
    ) as sel, patch(
        "app.modules.shadow.application.daily_operations._collect_watermarks"
    ) as wm:
        sel.return_value = SimpleNamespace(
            complete=True,
            as_of=d,
            reason="ok",
            to_dict=lambda: {"complete": True, "as_of": d.isoformat()},
        )
        wm.return_value = {
            "raw_market_latest_date": d,
            "analytics_v2_latest_date": d,
            "technical_v2_latest_date": d,
        }
        readiness = evaluate_eod_readiness(session)
    assert readiness.ready is True
    assert readiness.blocker_code is None


def test_lot_aware_order_build_persists_integer_qty() -> None:
    from app.modules.shadow.application import service as shadow_service

    session = MagicMock()
    portfolio = SimpleNamespace(
        id=10,
        cash=1_000_000.0,
        risk_mode="normal",
        positions={},
        exposure_cap=1.0,
    )
    spec = SimpleNamespace(
        fractional_shares=False,
        commission_bps=0.0,
        slippage_bps=0.0,
        policy_name="RANK_HYSTERESIS_LONG_ONLY_V1",
        payload={"execution_version": EXECUTION_VERSION_LOT_AWARE_V2, "strategic_cash_reserve": 0},
        min_trade_weight_delta=0.0,
    )
    decision = SimpleNamespace(id=99, metadata_={})
    batch = SimpleNamespace(
        id=5,
        as_of_date=date(2026, 9, 4),
        generated_at=datetime(2026, 9, 4, 18, 0, tzinfo=UTC),
    )
    target_by_id = {
        1: {
            "instrument_id": 1,
            "ticker": "SBER",
            "target_weight": 0.2,
            "action": "ENTER_TOP20",
            "rank": 1,
            "predicted_return_20d": 0.05,
        }
    }
    instrument = SimpleNamespace(id=1, symbol="SBER")
    session.scalars.return_value = [instrument]

    with patch(
        "app.modules.shadow.application.service.resolve_equity_lot_sizes",
        return_value={1: SimpleNamespace(lot_size=10)},
    ), patch(
        "app.modules.shadow.application.service._candle_open_close",
        return_value=(250.0, 250.0),
    ), patch(
        "app.modules.shadow.application.service._position_qty",
        return_value=0.0,
    ), patch(
        "app.modules.shadow.application.service._positions_dict",
        return_value={},
    ):
        shadow_service._persist_lot_aware_orders(
            session,
            portfolio=portfolio,
            spec=spec,
            decision=decision,
            batch=batch,
            target_by_id=target_by_id,
            all_ids={1},
            nav=1_000_000.0,
            min_delta=0.0,
            min_exec=date(2026, 9, 5),
            eligible_count=40,
            decision_at=datetime(2026, 9, 4, 18, 0, tzinfo=UTC),
        )

    assert decision.metadata_.get("execution_version") == EXECUTION_VERSION_LOT_AWARE_V2
    assert "order_plan" in decision.metadata_
    assert session.add.called
    order = session.add.call_args[0][0]
    assert order.quantity == float(int(order.quantity))
    assert int(order.quantity) % 10 == 0
    assert order.metadata_["lot_size"] == 10
    assert order.metadata_["execution_version"] == EXECUTION_VERSION_LOT_AWARE_V2


def test_v1_fractional_path_unchanged_semantics() -> None:
    from app.modules.shadow.application import service as shadow_service

    session = MagicMock()
    portfolio = SimpleNamespace(id=1, cash=1_000_000.0, risk_mode="normal", positions={})
    spec = SimpleNamespace(
        fractional_shares=True,
        policy_name="RANK_HYSTERESIS_LONG_ONLY_V1",
    )
    decision = SimpleNamespace(id=1, metadata_={})
    batch = SimpleNamespace(
        id=1,
        as_of_date=date(2026, 9, 4),
        generated_at=datetime(2026, 9, 4, 18, 0, tzinfo=UTC),
    )
    target_by_id = {
        1: {
            "instrument_id": 1,
            "ticker": "SBER",
            "target_weight": 0.1,
            "action": "ENTER_TOP20",
            "rank": 1,
            "predicted_return_20d": 0.01,
        }
    }
    with patch(
        "app.modules.shadow.application.service._candle_open_close",
        return_value=(333.0, 333.0),
    ), patch(
        "app.modules.shadow.application.service._position_qty",
        return_value=0.0,
    ), patch(
        "app.modules.shadow.application.service._positions_dict",
        return_value={},
    ):
        shadow_service._persist_fractional_orders(
            session,
            portfolio=portfolio,
            spec=spec,
            decision=decision,
            batch=batch,
            target_by_id=target_by_id,
            all_ids={1},
            nav=1_000_000.0,
            min_delta=0.0,
            min_exec=date(2026, 9, 5),
            eligible_count=40,
            decision_at=datetime(2026, 9, 4, 18, 0, tzinfo=UTC),
        )
    order = session.add.call_args[0][0]
    assert abs(order.quantity - (100_000.0 / 333.0)) < 1e-6
    assert "execution_version" not in (order.metadata_ or {})


def test_ready_status_constant_exported() -> None:
    assert READY_FOR_NEXT_SESSION == "READY_FOR_NEXT_SESSION"
