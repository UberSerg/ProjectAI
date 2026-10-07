"""IntelligenceRefreshV1 — unit tests (no live MOEX/CBR/Polza)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.modules.intelligence.operations.config import REFRESH_STAGES, REFRESH_WORKFLOW_KEY
from app.modules.intelligence.operations.models import RefreshRun
from app.modules.intelligence.operations.refresh import run_intelligence_refresh
from app.modules.intelligence.operations.stages import StageResult, run_stage_with_retries
from app.modules.intelligence.operations.status import (
    build_operational_status,
    build_source_health,
    collect_stale_warnings,
)


class _ScalarResult:
    def __init__(self, rows: list[RefreshRun]) -> None:
        self._rows = rows

    def all(self) -> list[RefreshRun]:
        return list(self._rows)


class FakeSession:
    def __init__(self) -> None:
        self.rows: list[RefreshRun] = []
        self._id = 0
        self.rolled_back = False

    def add(self, row: RefreshRun) -> None:
        self.rows.append(row)

    def flush(self) -> None:
        for row in self.rows:
            current = row.__dict__.get("id")
            if current in (None, 0):
                self._id += 1
                row.id = self._id

    def get(self, model, key):  # noqa: ANN001
        if model is RefreshRun:
            return next((r for r in self.rows if r.id == key), None)
        return None

    def rollback(self) -> None:
        self.rolled_back = True

    def commit(self) -> None:
        return None

    def scalars(self, stmt):  # noqa: ANN001
        text = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        rows = list(self.rows)
        if "RUNNING" in text and "SUCCESS" not in text:
            rows = [r for r in rows if r.status == "RUNNING"]
        elif "SUCCESS" in text:
            rows = [r for r in rows if r.status in {"SUCCESS", "NO_CHANGES", "WARNING"}]
        return _ScalarResult(list(reversed(rows)))

    def scalar(self, stmt):  # noqa: ANN001
        text = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        rows = list(self.rows)
        if "SUCCESS" in text:
            rows = [r for r in rows if r.status in {"SUCCESS", "NO_CHANGES", "WARNING"}]
            finished = [r for r in rows if r.finished_at is not None]
            if not finished:
                return None
            return sorted(finished, key=lambda r: (r.finished_at, r.id or 0), reverse=True)[0]
        return rows[-1] if rows else None


def _lock(acquired: bool) -> MagicMock:
    handle = MagicMock()
    handle.acquired = acquired
    return handle


def _noop_runner(_session, _ctx) -> StageResult:
    return StageResult(status="SKIPPED", reason="TEST_NOOP", changed=False)


def _success_runner(_session, _ctx) -> StageResult:
    return StageResult(status="SUCCESS", reason="TEST", changed=True, details={"rows": 1})


STUB_RUNNERS = {name: _noop_runner for name in REFRESH_STAGES}


def test_stage_order() -> None:
    assert REFRESH_STAGES[0] == "MARKET_INTRADAY"
    assert REFRESH_STAGES[-1] == "FINALIZE"
    assert REFRESH_STAGES == [
        "MARKET_INTRADAY",
        "FUNDAMENTALS",
        "NEWS",
        "EXTRACT_EVENTS",
        "MACRO",
        "BUILD_SNAPSHOTS",
        "RUN_MODELS",
        "RISK",
        "COMMITTEE",
        "FINALIZE",
    ]


@patch("app.modules.intelligence.operations.refresh.try_acquire_refresh_lock")
def test_lock_blocks_second_run(mock_lock: MagicMock) -> None:
    mock_lock.return_value = _lock(False)
    result = run_intelligence_refresh(FakeSession(), skip_lock=False)
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "ALREADY_RUNNING"


@patch("app.modules.intelligence.operations.refresh.try_acquire_refresh_lock")
def test_all_skipped_is_no_changes(mock_lock: MagicMock) -> None:
    mock_lock.return_value = _lock(True)
    session = FakeSession()
    result = run_intelligence_refresh(session, stage_runners=STUB_RUNNERS)
    assert result["status"] == "NO_CHANGES"
    assert result["progress"]["completed"] == len(REFRESH_STAGES)
    assert result["progress"]["total"] == len(REFRESH_STAGES)
    row = session.rows[0]
    assert row.workflow_key == REFRESH_WORKFLOW_KEY
    assert row.status == "NO_CHANGES"
    assert row.finished_at is not None
    assert all(row.stages[name]["status"] == "SKIPPED" for name in REFRESH_STAGES)


@patch("app.modules.intelligence.operations.refresh.try_acquire_refresh_lock")
def test_idempotent_second_run_does_not_create_new_row(mock_lock: MagicMock) -> None:
    mock_lock.return_value = _lock(True)
    session = FakeSession()
    first = run_intelligence_refresh(session, stage_runners=STUB_RUNNERS)
    second = run_intelligence_refresh(session, stage_runners=STUB_RUNNERS)
    assert first["status"] == "NO_CHANGES"
    assert second["status"] == "NO_CHANGES"
    assert second["reason"] == "IDEMPOTENT_HIT"
    assert second["refresh_run_id"] == first["refresh_run_id"]
    assert len(session.rows) == 1


@patch("app.modules.intelligence.operations.refresh.try_acquire_refresh_lock")
def test_force_reruns_despite_fingerprint(mock_lock: MagicMock) -> None:
    mock_lock.return_value = _lock(True)
    session = FakeSession()
    run_intelligence_refresh(session, stage_runners=STUB_RUNNERS)
    forced = run_intelligence_refresh(session, stage_runners=STUB_RUNNERS, force=True)
    assert forced.get("reason") != "IDEMPOTENT_HIT"
    assert forced["refresh_run_id"] != session.rows[0].id
    assert len(session.rows) == 2


@patch("app.modules.intelligence.operations.refresh.try_acquire_refresh_lock")
def test_changed_stage_yields_success(mock_lock: MagicMock) -> None:
    mock_lock.return_value = _lock(True)
    runners = dict(STUB_RUNNERS)
    runners["NEWS"] = _success_runner
    session = FakeSession()
    result = run_intelligence_refresh(session, stage_runners=runners)
    assert result["status"] == "SUCCESS"
    assert result["changed"] is True
    assert result["stages"]["NEWS"]["status"] == "SUCCESS"


def test_bounded_retries_then_success() -> None:
    calls = {"n": 0}

    def flaky(_session, _ctx) -> StageResult:
        calls["n"] += 1
        if calls["n"] < 3:
            return StageResult(status="FAILED", reason="TRANSIENT", error="boom")
        return StageResult(status="SUCCESS", changed=True)

    session = FakeSession()
    result = run_stage_with_retries(
        session, "NEWS", flaky, {}, max_retries=2, backoff_seconds=0
    )
    assert result.status == "SUCCESS"
    assert result.attempts == 3
    assert calls["n"] == 3


def test_bounded_retries_exhausted() -> None:
    def always_fail(_session, _ctx) -> StageResult:
        return StageResult(status="FAILED", reason="HARD")

    result = run_stage_with_retries(
        FakeSession(), "RISK", always_fail, {}, max_retries=2, backoff_seconds=0
    )
    assert result.status == "FAILED"
    assert result.attempts == 3


@patch("app.modules.intelligence.operations.refresh.try_acquire_refresh_lock")
def test_failed_stage_does_not_abort_remaining(mock_lock: MagicMock) -> None:
    mock_lock.return_value = _lock(True)

    def fail(_session, _ctx) -> StageResult:
        return StageResult(status="FAILED", reason="HARD", error="x")

    runners = dict(STUB_RUNNERS)
    runners["FUNDAMENTALS"] = fail
    session = FakeSession()
    result = run_intelligence_refresh(
        session, stage_runners=runners, max_retries=0, backoff_seconds=0
    )
    assert result["status"] == "WARNING"
    assert result["stages"]["FUNDAMENTALS"]["status"] == "FAILED"
    assert result["stages"]["COMMITTEE"]["status"] == "SKIPPED"
    assert result["progress"]["completed"] == len(REFRESH_STAGES)


@patch("app.modules.intelligence.operations.refresh.try_acquire_refresh_lock")
def test_stale_running_finalized_then_new_run(mock_lock: MagicMock) -> None:
    mock_lock.return_value = _lock(True)
    session = FakeSession()
    orphan = RefreshRun(
        workflow_key=REFRESH_WORKFLOW_KEY,
        status="RUNNING",
        stages={},
        started_at=datetime.now(UTC),
        run_metadata={},
    )
    session.add(orphan)
    session.flush()
    result = run_intelligence_refresh(session, stage_runners=STUB_RUNNERS)
    assert orphan.status == "FAILED"
    assert orphan.error_message and "STALE_RUNNING" in orphan.error_message
    assert result["status"] == "NO_CHANGES"
    assert result["refresh_run_id"] != orphan.id


@patch("app.modules.intelligence.operations.refresh.try_acquire_refresh_lock")
def test_dry_run_skips_hooks(mock_lock: MagicMock) -> None:
    mock_lock.return_value = _lock(True)
    called = {"n": 0}

    def boom(_session, _ctx) -> StageResult:
        called["n"] += 1
        raise AssertionError("must not run")

    runners = {name: boom for name in REFRESH_STAGES}
    session = FakeSession()
    result = run_intelligence_refresh(session, stage_runners=runners, dry_run=True)
    assert called["n"] == 0
    assert result["reason"] == "DRY_RUN"
    assert all(s["reason"] == "DRY_RUN" for s in result["stages"].values())


def test_stale_warnings_when_sources_never_succeeded() -> None:
    session = FakeSession()
    health = build_source_health(session, current_stages=None)
    warnings = collect_stale_warnings(health)
    assert any(w["code"] == "STALE_SOURCE" for w in warnings)
    assert "MARKET_INTRADAY" in health


def test_source_health_not_stale_when_fresh() -> None:
    now = datetime.now(UTC)
    stages = {
        name: {"status": "SUCCESS", "finished_at": now.isoformat(), "reason": None}
        for name in REFRESH_STAGES
    }
    session = FakeSession()
    row = RefreshRun(
        workflow_key=REFRESH_WORKFLOW_KEY,
        status="SUCCESS",
        stages=stages,
        started_at=now,
        finished_at=now,
        run_metadata={"changed": True},
    )
    session.add(row)
    session.flush()
    health = build_source_health(session, current_stages=stages, now=now)
    assert health["NEWS"]["stale"] is False
    old = now - timedelta(hours=100)
    health_old = build_source_health(
        session,
        current_stages={
            "NEWS": {"status": "SUCCESS", "finished_at": old.isoformat(), "reason": None}
        },
        now=now,
    )
    assert health_old["NEWS"]["stale"] is True


@patch("app.modules.intelligence.operations.status.is_refresh_lock_held", return_value=False)
def test_operational_status_orphan_running(_lock: MagicMock) -> None:
    session = FakeSession()
    session.add(
        RefreshRun(
            workflow_key=REFRESH_WORKFLOW_KEY,
            status="RUNNING",
            stages={"MARKET_INTRADAY": {"status": "RUNNING"}},
            started_at=datetime.now(UTC),
            run_metadata={"progress": {"completed": 0, "total": 10}, "current_stage": "MARKET_INTRADAY"},
        )
    )
    session.flush()
    payload = build_operational_status(session)
    assert payload["running"] is True
    assert payload["orphan_running"] is True
    assert payload["polling_policy"]["aggressive_polling"] is False
    assert payload["polling_policy"]["scheduled_beat"] is False
    assert any(w["code"] == "STALE_RUNNING" for w in payload["stale_warnings"])


def test_cli_run_and_status_exit_codes() -> None:
    from app.modules.intelligence.operations.cli import main

    fake_cm = MagicMock()
    fake_cm.__enter__.return_value = FakeSession()
    fake_cm.__exit__.return_value = False
    with (
        patch("app.modules.intelligence.operations.cli.core_session", return_value=fake_cm),
        patch(
            "app.modules.intelligence.operations.cli.run_intelligence_refresh",
            return_value={"status": "NO_CHANGES"},
        ) as run_fn,
        patch(
            "app.modules.intelligence.operations.cli.build_operational_status",
            return_value={"workflow_key": REFRESH_WORKFLOW_KEY},
        ),
    ):
        assert main(["status"]) == 0
        assert main(["run", "--dry-run", "--force"]) == 0
        run_fn.assert_called()
        kwargs = run_fn.call_args.kwargs
        assert kwargs["dry_run"] is True
        assert kwargs["force"] is True


def test_default_hooks_skip_missing_modules() -> None:
    from app.modules.intelligence.operations.stages import stage_news

    result = stage_news(FakeSession(), {})  # type: ignore[arg-type]
    assert result.status == "SKIPPED"
    assert result.reason in {"MODULE_NOT_AVAILABLE", "HOOK_NOT_AVAILABLE"}


def test_celery_task_not_on_beat_schedule() -> None:
    from pathlib import Path

    from app.worker import celery_app as celery_mod
    from app.worker import tasks as tasks_mod

    beat_src = Path(celery_mod.__file__).read_text(encoding="utf-8")
    task_src = Path(tasks_mod.__file__).read_text(encoding="utf-8")
    assert "projectai.intelligence_refresh_v1" in task_src
    assert "projectai.intelligence_refresh_v1" not in beat_src


def test_production_isolation_pins_unchanged() -> None:
    from app.modules.intelligence.isolation import production_isolation_report

    report = production_isolation_report()
    assert report["candidate_promotion"] is False
    assert report["shadow_policy_switch"] is False
    assert report["broker_execution"] is False
    assert report["active_dataset_unchanged"] is True
