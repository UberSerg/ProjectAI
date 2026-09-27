"""PIT / no look-ahead contracts for market→shadow recovery."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.modules.shadow.application.recovery import run_market_shadow_recovery
from app.modules.shadow.application.session_catchup import run_portfolio_session_catchup


def test_recovery_generates_forward_per_session_as_of() -> None:
    session = MagicMock()
    gap = SimpleNamespace(
        status="MARKET_STALE",
        local_complete_eod=date(2026, 9, 10),
        expected_completed_session=date(2026, 9, 15),
        to_dict=lambda: {"status": "MARKET_STALE"},
    )
    gap_after = SimpleNamespace(
        status="MARKET_CURRENT",
        to_dict=lambda: {"status": "MARKET_CURRENT"},
    )
    forward_calls: list[date] = []

    def fake_forward(session, *, as_of=None, generated_at=None, **_kwargs):
        forward_calls.append(as_of)
        assert generated_at is not None
        assert generated_at.date() == as_of
        return SimpleNamespace(status="SUCCESS", batch_id=1, summary={})

    with (
        patch(
            "app.modules.shadow.application.recovery.detect_market_eod_gap",
            side_effect=[gap, gap, gap_after],
        ),
        patch(
            "app.modules.shadow.application.recovery.run_eod_market_recovery",
            return_value={"status": "SUCCESS", "downloaded_sessions": ["2026-09-11"]},
        ),
        patch(
            "app.modules.shadow.application.recovery.select_latest_complete_as_of",
            return_value=SimpleNamespace(complete=True, as_of=date(2026, 9, 15)),
        ),
        patch(
            "app.modules.shadow.application.recovery._ensure_features",
            return_value={"analytics": {}, "technical": {}},
        ),
        patch(
            "app.modules.shadow.application.recovery.candle_dates_in_range",
            return_value=[date(2026, 9, 11), date(2026, 9, 12), date(2026, 9, 15)],
        ),
        patch(
            "app.modules.shadow.application.recovery.run_forward_signal_v0",
            side_effect=fake_forward,
        ),
        patch(
            "app.modules.shadow.application.recovery.run_all_shadow_catchup",
            return_value={"status": "CATCH_UP_SUCCESS"},
        ),
        patch(
            "app.modules.shadow.application.recovery.build_catchup_status",
            return_value={},
        ),
        patch(
            "app.modules.shadow.application.recovery.trading_sessions_between",
            return_value=[date(2026, 9, 11), date(2026, 9, 12), date(2026, 9, 15)],
        ),
    ):
        out = run_market_shadow_recovery(session, commit_each_session=False)

    assert out["pit"]["intermediate_forward_as_of"] is True
    assert forward_calls == [date(2026, 9, 11), date(2026, 9, 12), date(2026, 9, 15)]


def test_catchup_applies_decisions_with_max_as_of_per_day() -> None:
    """Replay day D must not see Forward as_of > D."""
    session = MagicMock()
    portfolio = SimpleNamespace(
        id=1,
        spec_id=2,
        last_processed_market_date=date(2026, 9, 10),
    )
    spec = SimpleNamespace(name="P", id=2)
    applied: list[tuple[date, date]] = []

    def fake_apply(_session, _p, _s, *, now, max_as_of=None):
        applied.append((now.date(), max_as_of))
        return 1

    session.get.side_effect = lambda model, pk: portfolio if pk == 1 else spec

    with (
        patch(
            "app.modules.shadow.application.session_catchup.evaluate_eod_readiness",
            return_value=SimpleNamespace(latest_complete_eod_date=date(2026, 9, 12)),
        ),
        patch(
            "app.modules.shadow.application.session_catchup.build_portfolio_catchup_plan",
            side_effect=[
                SimpleNamespace(
                    status="CATCH_UP_PARTIAL",
                    reason=None,
                    missing_sessions=[date(2026, 9, 11), date(2026, 9, 12)],
                    last_processed_session=date(2026, 9, 10),
                    latest_completed_market_session=date(2026, 9, 12),
                    backlog_count=2,
                ),
                SimpleNamespace(
                    status="CATCH_UP_PARTIAL",
                    reason=None,
                    missing_sessions=[date(2026, 9, 11), date(2026, 9, 12)],
                    last_processed_session=date(2026, 9, 10),
                    latest_completed_market_session=date(2026, 9, 12),
                    backlog_count=2,
                ),
            ],
        ),
        patch(
            "app.modules.shadow.application.session_catchup.session_has_eod_candles",
            return_value=True,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.apply_pending_forward_decisions",
            side_effect=fake_apply,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.process_shadow_market_day",
            side_effect=lambda *_a, **k: {
                "day": k.get("day", _a[3]).isoformat() if len(_a) > 3 else "x",
                "fills": 0,
                "skipped": None,
            },
        ),
        patch(
            "app.modules.shadow.application.session_catchup.refresh_shadow_portfolio_status"
        ),
        patch(
            "app.modules.shadow.application.session_catchup.missing_sessions_for_watermark",
            return_value=[],
        ),
    ):
        # Fix process_shadow_market_day mock properly
        pass

    with (
        patch(
            "app.modules.shadow.application.session_catchup.evaluate_eod_readiness",
            return_value=SimpleNamespace(latest_complete_eod_date=date(2026, 9, 12)),
        ),
        patch(
            "app.modules.shadow.application.session_catchup.build_portfolio_catchup_plan",
            return_value=SimpleNamespace(
                status="CATCH_UP_PARTIAL",
                reason=None,
                missing_sessions=[date(2026, 9, 11), date(2026, 9, 12)],
                last_processed_session=date(2026, 9, 10),
                latest_completed_market_session=date(2026, 9, 12),
                backlog_count=2,
                to_dict=lambda: {},
            ),
        ),
        patch(
            "app.modules.shadow.application.session_catchup.session_has_eod_candles",
            return_value=True,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.apply_pending_forward_decisions",
            side_effect=fake_apply,
        ),
        patch(
            "app.modules.shadow.application.session_catchup.process_shadow_market_day",
            side_effect=lambda _s, _p, _sp, day, now: {
                "day": day.isoformat(),
                "fills": 0,
                "skipped": None,
            },
        ),
        patch("app.modules.shadow.application.session_catchup.refresh_shadow_portfolio_status"),
        patch(
            "app.modules.shadow.application.session_catchup.missing_sessions_for_watermark",
            return_value=[],
        ),
    ):
        portfolio.last_processed_market_date = date(2026, 9, 10)

        def _process(_s, _p, _sp, day, now):
            portfolio.last_processed_market_date = day
            return {"day": day.isoformat(), "fills": 0, "skipped": None}

        with patch(
            "app.modules.shadow.application.session_catchup.process_shadow_market_day",
            side_effect=_process,
        ):
            out = run_portfolio_session_catchup(
                session, 1, ensure_market=False, commit_each_session=False
            )

    assert applied == [
        (date(2026, 9, 11), date(2026, 9, 11)),
        (date(2026, 9, 12), date(2026, 9, 12)),
    ]
    assert out["status"] == "CATCH_UP_SUCCESS"
