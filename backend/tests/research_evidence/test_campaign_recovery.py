"""Recovery/resume tests for Canonical Evidence Campaign V1."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.modules.learning.dataset_config import PIT_DAILY_CORE_ACTIVE_VERSION
from app.modules.prediction.candidate_config import CandidateV0Config
from app.modules.prediction.candidate_v1_config import CandidateV1RankerConfig
from app.modules.research_evidence.campaign_recovery import (
    INTERRUPT_REASON,
    find_reusable_dataset_run,
    interrupt_stale_campaign_dataset_builds,
)
from app.modules.research_evidence.campaign_runner import run_canonical_evidence_campaign_v1
from app.modules.research_evidence.campaign_window import PRIMARY_DATE_FROM


def test_production_pins_unchanged() -> None:
    assert PIT_DAILY_CORE_ACTIVE_VERSION == 1
    assert CandidateV0Config().dataset_spec_version == 2
    assert CandidateV1RankerConfig().dataset_spec_version == 2


def test_success_v3_run_is_reusable() -> None:
    run = SimpleNamespace(id=655, status="SUCCESS", pit_status="PASS", samples_total=10)
    session = MagicMock()
    session.scalars.return_value.first.return_value = run
    found = find_reusable_dataset_run(
        session,
        spec_version=3,
        date_from=date(2022, 4, 1),
        date_to=date(2026, 9, 1),
    )
    assert found is run


def test_incomplete_v3_run_is_not_reusable() -> None:
    session = MagicMock()
    session.scalars.return_value.first.return_value = None
    found = find_reusable_dataset_run(
        session,
        spec_version=3,
        date_from=date(2022, 4, 1),
        date_to=date(2026, 9, 1),
    )
    assert found is None


def test_interrupt_stale_running_v4_uses_finish_workflow(monkeypatch) -> None:
    run = SimpleNamespace(
        id=656,
        dataset_spec_id="spec-4",
        workflow_id=2923,
        status="RUNNING",
        error_message=None,
        finished_at=None,
        date_from=PRIMARY_DATE_FROM,
    )
    spec = SimpleNamespace(id="spec-4", version=4)
    step = SimpleNamespace(status="RUNNING", name="Build PIT features")
    workflow = SimpleNamespace(id=2923, status="RUNNING", steps=[step], error=None, finished_at=None)
    session = MagicMock()
    session.scalars.return_value = [run]
    session.get.side_effect = lambda model, key: spec if key == "spec-4" else workflow

    finished: list[tuple] = []

    def _finish(sess, wf, status, *, error=None):
        finished.append((wf.id, status, error))
        wf.status = status
        wf.error = error

    monkeypatch.setattr(
        "app.modules.research_evidence.campaign_recovery.finish_workflow",
        _finish,
    )
    monkeypatch.setattr(
        "app.modules.research_evidence.campaign_recovery.update_step",
        lambda sess, st, status, error=None: setattr(st, "status", status),
    )
    touched = interrupt_stale_campaign_dataset_builds(session)
    assert touched[0]["dataset_run_id"] == 656
    assert run.status == "ERROR"
    assert run.error_message == INTERRUPT_REASON
    assert finished == [(2923, "ERROR", INTERRUPT_REASON)]


def test_blocked_historical_stages_are_retried(tmp_path) -> None:
    from app.modules.prediction.infrastructure.artifacts import write_json
    from app.modules.research_evidence.campaign_runner import _CampaignState
    from app.modules.research_evidence.paths import campaign_runtime_dir

    runtime = campaign_runtime_dir(77, root=tmp_path)
    runtime.mkdir(parents=True, exist_ok=True)
    state = _CampaignState(runtime / "state.json")
    pre = "same-identity"
    snap = {
        "schema": "research_data_snapshot_v1",
        "data_snapshot_hash": "ab" * 32,
        "created_at": "2026-01-01T00:00:00+00:00",
        "campaign_window_status": "OK",
        "campaign_window": {
            "status": "OK",
            "primary": {"date_from": "2022-04-01", "date_to": "2025-06-01"},
            "date_from": "2022-04-01",
            "date_to": "2025-06-01",
        },
        "domains": [],
        "overall_availability": "PARTIAL",
    }
    write_json(runtime / "research_data_snapshot.json", snap)
    write_json(runtime / "refresh_audit.json", {"dry_run": True})
    state.data["pre_pair_identity"] = pre
    state.data["data_snapshot_hash"] = snap["data_snapshot_hash"]
    state.mark("DATA_SNAPSHOT", "SUCCESS", identity=pre)
    state.mark("SAFE_DATA_REFRESH", "SUCCESS", identity=pre)
    for name in (
        "BUILD_V3",
        "BUILD_V4",
        "FAIR_PAIR_PROOF",
        "OOS_REGRESSION",
        "OOS_RANKER",
        "ABLATION",
        "STABILITY",
        "ECONOMICS_PRIMARY",
        "ECONOMICS_ROBUSTNESS",
    ):
        state.mark(name, "BLOCKED", identity=pre, extra={"code": "PIT_FAIL"})
    state.save()

    pair_calls: list[int] = []

    def pair_fn(*_a, **_k):
        pair_calls.append(1)
        raise RuntimeError("stop-after-pair-called")

    try:
        run_canonical_evidence_campaign_v1(
            MagicMock(),
            None,
            workflow_id=77,
            persist_registry=False,
            artifact_root=tmp_path,
            snapshot_builder=lambda _s: snap,
            inspect_fn=lambda _s: {
                "equity_instruments": 10,
                "daily_equity_candles": 1000,
                "instruments_with_daily_history": 10,
                "fns_gir_bo_reports": 5,
                "fundamentals_schema_ready": True,
            },
            refresh_fn=lambda _s, dry_run=True: {"dry_run": dry_run},
            pair_fn=pair_fn,
        )
    except RuntimeError as exc:
        assert "stop-after-pair-called" in str(exc)
    assert pair_calls == [1]


def test_pit_fail_dossier_not_overwritten_under_same_hash(tmp_path) -> None:
    from app.modules.research_evidence.campaign_dossier import (
        DossierImmutabilityError,
        persist_evidence_dossier,
    )

    dossier = {
        "schema": "EvidenceDossierV1",
        "campaign_fingerprint": "audit-pit-fail",
        "identity": {"campaign_version": "CanonicalEvidenceCampaignV1", "note": "PIT_FAIL"},
        "data_snapshot": {"status": "COMPLETE"},
        "dataset_pair": {"status": "BLOCKED"},
        "historical_oos": {"status": "BLOCKED"},
        "ablation": {"status": "BLOCKED"},
        "stability": {"status": "BLOCKED"},
        "economics_primary": {"status": "BLOCKED"},
        "economics_robustness": {"status": "BLOCKED"},
        "prospective": {"status": "EMPTY"},
        "limitations": [],
        "evidence_completeness": {"OWNER_REVIEW_STATE": "EVIDENCE_INCOMPLETE"},
    }
    first = persist_evidence_dossier(dossier, artifact_root=tmp_path)
    assert first["status"] in {"WRITTEN", "REUSED"}
    changed = dict(dossier)
    changed["dataset_pair"] = {"status": "COMPLETE", "run_id": 1}
    try:
        persist_evidence_dossier(changed, artifact_root=tmp_path)
        reused = False
    except DossierImmutabilityError:
        reused = True
    assert reused is True
