"""Focused contract tests for Research Evidence experiment identity, pairing, and bundle."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.infrastructure.learning.models import DatasetRun, DatasetSpec
from app.modules.learning.application.research_eval import (
    FairCompareError,
    assert_fair_v3_v4_compare_contract,
)
from app.modules.learning.dataset_config import PIT_DAILY_CORE_CODE
from app.modules.research_evidence.bundle import recompute_bundle_hash, write_evidence_bundle
from app.modules.research_evidence.experiment import (
    EVALUATION_WORDING,
    EXPERIMENT_VERSION,
    ResearchEvidenceExperimentV1,
    fingerprint_identity,
)
from app.modules.research_evidence.pairing import prove_paired_v3_v4, resolve_or_build_paired_runs
from app.modules.research_evidence.service import finalize_bundle

_KW = dict(
    dataset_v3_run_id=11,
    dataset_v4_run_id=12,
    dataset_v3_hash="aaa",
    dataset_v4_hash="bbb",
    dataset_v3_values_hash=None,
    dataset_v4_values_hash="ccc",
    date_from="2020-01-02",
    date_to="2024-12-30",
    model_seed=42,
)


def test_deterministic_fingerprint() -> None:
    a = ResearchEvidenceExperimentV1(**_KW)
    b = ResearchEvidenceExperimentV1(**_KW)
    assert a.experiment_fingerprint == b.experiment_fingerprint
    assert len(a.experiment_fingerprint) == 64
    assert a.identity_payload()["experiment_version"] == EXPERIMENT_VERSION
    assert a.identity_payload()["persist_registry"] is False


def test_key_order_independence() -> None:
    identity = ResearchEvidenceExperimentV1(**_KW).identity_payload()
    reversed_keys = dict(reversed(list(identity.items())))
    inserted_first = {"zzz_noise_should_not_exist": 1, **identity}
    inserted_first.pop("zzz_noise_should_not_exist")
    assert fingerprint_identity(identity) == fingerprint_identity(reversed_keys)
    assert fingerprint_identity(identity) == fingerprint_identity(inserted_first)


def test_runtime_timestamp_not_in_identity() -> None:
    stamped = ResearchEvidenceExperimentV1(
        **_KW, created_at=datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    )
    plain = ResearchEvidenceExperimentV1(**_KW, created_at=None)
    identity = stamped.identity_payload()
    assert "created_at" not in identity
    assert stamped.experiment_fingerprint == plain.experiment_fingerprint
    record = stamped.to_record()
    assert record["created_at"] is not None
    assert "pristine final holdout" not in str(record).lower()
    assert "live ready" not in str(record).lower()
    assert EVALUATION_WORDING in record["evaluation_wording"]


def test_persist_registry_true_rejected() -> None:
    with pytest.raises(ValueError, match="persist_registry"):
        ResearchEvidenceExperimentV1(**_KW, persist_registry=True)


def test_fair_v3_v4_schema_contract_passes() -> None:
    fair = assert_fair_v3_v4_compare_contract()
    assert fair["pins_match"] is True
    assert fair["added_feature_count"] > 0
    groups = ResearchEvidenceExperimentV1(**_KW).identity_payload()["feature_group_definitions"]
    assert set(groups) == {"BASE", "FUNDAMENTALS", "EVENTS", "V4_FULL"}
    assert groups["BASE"]
    assert set(groups["FUNDAMENTALS"]).isdisjoint(groups["BASE"])
    assert set(groups["EVENTS"]).isdisjoint(groups["BASE"])
    assert groups["V4_FULL"][: len(groups["BASE"])] == groups["BASE"]


_DATE_FROM = datetime(2020, 1, 2).date()
_DATE_TO = datetime(2024, 12, 30).date()
_COVERAGE_V4 = {"eligible_20d": 9, "v4": {"preload_query_count": 1}}


def _fake_spec(*, version: int, code: str = PIT_DAILY_CORE_CODE) -> MagicMock:
    spec = MagicMock()
    spec.id = uuid4()
    spec.code = code
    spec.version = version
    return spec


def _fake_run(
    spec: MagicMock,
    *,
    dataset_hash: str,
    values_hash: str | None = None,
    status: str = "SUCCESS",
    pit_status: str = "PASS",
    pit_violations: int = 0,
    date_from=_DATE_FROM,
    date_to=_DATE_TO,
    coverage_summary: dict | None = None,
) -> MagicMock:
    run = MagicMock()
    run.dataset_spec_id = spec.id
    run.dataset_hash = dataset_hash
    run.manifest = {"values_hash": values_hash} if values_hash is not None else {}
    run.status = status
    run.pit_status = pit_status
    run.pit_violations = pit_violations
    run.date_from = date_from
    run.date_to = date_to
    run.coverage_summary = coverage_summary
    return run


def _session_for(run3: MagicMock, spec3: MagicMock, run4: MagicMock, spec4: MagicMock) -> MagicMock:
    session = MagicMock()
    runs = {1: run3, 2: run4}
    specs = {spec3.id: spec3, spec4.id: spec4}

    def _get(model: object, pk: object) -> object | None:
        if model is DatasetRun:
            return runs.get(int(pk))  # type: ignore[arg-type]
        if model is DatasetSpec:
            return specs.get(pk)
        return None

    session.get.side_effect = _get
    return session


def _prove_ok(session: MagicMock, *, population: dict | None = None) -> dict:
    payload = population or {
        "fair_contract_status": "PASS",
        "sample_identity_match": True,
        "target_identity_match": True,
        "samples": 9,
    }
    with patch(
        "app.modules.research_evidence.pairing.assert_fair_v3_v4_compare_contract",
        return_value=assert_fair_v3_v4_compare_contract(),
    ):
        with patch(
            "app.modules.research_evidence.pairing.assert_v3_v4_run_population_identity",
            return_value=payload,
        ):
            return prove_paired_v3_v4(session, 1, 2)


def _genuine_pair(
    *,
    spec3_version: int = 3,
    spec4_version: int = 4,
    date_from_v4=_DATE_FROM,
    date_to_v4=_DATE_TO,
    pit_status_v3: str = "PASS",
    pit_status_v4: str = "PASS",
    pit_violations_v3: int = 0,
    pit_violations_v4: int = 0,
    status_v3: str = "SUCCESS",
    status_v4: str = "WARNING",
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock, MagicMock]:
    spec3 = _fake_spec(version=spec3_version)
    spec4 = _fake_spec(version=spec4_version)
    run3 = _fake_run(
        spec3,
        dataset_hash="h3",
        values_hash="v3",
        status=status_v3,
        pit_status=pit_status_v3,
        pit_violations=pit_violations_v3,
        coverage_summary={"eligible_20d": 9},
    )
    run4 = _fake_run(
        spec4,
        dataset_hash="h4",
        values_hash="v4",
        status=status_v4,
        pit_status=pit_status_v4,
        pit_violations=pit_violations_v4,
        date_from=date_from_v4,
        date_to=date_to_v4,
        coverage_summary=_COVERAGE_V4,
    )
    return _session_for(run3, spec3, run4, spec4), run3, spec3, run4, spec4


def test_paired_mismatch_hard_fails_with_fair_contract_fail() -> None:
    session, *_ = _genuine_pair()
    with patch(
        "app.modules.research_evidence.pairing.assert_fair_v3_v4_compare_contract",
        return_value={"pins_match": True},
    ):
        with patch(
            "app.modules.research_evidence.pairing.assert_v3_v4_run_population_identity",
            side_effect=FairCompareError("FAIR_CONTRACT_FAIL: sample identity differs"),
        ):
            with pytest.raises(FairCompareError, match="FAIR_CONTRACT_FAIL"):
                prove_paired_v3_v4(session, 1, 2)


def test_paired_population_without_pass_is_not_defaulted_to_pass() -> None:
    session, *_ = _genuine_pair()
    with pytest.raises(FairCompareError, match="FAIR_CONTRACT_FAIL"):
        _prove_ok(
            session,
            population={"sample_identity_match": True, "target_identity_match": True},
        )


def test_wrong_v3_spec_version_fails() -> None:
    session, *_ = _genuine_pair(spec3_version=2)
    with pytest.raises(FairCompareError, match="FAIR_CONTRACT_FAIL"):
        _prove_ok(session)


def test_wrong_v4_spec_version_fails() -> None:
    session, *_ = _genuine_pair(spec4_version=3)
    with pytest.raises(FairCompareError, match="FAIR_CONTRACT_FAIL"):
        _prove_ok(session)


def test_differing_windows_fail() -> None:
    session, *_ = _genuine_pair(date_from_v4=datetime(2021, 1, 2).date())
    with pytest.raises(FairCompareError, match="FAIR_CONTRACT_FAIL"):
        _prove_ok(session)


def test_pit_status_not_pass_fails() -> None:
    session, *_ = _genuine_pair(pit_status_v4="PENDING")
    with pytest.raises(FairCompareError, match="FAIR_CONTRACT_FAIL"):
        _prove_ok(session)


def test_pit_violations_nonzero_fail() -> None:
    session, *_ = _genuine_pair(pit_violations_v4=2)
    with pytest.raises(FairCompareError, match="FAIR_CONTRACT_FAIL"):
        _prove_ok(session)


def test_paired_same_contract_passes() -> None:
    session, run3, _spec3, run4, _spec4 = _genuine_pair()
    proof = _prove_ok(session)
    assert proof["fair_contract_status"] == "PASS"
    assert proof["sample_identity_match"] is True
    assert proof["pit_violations"] == 0
    assert proof["pit_status"] == "PASS"
    assert proof["coverage_summary"] == _COVERAGE_V4
    assert proof["v4"]["pit_violations"] == 0
    assert proof["v4"]["pit_status"] == "PASS"
    assert proof["v4"]["coverage_summary"] == _COVERAGE_V4
    assert proof["dataset_v3_hash"] == "h3"
    assert proof["dataset_v4_values_hash"] == "v4"
    session.get.assert_any_call(DatasetRun, 1)
    session.get.assert_any_call(DatasetSpec, run3.dataset_spec_id)
    session.get.assert_any_call(DatasetSpec, run4.dataset_spec_id)


def test_resolve_build_path_is_orchestrator_owned() -> None:
    with pytest.raises(NotImplementedError, match="orchestrator-owned"):
        resolve_or_build_paired_runs(MagicMock(), build_if_missing=True)


def test_evidence_bundle_pending_and_hash_ignores_runtime_timestamps(tmp_path: Path) -> None:
    first = write_evidence_bundle(
        tmp_path / "a",
        {
            "manifest": {"created_at": "2026-01-01T00:00:00+00:00", "note": "x"},
            "dataset_compare": {"status": "ok", "created_at": "t1"},
        },
    )
    second = write_evidence_bundle(
        tmp_path / "b",
        {
            "manifest": {"created_at": "2099-12-31T23:59:59+00:00", "note": "x"},
            "dataset_compare": {"status": "ok", "created_at": "t2"},
        },
    )
    assert first["bundle_hash"] == second["bundle_hash"]
    import json

    manifest = json.loads((tmp_path / "a" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["research_only"] is True
    assert manifest["production_registry_mutated"] is False
    assert manifest["candidate_promoted"] is False
    assert manifest["shadow_mutated"] is False
    assert manifest["personal_decision_mutated"] is False
    assert manifest["primary_return_semantic"] == "MECHANICAL_PRICE_RETURN"
    assert manifest["total_return"] is False
    assert manifest["persist_registry"] is False
    assert EVALUATION_WORDING in manifest["evaluation_wording"]
    ablation = json.loads((tmp_path / "a" / "ablation.json").read_text(encoding="utf-8"))
    assert ablation == {"status": "PENDING"}
    overview = json.loads((tmp_path / "a" / "evidence_overview.json").read_text(encoding="utf-8"))
    assert overview == {"status": "PENDING"}
    for forbidden in ("pristine final holdout", "LIVE READY"):
        assert forbidden.lower() not in json.dumps(manifest).lower()


def test_finalize_bundle_returns_recomputed_final_hash(tmp_path: Path) -> None:
    parts_a = {
        "manifest": {"created_at": "2026-01-01T00:00:00+00:00", "note": "x"},
        "dataset_compare": {"status": "ok", "created_at": "t1"},
    }
    parts_b = {
        "manifest": {"created_at": "2099-12-31T23:59:59+00:00", "note": "x"},
        "dataset_compare": {"status": "ok", "created_at": "t2"},
    }
    result = finalize_bundle(tmp_path / "a" / "exp", parts_a)
    other = finalize_bundle(tmp_path / "b" / "exp", parts_b)
    recomputed = recompute_bundle_hash(tmp_path / "a" / "exp")
    assert result["bundle_hash"] == recomputed
    assert result["bundle_hash"] == other["bundle_hash"]
    assert "experiment" in result["overview"]
    provisional = write_evidence_bundle(tmp_path / "c" / "exp", parts_a)
    assert result["bundle_hash"] != provisional["bundle_hash"]


def test_finalize_bundle_nan_metrics_match_on_disk_hash(tmp_path: Path) -> None:
    parts = {
        "manifest": {"note": "nan-metrics"},
        "model_regression": {
            "status": "ok",
            "metrics": {"mean_ic": float("nan"), "mae": float("inf"), "n": 0},
        },
    }
    written = write_evidence_bundle(tmp_path / "nan", parts)
    assert written["bundle_hash"] == recompute_bundle_hash(tmp_path / "nan")
    finalized = finalize_bundle(tmp_path / "nan-final", parts)
    assert finalized["bundle_hash"] == recompute_bundle_hash(tmp_path / "nan-final")
