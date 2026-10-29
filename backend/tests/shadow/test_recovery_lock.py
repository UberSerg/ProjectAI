"""Recovery single-flight lock: owner token, atomic release, renew / lose-lock."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.modules.shadow.application.recovery import (
    RecoveryLockLease,
    release_recovery_lock,
    renew_recovery_lock,
    run_market_shadow_recovery,
    try_acquire_recovery_lock,
)


def test_try_acquire_sets_nx_ex() -> None:
    client = MagicMock()
    client.set.return_value = True
    with patch(
        "app.modules.shadow.application.recovery._redis",
        return_value=client,
    ), patch(
        "app.modules.shadow.application.recovery.get_settings",
        return_value=SimpleNamespace(redis_url="redis://localhost/0"),
    ):
        assert try_acquire_recovery_lock("owner-a", ttl=600) is True
    client.set.assert_called_once()
    args, kwargs = client.set.call_args
    assert kwargs.get("nx") is True
    assert kwargs.get("ex") == 600
    assert args[1] == "owner-a"


def test_release_only_owner_via_lua() -> None:
    client = MagicMock()
    client.eval.return_value = 1
    with patch(
        "app.modules.shadow.application.recovery._redis",
        return_value=client,
    ):
        assert release_recovery_lock("owner-a") is True
    client.eval.assert_called_once()
    # ARGV[1] is the owner token
    assert client.eval.call_args.args[3] == "owner-a"


def test_stale_owner_cannot_release_new_owner() -> None:
    client = MagicMock()
    client.eval.return_value = 0  # compare failed
    with patch(
        "app.modules.shadow.application.recovery._redis",
        return_value=client,
    ):
        assert release_recovery_lock("old-owner") is False


def test_renew_extends_only_when_owned() -> None:
    client = MagicMock()
    client.eval.return_value = 1
    with patch(
        "app.modules.shadow.application.recovery._redis",
        return_value=client,
    ):
        assert renew_recovery_lock("owner-a", ttl=600) is True
    assert client.eval.call_args.args[3] == "owner-a"


def test_renew_false_when_lock_stolen() -> None:
    client = MagicMock()
    client.eval.return_value = 0
    with patch(
        "app.modules.shadow.application.recovery._redis",
        return_value=client,
    ):
        assert renew_recovery_lock("owner-a") is False


def test_run_recovery_aborts_when_lock_lost_before_market() -> None:
    session = MagicMock()
    renews = iter([False])

    with patch(
        "app.modules.shadow.application.recovery.publish_recovery_status"
    ), patch(
        "app.modules.shadow.application.recovery.detect_market_eod_gap"
    ) as gap:
        out = run_market_shadow_recovery(
            session,
            renew_lock=lambda: next(renews),
            lock_token="tok",
            task_id="t1",
        )
    assert out["status"] == "RECOVERY_LOCK_LOST"
    gap.assert_not_called()


def test_two_workers_second_fails_acquire() -> None:
    """Simulate concurrent start: first NX wins, second loses."""
    store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, value, nx=False, ex=None):  # noqa: ANN001
            if nx and key in store:
                return False
            store[key] = value
            return True

        def eval(self, script, nkeys, key, *argv):  # noqa: ANN001
            owner = argv[0]
            if store.get(key) != owner:
                return 0
            if "expire" in script.lower():
                return 1
            store.pop(key, None)
            return 1

        def exists(self, key):  # noqa: ANN001
            return 1 if key in store else 0

        def get(self, key):  # noqa: ANN001
            v = store.get(key)
            return v.encode() if isinstance(v, str) else v

    fake = FakeRedis()
    with patch(
        "app.modules.shadow.application.recovery._redis",
        return_value=fake,
    ), patch(
        "app.modules.shadow.application.recovery.get_settings",
        return_value=SimpleNamespace(redis_url="redis://x"),
    ):
        assert try_acquire_recovery_lock("w1") is True
        assert try_acquire_recovery_lock("w2") is False
        assert renew_recovery_lock("w1") is True
        assert renew_recovery_lock("w2") is False
        assert release_recovery_lock("w2") is False
        assert release_recovery_lock("w1") is True
        assert try_acquire_recovery_lock("w2") is True


def test_heartbeat_renews_during_long_stage() -> None:
    """Lease stays owned across a stage longer than TTL via heartbeat renewals."""
    renews: list[str] = []

    def renew_fn(token: str) -> bool:
        renews.append(token)
        return True

    lease = RecoveryLockLease(
        "owner-hb",
        ttl=1,
        heartbeat_seconds=0.05,
        renew_fn=renew_fn,
    ).start()
    try:
        time.sleep(0.22)
        assert lease.owned is True
        assert lease.still_owned() is True
        assert lease.renew_count >= 2
        assert all(t == "owner-hb" for t in renews)
    finally:
        lease.stop()


def test_heartbeat_marks_lost_when_renew_fails() -> None:
    calls = {"n": 0}

    def renew_fn(token: str) -> bool:
        calls["n"] += 1
        return calls["n"] < 2  # first heartbeat ok path via still_owned; fail later

    lease = RecoveryLockLease(
        "owner-x",
        ttl=1,
        heartbeat_seconds=0.05,
        renew_fn=renew_fn,
    )
    # Force owned path; start heartbeat that will fail on first loop iteration after wait.
    assert lease.still_owned() is True  # call 1 succeeds
    lease.start()
    try:
        time.sleep(0.18)
        assert lease.owned is False
        assert lease.still_owned() is False
        assert lease.lost_at is not None
    finally:
        lease.stop()


def test_market_ingest_stops_commits_when_lease_lost() -> None:
    """Per-instrument progress commits must stop after commit_guard fails."""
    from app.modules.market.application.ingest import (
        MarketIngestionLockLost,
        MarketIngestionService,
    )

    session = MagicMock()
    commits = {"n": 0}
    session.commit.side_effect = lambda: commits.__setitem__("n", commits["n"] + 1)

    guard_calls = {"n": 0}

    def guard() -> bool:
        guard_calls["n"] += 1
        return guard_calls["n"] < 2  # first commit ok, second denied

    svc = MarketIngestionService(session, commit_progress=True, commit_guard=guard, pause_seconds=0)
    svc._commit_if_allowed()
    assert commits["n"] == 1
    try:
        svc._commit_if_allowed()
        raised = False
    except MarketIngestionLockLost:
        raised = True
    assert raised is True
    assert commits["n"] == 1
    session.rollback.assert_called()


def test_run_recovery_aborts_market_when_ingest_loses_lease() -> None:
    session = MagicMock()
    with patch(
        "app.modules.shadow.application.recovery.publish_recovery_status"
    ), patch(
        "app.modules.shadow.application.recovery.detect_market_eod_gap"
    ) as gap, patch(
        "app.modules.shadow.application.recovery.run_eod_market_recovery",
        return_value={"status": "RECOVERY_LOCK_LOST", "lock_lost": True, "reason": "recovery_lock_lost"},
    ) as market:
        gap.return_value = SimpleNamespace(status="STALE", local_complete_eod=None)
        out = run_market_shadow_recovery(
            session,
            renew_lock=lambda: True,
            lock_token="tok",
            task_id="t-market",
        )
    assert out["status"] == "RECOVERY_LOCK_LOST"
    assert out["reason"] == "lock_lost_during_market"
    market.assert_called_once()
    assert market.call_args.kwargs.get("commit_guard") is not None
    session.commit.assert_not_called()


def test_run_recovery_aborts_before_features_when_lease_lost() -> None:
    session = MagicMock()
    # 1 before market, 2 after market commit check, 3 before features → lost
    renews = iter([True, True, False])

    with patch(
        "app.modules.shadow.application.recovery.publish_recovery_status"
    ), patch(
        "app.modules.shadow.application.recovery.detect_market_eod_gap"
    ) as gap, patch(
        "app.modules.shadow.application.recovery.run_eod_market_recovery",
        return_value={"status": "SUCCESS"},
    ), patch(
        "app.modules.shadow.application.recovery.select_latest_complete_as_of",
        return_value=SimpleNamespace(complete=True, as_of=None),
    ), patch(
        "app.modules.shadow.application.recovery._ensure_features",
        return_value={"analytics": {}, "technical": {}},
    ) as features:
        gap.return_value = SimpleNamespace(
            status="STALE",
            local_complete_eod=None,
            expected_completed_session=None,
        )
        out = run_market_shadow_recovery(
            session,
            renew_lock=lambda: next(renews),
            commit_each_session=True,
            lock_token="tok",
            task_id="t-feat",
        )
    assert out["status"] == "RECOVERY_LOCK_LOST"
    assert out["reason"] == "lock_lost_before_features"
    features.assert_not_called()


def test_run_recovery_aborts_features_commit_when_lease_lost() -> None:
    session = MagicMock()
    # 1 before market, 2 after market, 3 before features, 4 before features commit → lost
    renews = iter([True, True, True, False])

    with patch(
        "app.modules.shadow.application.recovery.publish_recovery_status"
    ), patch(
        "app.modules.shadow.application.recovery.detect_market_eod_gap"
    ) as gap, patch(
        "app.modules.shadow.application.recovery.run_eod_market_recovery",
        return_value={"status": "SUCCESS"},
    ), patch(
        "app.modules.shadow.application.recovery.select_latest_complete_as_of",
        return_value=SimpleNamespace(complete=True, as_of=None),
    ), patch(
        "app.modules.shadow.application.recovery._ensure_features",
        return_value={"analytics": {}, "technical": {}},
    ) as features:
        gap.return_value = SimpleNamespace(
            status="STALE",
            local_complete_eod=None,
            expected_completed_session=None,
        )
        out = run_market_shadow_recovery(
            session,
            renew_lock=lambda: next(renews),
            commit_each_session=True,
            lock_token="tok",
            task_id="t-feat-commit",
        )
    assert out["status"] == "RECOVERY_LOCK_LOST"
    assert out["reason"] == "lock_lost_before_features_commit"
    features.assert_called_once()
    session.rollback.assert_called()
    # Market stage may have committed once; features must not get another durable commit after loss.
    assert session.commit.call_count <= 1


def test_ensure_features_passes_commit_guard_to_technical() -> None:
    from app.modules.shadow.application.recovery import _ensure_features

    session = MagicMock()
    guard = MagicMock(return_value=True)
    with patch(
        "app.modules.analytics.application.compute.FeatureComputeService"
    ) as analytics_cls, patch(
        "app.modules.technical.application.compute.TechnicalComputeService"
    ) as tech_cls:
        analytics_cls.return_value.run_update.return_value = {"ok": True}
        tech_cls.return_value.run_update.return_value = {"ok": True}
        _ensure_features(session, renew_lock=guard)
    tech_cls.assert_called_once()
    assert tech_cls.call_args.kwargs.get("commit_guard") is guard
    analytics_cls.assert_called_once_with(session)


def test_stale_owner_cannot_release_after_heartbeat_transfer() -> None:
    store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, value, nx=False, ex=None):  # noqa: ANN001
            if nx and key in store:
                return False
            store[key] = value
            return True

        def eval(self, script, nkeys, key, *argv):  # noqa: ANN001
            owner = argv[0]
            if store.get(key) != owner:
                return 0
            if "expire" in script.lower():
                return 1
            store.pop(key, None)
            return 1

    fake = FakeRedis()
    with patch(
        "app.modules.shadow.application.recovery._redis",
        return_value=fake,
    ), patch(
        "app.modules.shadow.application.recovery.get_settings",
        return_value=SimpleNamespace(redis_url="redis://x"),
    ):
        assert try_acquire_recovery_lock("old") is True
        # Simulate TTL expiry + new owner without old releasing.
        store["projectai:lock:market_shadow_recovery"] = "new"
        assert renew_recovery_lock("old") is False
        assert release_recovery_lock("old") is False
        assert release_recovery_lock("new") is True
