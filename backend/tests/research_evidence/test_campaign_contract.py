"""CanonicalEvidenceCampaignV1 identity and paired V3/V4 orchestration (no training)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.infrastructure.learning.models import DatasetRun, DatasetSpec
from app.modules.learning.application.compare_v3_v4 import CompareContractError
from app.modules.learning.application.research_eval import FairCompareError
from app.modules.learning.dataset_config import PIT_DAILY_CORE_CODE
from app.modules.market.application.historical_universe import HISTORICAL_EQUITY_UNIVERSE_V2
from app.modules.prediction.candidate_config import CATBOOST_HYPERPARAMETERS
from app.modules.prediction.candidate_v1_config import CATBOOST_RANKER_HYPERPARAMETERS
from app.modules.research_evidence.campaign_contract import (
    CAMPAIGN_VERSION,
    PRIMARY_COST_BPS_PER_SIDE,
    PRIMARY_REBALANCE_SESSIONS,
    PRIMARY_TARGET,
    PRIMARY_TOP_PERCENT,
    CanonicalEvidenceCampaignV1,
    default_economic_primary_contract,
    default_robustness_matrix_contract,
    fingerprint_identity,
    frozen_catboost_config_hash,
    ranker_model_config_hash,
    regression_model_config_hash,
)
from app.modules.research_evidence.campaign_pair import (
    assert_campaign_specs_ready,
    build_or_load_paired_v3_v4,
    campaign_from_proof,
)
from app.modules.research_evidence.pairing import prove_paired_v3_v4

_KW = dict(
    dataset_v3_run_id=21,
    dataset_v4_run_id=22,
    dataset_v3_hash="v3hash",
    dataset_v4_hash="v4hash",
    dataset_v3_values_hash="v3val",
    dataset_v4_values_hash="v4val",
    date_from="2022-04-01",
    date_to="2026-01-15",
    data_snapshot_hash=None,
    model_seed=42,
)


def test_deterministic_fingerprint_and_identity_fields() -> None:
    a = CanonicalEvidenceCampaignV1(**_KW)
    b = CanonicalEvidenceCampaignV1(**_KW)
    identity = a.identity_payload()
    assert a.campaign_fingerprint == b.campaign_fingerprint
    assert len(a.campaign_fingerprint) == 64
    assert identity["campaign_version"] == CAMPAIGN_VERSION
    assert "data_snapshot_hash" in identity
    assert identity["data_snapshot_hash"] is None
    assert identity["primary_target"] == PRIMARY_TARGET == "forward_return_20d"
    assert identity["historical_universe_version"] == HISTORICAL_EQUITY_UNIVERSE_V2
    assert identity["persist_registry"] is False
    assert identity["regression_config_hash"] == regression_model_config_hash()
    assert identity["ranker_config_hash"] == ranker_model_config_hash()
    assert identity["regression_config_hash"] == frozen_catboost_config_hash(
        CATBOOST_HYPERPARAMETERS
    )
    assert identity["ranker_config_hash"] == frozen_catboost_config_hash(
        CATBOOST_RANKER_HYPERPARAMETERS
    )
    assert identity["ablation_variants"] == [
        "BASE",
        "BASE+FUNDAMENTALS",
        "BASE+EVENTS",
        "V4_FULL",
    ]
    wf = identity["walk_forward_contract"]
    assert wf["kind"] == "expanding_walk_forward"
    assert wf["random_split"] is False
    assert wf["optuna"] is False
    assert wf["evaluation_end_policy"] == "CAMPAIGN_DATE_TO_INCLUSIVE"
    assert wf["evaluation_end_inclusive"] == "2026-01-15"
    assert wf["development_end_exclusive"] == "2026-01-16"
    assert wf["label_purge"]["target_date_20d_lt_validation_start"] is True
    primary = identity["economic_primary_contract"]
    assert primary == default_economic_primary_contract()
    assert primary["rebalance_sessions"] == PRIMARY_REBALANCE_SESSIONS
    assert primary["top_percent"] == PRIMARY_TOP_PERCENT
    assert primary["cost_bps_per_side"] == PRIMARY_COST_BPS_PER_SIDE
    matrix = identity["robustness_matrix_contract"]
    assert matrix == default_robustness_matrix_contract()
    assert matrix["cost_bps_per_side"] == [0, 10, 30, 50]
    assert matrix["rebalance_sessions"] == [10, 20, 40]
    assert matrix["top_percent"] == [10, 20, 30]
    assert matrix["primary"] == {
        "cost_bps_per_side": 30,
        "rebalance_sessions": 20,
        "top_percent": 20,
    }
    assert matrix["not_hyperparameter_search"] is True


def test_fingerprint_key_order_independent() -> None:
    identity = CanonicalEvidenceCampaignV1(**_KW).identity_payload()
    reversed_keys = dict(reversed(list(identity.items())))
    inserted_first = {"zzz_noise_should_not_exist": 1, **identity}
    inserted_first.pop("zzz_noise_should_not_exist")
    assert fingerprint_identity(identity) == fingerprint_identity(reversed_keys)
    assert fingerprint_identity(identity) == fingerprint_identity(inserted_first)


def test_runtime_timestamp_not_in_identity() -> None:
    stamped = CanonicalEvidenceCampaignV1(
        **_KW, created_at=datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    )
    plain = CanonicalEvidenceCampaignV1(**_KW, created_at=None)
    identity = stamped.identity_payload()
    assert "created_at" not in identity
    assert stamped.campaign_fingerprint == plain.campaign_fingerprint
    record = stamped.to_record()
    assert record["created_at"] is not None
    assert record["campaign_fingerprint"] == stamped.campaign_fingerprint


def test_persist_registry_true_rejected() -> None:
    with pytest.raises(ValueError, match="persist_registry"):
        CanonicalEvidenceCampaignV1(**_KW, persist_registry=True)
    with pytest.raises(ValueError, match="persist_registry"):
        build_or_load_paired_v3_v4(MagicMock(), persist_registry=True)


def test_snapshot_hash_placeholder_is_identity_field() -> None:
    empty = CanonicalEvidenceCampaignV1(**_KW)
    filled = CanonicalEvidenceCampaignV1(**{**_KW, "data_snapshot_hash": "abc" * 21 + "ab"})
    assert "data_snapshot_hash" in empty.identity_payload()
    assert empty.campaign_fingerprint != filled.campaign_fingerprint


_DATE_FROM = date(2022, 4, 1)
_DATE_TO = date(2024, 12, 30)
_FLAGS = [
    {"id": "1", "code": PIT_DAILY_CORE_CODE, "version": 1, "is_active": True},
    {"id": "3", "code": PIT_DAILY_CORE_CODE, "version": 3, "is_active": False},
    {"id": "4", "code": PIT_DAILY_CORE_CODE, "version": 4, "is_active": False},
]


def _fake_spec(*, version: int, is_active: bool = False) -> MagicMock:
    spec = MagicMock()
    spec.id = uuid4()
    spec.code = PIT_DAILY_CORE_CODE
    spec.version = version
    spec.is_active = is_active
    spec.universe_policy = HISTORICAL_EQUITY_UNIVERSE_V2
    return spec


def _fake_run(
    spec: MagicMock,
    *,
    dataset_hash: str,
    values_hash: str | None = "vh",
    status: str = "SUCCESS",
    pit_status: str = "PASS",
    pit_violations: int = 0,
    date_from=_DATE_FROM,
    date_to=_DATE_TO,
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
    run.coverage_summary = {"eligible_20d": 9}
    return run


def _session_ready() -> tuple[MagicMock, MagicMock, MagicMock, MagicMock, MagicMock]:
    spec1 = _fake_spec(version=1, is_active=True)
    spec3 = _fake_spec(version=3)
    spec4 = _fake_spec(version=4)
    run3 = _fake_run(spec3, dataset_hash="h3", values_hash="v3")
    run4 = _fake_run(spec4, dataset_hash="h4", values_hash="v4")
    session = MagicMock()
    runs = {1: run3, 2: run4}
    specs_by_id = {spec1.id: spec1, spec3.id: spec3, spec4.id: spec4}

    def _get(model: object, pk: object) -> object | None:
        if model is DatasetRun:
            return runs.get(int(pk))  # type: ignore[arg-type]
        if model is DatasetSpec:
            return specs_by_id.get(pk)
        return None

    calls = {"n": 0}

    def _scalar_seq(_stmt: object) -> object | None:
        calls["n"] += 1
        if calls["n"] == 1:
            return spec3
        if calls["n"] == 2:
            return spec4
        if calls["n"] == 3:
            return spec1
        return spec1

    session.get.side_effect = _get
    session.scalar.side_effect = _scalar_seq
    return session, spec3, spec4, run3, run4


def test_activating_spec_forbidden_source_and_runtime() -> None:
    from pathlib import Path

    pair_src = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "modules"
        / "research_evidence"
        / "campaign_pair.py"
    ).read_text(encoding="utf-8")
    assert "seed_dataset_specs(" not in pair_src
    assert "seed_specs=True" not in pair_src
    assert "is_active=True" not in pair_src

    session, *_ = _session_ready()
    with patch(
        "app.modules.research_evidence.campaign_pair.seed_dataset_specs",
        create=True,
    ) as seed:
        with patch(
            "app.modules.research_evidence.campaign_pair.snapshot_dataset_spec_flags",
            return_value=list(_FLAGS),
        ):
            with patch(
                "app.modules.research_evidence.campaign_pair.prove_paired_v3_v4",
                return_value={
                    "dataset_v3_run_id": 1,
                    "dataset_v4_run_id": 2,
                    "dataset_v3_hash": "h3",
                    "dataset_v4_hash": "h4",
                    "dataset_v3_values_hash": "v3",
                    "dataset_v4_values_hash": "v4",
                    "date_from": "2022-04-01",
                    "date_to": "2024-12-30",
                    "fair_contract_status": "PASS",
                    "sample_identity_match": True,
                    "target_identity_match": True,
                },
            ):
                result = build_or_load_paired_v3_v4(session, v3_run_id=1, v4_run_id=2)
    seed.assert_not_called()
    assert result["activation"]["unchanged"] is True
    assert result["fair_contract_status"] == "PASS"
    assert result["campaign"]["identity"]["persist_registry"] is False


def test_missing_specs_does_not_seed() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    with patch(
        "app.modules.research_evidence.campaign_pair.seed_dataset_specs",
        create=True,
    ) as seed:
        with pytest.raises(CompareContractError, match="does not seed or activate"):
            assert_campaign_specs_ready(session)
    seed.assert_not_called()


def test_activated_v3_spec_forbidden() -> None:
    session, spec3, spec4, _run3, _run4 = _session_ready()
    spec3.is_active = True
    with pytest.raises(ValueError, match="activated"):
        assert_campaign_specs_ready(session)


def test_fair_contract_fail_on_mismatch_fakes() -> None:
    session, spec3, spec4, run3, run4 = _session_ready()
    with patch(
        "app.modules.research_evidence.campaign_pair.snapshot_dataset_spec_flags",
        return_value=list(_FLAGS),
    ):
        with patch(
            "app.modules.research_evidence.campaign_pair.prove_paired_v3_v4",
            side_effect=FairCompareError("FAIR_CONTRACT_FAIL: sample identity differs"),
        ):
            with pytest.raises(FairCompareError, match="FAIR_CONTRACT_FAIL"):
                build_or_load_paired_v3_v4(session, v3_run_id=1, v4_run_id=2)


def test_fair_contract_fail_from_compare_sample_diff() -> None:
    session, *_ = _session_ready()
    with patch(
        "app.modules.research_evidence.campaign_pair.snapshot_dataset_spec_flags",
        return_value=list(_FLAGS),
    ):
        with patch(
            "app.modules.research_evidence.campaign_pair.compare_v3_v4_builds",
            return_value={
                "sample_diff": {"fair_contract_status": "FAIR_CONTRACT_FAIL"},
                "v3": {"run_id": 1},
                "v4": {"run_id": 2},
            },
        ):
            with pytest.raises(FairCompareError, match="FAIR_CONTRACT_FAIL"):
                build_or_load_paired_v3_v4(
                    session,
                    date_from=_DATE_FROM,
                    date_to=_DATE_TO,
                    rebuild=True,
                )


def test_campaign_from_unproven_proof_stops() -> None:
    with pytest.raises(FairCompareError, match="FAIR_CONTRACT_FAIL"):
        campaign_from_proof(
            {
                "dataset_v3_run_id": 1,
                "dataset_v4_run_id": 2,
                "dataset_v3_hash": "h3",
                "dataset_v4_hash": "h4",
                "date_from": "2022-04-01",
                "date_to": "2024-12-30",
                "fair_contract_status": "FAIR_CONTRACT_FAIL",
                "sample_identity_match": False,
                "target_identity_match": False,
            }
        )


def test_prove_paired_wrong_spec_version_fails() -> None:
    spec3 = _fake_spec(version=2)
    spec4 = _fake_spec(version=4)
    run3 = _fake_run(spec3, dataset_hash="h3")
    run4 = _fake_run(spec4, dataset_hash="h4")
    session = MagicMock()
    specs = {spec3.id: spec3, spec4.id: spec4}

    def _get(model: object, pk: object) -> object | None:
        if model is DatasetRun:
            return {1: run3, 2: run4}.get(int(pk))  # type: ignore[arg-type]
        if model is DatasetSpec:
            return specs.get(pk)
        return None

    session.get.side_effect = _get
    with pytest.raises(FairCompareError, match="FAIR_CONTRACT_FAIL"):
        prove_paired_v3_v4(session, 1, 2)


def test_build_path_uses_compare_without_activation() -> None:
    session, *_ = _session_ready()
    proof = {
        "dataset_v3_run_id": 11,
        "dataset_v4_run_id": 12,
        "dataset_v3_hash": "h3",
        "dataset_v4_hash": "h4",
        "dataset_v3_values_hash": "v3",
        "dataset_v4_values_hash": "v4",
        "date_from": "2022-04-01",
        "date_to": "2024-12-30",
        "fair_contract_status": "PASS",
        "sample_identity_match": True,
        "target_identity_match": True,
    }
    with patch(
        "app.modules.research_evidence.campaign_pair.snapshot_dataset_spec_flags",
        return_value=list(_FLAGS),
    ):
        with patch(
            "app.modules.research_evidence.campaign_pair.compare_v3_v4_builds",
            return_value={
                "sample_diff": {"fair_contract_status": "PASS"},
                "v3": {"run_id": 11},
                "v4": {"run_id": 12},
            },
        ) as compare:
            with patch(
                "app.modules.research_evidence.campaign_pair.prove_paired_v3_v4",
                return_value=proof,
            ) as prove:
                out = build_or_load_paired_v3_v4(
                    session,
                    date_from=_DATE_FROM,
                    date_to=_DATE_TO,
                    rebuild=True,
                    data_snapshot_hash=None,
                )
    compare.assert_called_once()
    kwargs = compare.call_args.kwargs
    assert kwargs["date_from"] == _DATE_FROM
    assert kwargs["date_to"] == _DATE_TO
    assert kwargs["rebuild"] is True
    prove.assert_called_once_with(session, 11, 12)
    identity = out["campaign"]["identity"]
    assert identity["dataset_v3_run_id"] == 11
    assert identity["campaign_version"] == CAMPAIGN_VERSION
    assert "created_at" not in identity
