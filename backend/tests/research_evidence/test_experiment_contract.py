"""Focused contract tests for Research Evidence experiment identity, pairing, and bundle."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.learning.models import DatasetRun
from app.modules.learning.application.research_eval import (
    FairCompareError,
    assert_fair_v3_v4_compare_contract,
)
from app.modules.research_evidence.bundle import write_evidence_bundle
from app.modules.research_evidence.experiment import (
    EVALUATION_WORDING,
    EXPERIMENT_VERSION,
    ResearchEvidenceExperimentV1,
    fingerprint_identity,
)
from app.modules.research_evidence.pairing import prove_paired_v3_v4, resolve_or_build_paired_runs

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


def test_paired_mismatch_hard_fails_with_fair_contract_fail() -> None:
    session = MagicMock()
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
    session = MagicMock()
    run3 = MagicMock()
    run3.dataset_hash = "h3"
    run3.manifest = {}
    run3.date_from = datetime(2020, 1, 2).date()
    run3.date_to = datetime(2024, 12, 30).date()
    run3.pit_violations = 0
    run4 = MagicMock()
    run4.dataset_hash = "h4"
    run4.manifest = {}
    run4.date_from = run3.date_from
    run4.date_to = run3.date_to
    run4.pit_violations = 2
    session.get.side_effect = lambda _model, pk: {1: run3, 2: run4}[int(pk)]
    with patch(
        "app.modules.research_evidence.pairing.assert_fair_v3_v4_compare_contract",
        return_value={"pins_match": True},
    ):
        with patch(
            "app.modules.research_evidence.pairing.assert_v3_v4_run_population_identity",
            return_value={"sample_identity_match": True, "target_identity_match": True},
        ):
            with pytest.raises(FairCompareError, match="FAIR_CONTRACT_FAIL"):
                prove_paired_v3_v4(session, 1, 2)


def test_paired_same_contract_passes() -> None:
    session = MagicMock()
    run3 = MagicMock()
    run3.dataset_hash = "h3"
    run3.manifest = {"values_hash": "v3"}
    run3.date_from = datetime(2020, 1, 2).date()
    run3.date_to = datetime(2024, 12, 30).date()
    run3.pit_violations = 0
    run4 = MagicMock()
    run4.dataset_hash = "h4"
    run4.manifest = {"values_hash": "v4"}
    run4.date_from = run3.date_from
    run4.date_to = run3.date_to
    run4.pit_violations = 0

    def _get(_model: object, pk: int) -> object:
        return {1: run3, 2: run4}[int(pk)]

    session.get.side_effect = _get
    population = {
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
            return_value=population,
        ):
            proof = prove_paired_v3_v4(session, 1, 2)
    assert proof["fair_contract_status"] == "PASS"
    assert proof["sample_identity_match"] is True
    assert proof["pit_violations"] == 0
    assert proof["v4"]["pit_violations"] == 0
    assert proof["dataset_v3_hash"] == "h3"
    assert proof["dataset_v4_values_hash"] == "v4"
    session.get.assert_any_call(DatasetRun, 1)


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
