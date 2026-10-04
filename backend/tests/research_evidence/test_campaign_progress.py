"""Operational campaign progress — not part of evidence identity."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from app.modules.learning.application.builder import PITDatasetBuilder
from app.modules.learning.dataset_config import PIT_DAILY_CORE_V4_VERSION
from app.modules.prediction.application.splits import WalkForwardFold
from app.modules.research_evidence.campaign_economics import (
    enumerate_robustness_cells,
    run_economic_robustness_campaign,
)
from app.modules.research_evidence.campaign_oos import run_paired_v3_v4_evidence_campaign
from app.modules.research_evidence.campaign_progress import (
    STAGE_WEIGHTS,
    CampaignProgress,
    assert_weights_sum_100,
    mark_progress_file_error,
    write_progress_atomic,
)
from app.modules.research_evidence.campaign_runner import run_canonical_evidence_campaign_v1
from app.modules.research_evidence.campaign_window import STATUS_INSUFFICIENT as CAMPAIGN_DATA_INSUFFICIENT
from tests.learning.test_dataset_v3 import _bind_flush_only, _seed_v3_fixture
from tests.research_evidence.test_campaign_oos import (
    FEATURE_NAMES,
    _factory,
    _panel_frame,
)
from tests.research_evidence.test_campaign_runner import _inspect_ready, _insufficient_snapshot


def test_progress_weights_sum_to_100() -> None:
    assert_weights_sum_100()
    assert sum(STAGE_WEIGHTS.values()) == 100.0


def test_resume_completed_stages_initial_pct(tmp_path: Path) -> None:
    progress = CampaignProgress(tmp_path / "progress.json", campaign_id="w", heartbeat=False)
    progress.mark_completed(["DATA_SNAPSHOT", "SAFE_DATA_REFRESH", "BUILD_V3"])
    snap = progress.snapshot()
    assert snap["approx_progress_pct"] == 5.0
    assert "BUILD_V4" not in snap["completed_stages"]
    progress.close()


def test_progress_never_decreases_or_exceeds_100(tmp_path: Path) -> None:
    progress = CampaignProgress(tmp_path / "progress.json", campaign_id="w", heartbeat=False)
    seen: list[float] = []
    progress.update_stage_units("BUILD_V4", current=100, total=1000, unit="samples")
    seen.append(progress.snapshot()["approx_progress_pct"])
    progress.update_stage_units("BUILD_V4", current=50, total=1000, unit="samples")
    seen.append(progress.snapshot()["approx_progress_pct"])
    progress.update_stage_units("BUILD_V4", current=400, total=1000, unit="samples")
    seen.append(progress.snapshot()["approx_progress_pct"])
    assert seen[1] == seen[0]
    assert seen[2] >= seen[1]
    progress.finish(status="COMPLETE")
    assert progress.snapshot()["approx_progress_pct"] == 100.0
    assert progress.snapshot()["approx_progress_pct"] <= 100.0


def test_blocked_keeps_partial_progress(tmp_path: Path) -> None:
    progress = CampaignProgress(tmp_path / "progress.json", campaign_id="w", heartbeat=False)
    progress.mark_completed(["DATA_SNAPSHOT", "SAFE_DATA_REFRESH"])
    progress.update_stage_units("BUILD_V4", current=11800, total=42988, unit="samples")
    before = progress.snapshot()["approx_progress_pct"]
    assert 2.0 < before < 100.0
    progress.finish(status="BLOCKED", block_code="CAMPAIGN_DATA_INSUFFICIENT", block_reason="short")
    after = progress.snapshot()
    assert after["status"] == "BLOCKED"
    assert after["approx_progress_pct"] == before
    assert after["block_code"] == "CAMPAIGN_DATA_INSUFFICIENT"


def test_heartbeat_does_not_advance_pct(tmp_path: Path) -> None:
    progress = CampaignProgress(tmp_path / "progress.json", campaign_id="w", heartbeat=False)
    progress.update_stage_units("BUILD_V4", current=200, total=1000, unit="samples")
    first = progress.snapshot()
    with progress._lock:
        progress._flush_locked(force=True)
    second = progress.snapshot()
    assert second["approx_progress_pct"] == first["approx_progress_pct"]
    assert second["last_progress_at"] >= first["last_progress_at"]
    progress.close()


def test_atomic_progress_file_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "progress.json"
    write_progress_atomic(path, {"status": "RUNNING", "approx_progress_pct": 1.2})
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "RUNNING"
    assert not path.with_name("progress.json.tmp").exists()
    mark_progress_file_error(path, error="boom")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "ERROR"


def test_v4_progress_callback_does_not_change_hash(core_db: Session) -> None:
    _bind_flush_only(core_db)
    fx = _seed_v3_fixture(core_db)
    ids = [fx["aaa"].id, fx["dead"].id]
    builder = PITDatasetBuilder(core_db)
    seen: list[int] = []

    def _cb(info: dict) -> None:
        seen.append(int(info["current"]))

    r1 = builder.run_build(
        date_from=date(2024, 5, 6),
        date_to=date(2024, 5, 20),
        dataset_spec_version=PIT_DAILY_CORE_V4_VERSION,
        instrument_ids=ids,
        seed_specs=False,
    )
    r2 = builder.run_build(
        date_from=date(2024, 5, 6),
        date_to=date(2024, 5, 20),
        dataset_spec_version=PIT_DAILY_CORE_V4_VERSION,
        instrument_ids=ids,
        seed_specs=False,
        progress_callback=_cb,
        expected_samples=int(r1["samples_total"] or 0),
    )
    assert r1["values_hash"] == r2["values_hash"]
    assert r1["dataset_hash"] == r2["dataset_hash"]
    assert seen


def test_oos_fold_callback_reports_count() -> None:
    folds = [
        WalkForwardFold(
            fold_id=0,
            train_start=date(2023, 1, 1),
            train_end=date(2024, 6, 1),
            validation_start=date(2024, 6, 1),
            validation_end=date(2024, 6, 10),
        ),
        WalkForwardFold(
            fold_id=1,
            train_start=date(2023, 1, 1),
            train_end=date(2024, 6, 10),
            validation_start=date(2024, 6, 10),
            validation_end=date(2024, 7, 1),
        ),
    ]
    events: list[dict] = []
    run_paired_v3_v4_evidence_campaign(
        _panel_frame(),
        persist_registry=False,
        model_factory=_factory,
        feature_names=FEATURE_NAMES,
        folds=folds,
        min_train_n=5,
        min_val_n=5,
        fold_progress=events.append,
    )
    regression = [e for e in events if e.get("semantic") == "regression"]
    ranking = [e for e in events if e.get("semantic") == "ranking"]
    assert len(regression) == 2
    assert len(ranking) == 2
    assert regression[-1]["fold_index"] == 2
    assert regression[-1]["fold_total"] == 2


def test_economics_reports_36_cell_progress() -> None:
    cells = enumerate_robustness_cells()
    assert len(cells) == 36
    finished: list[str] = []

    def _fake_cell(**kwargs: object) -> dict:
        cell = kwargs["cell"]
        return {
            "cell": cell.as_dict(),
            "strategy": {"metrics": {"cumulative_price_return": 0.01}},
        }

    with (
        patch(
            "app.modules.research_evidence.campaign_economics.validate_oos_prediction_frame",
            lambda *a, **k: None,
        ),
        patch(
            "app.modules.research_evidence.campaign_economics.run_predeclared_cell",
            _fake_cell,
        ),
    ):
        run_economic_robustness_campaign(
            predictions=MagicMock(),
            market=SimpleNamespace(trading_days=[]),
            observer=lambda event, payload=None: finished.append(event),
        )
    assert finished.count("cell_metrics_finished") == 36


def test_blocked_runner_writes_partial_progress(tmp_path: Path) -> None:
    result = run_canonical_evidence_campaign_v1(
        MagicMock(),
        None,
        workflow_id="progress-block",
        persist_registry=False,
        artifact_root=tmp_path,
        snapshot_builder=lambda _s: _insufficient_snapshot(),
        inspect_fn=lambda _s: _inspect_ready(),
        refresh_fn=lambda _s, dry_run=True: {"dry_run": dry_run, "before": {}, "after": {}},
        pair_fn=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no pair")),
        oos_fn=lambda **_k: (_ for _ in ()).throw(AssertionError("no oos")),
        economics_fn=lambda **_k: (_ for _ in ()).throw(AssertionError("no econ")),
    )
    assert result["block_code"] == CAMPAIGN_DATA_INSUFFICIENT
    payload = json.loads(
        (tmp_path / "research_evidence" / "campaign_runtime" / "progress-block" / "progress.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["status"] == "BLOCKED"
    assert payload["approx_progress_pct"] < 100
    assert payload["approx_progress_pct"] >= 2.0
