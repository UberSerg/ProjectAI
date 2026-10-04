"""EvidenceDossierV1 + prospective snapshot: empty valid, captures ≠ matured, immutable hash."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.memory.domain.decision_memory import HORIZONS, OUTCOME_PENDING, RETURN_TYPE_PRICE
from app.modules.research_evidence.bundle import payload_file_hash
from app.modules.research_evidence.campaign_dossier import (
    CAMPAIGN_VERSION,
    DEFAULT_LIMITATIONS,
    DOSSIER_SECTION_KEYS,
    EVIDENCE_DOSSIER_VERSION,
    FORBIDDEN_DOSSIER_KEYS,
    OWNER_DOSSIER_COMPLETE,
    OWNER_INCOMPLETE,
    STATUS_BLOCKED,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    STATUS_INSUFFICIENT,
    STATUS_INSUFFICIENT_SAMPLE,
    STATUS_OBSERVED,
    STATUS_PARTIAL,
    STATUS_PENDING,
    DossierImmutabilityError,
    build_evidence_dossier_v1,
    build_prospective_snapshot_v1,
    campaign_artifact_dir,
    classify_prospective_completeness,
    fingerprint_campaign_identity,
    on_disk_semantic_hash,
    persist_evidence_dossier,
)
from app.modules.research_evidence.prospective import build_prospective_evidence_v1

DOSSIER_SRC = (
    Path(__file__).resolve().parents[2] / "app" / "modules" / "research_evidence" / "campaign_dossier.py"
)


class _Scalars:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class FakeReadSession:
    def __init__(self, **tables: list[object]) -> None:
        self._tables = tables

    def add(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("session.add is forbidden on dossier prospective paths")

    def commit(self) -> None:
        raise AssertionError("session.commit is forbidden on dossier prospective paths")

    def scalars(self, stmt: object) -> _Scalars:
        entity = None
        descriptions = getattr(stmt, "column_descriptions", None) or []
        if descriptions:
            entity = descriptions[0].get("entity")
        table = getattr(entity, "__tablename__", None)
        return _Scalars(self._tables.get(table, []))


def _record(*, rec_id: int, portfolio_id: int = 7) -> SimpleNamespace:
    return SimpleNamespace(id=rec_id, portfolio_id=portfolio_id)


def _action(*, action_id: int, record_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=action_id,
        decision_record_id=record_id,
        action="CONSIDER_INCREASE",
        instrument_id=10,
        symbol="SBER",
    )


def _pending_outcome(*, action_id: int, horizon: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=action_id * 100 + horizon,
        decision_action_id=action_id,
        horizon_sessions=horizon,
        status=OUTCOME_PENDING,
        return_type=RETURN_TYPE_PRICE,
        forward_return=None,
        directional_alignment=None,
    )


def _identity(**extra: object) -> dict:
    body = {
        "campaign_version": CAMPAIGN_VERSION,
        "date_from": "2018-01-03",
        "date_to": "2024-12-30",
        "dataset_v3_run_id": 3,
        "dataset_v4_run_id": 4,
        "dataset_v3_hash": "v3hash",
        "dataset_v4_hash": "v4hash",
        "historical_universe_version": "historical_equity_universe_v2",
        "primary_target": "forward_return_20d",
        "model_seed": 42,
    }
    body.update(extra)
    return body


def _complete_parts() -> dict:
    return {
        "data_snapshot": {"status": STATUS_COMPLETE, "data_snapshot_hash": "snap"},
        "dataset_pair": {"status": STATUS_COMPLETE, "fair_contract_status": "PASS"},
        "historical_oos": {"status": STATUS_COMPLETE, "mean_ic": 0.01},
        "ablation": {"status": STATUS_COMPLETE},
        "stability": {"status": STATUS_COMPLETE},
        "economics_primary": {"status": STATUS_COMPLETE},
        "economics_robustness": {"status": STATUS_COMPLETE},
    }


def _collect_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys |= _collect_keys(child)
    elif isinstance(value, list):
        for child in value:
            keys |= _collect_keys(child)
    return keys


def test_source_does_not_call_pdm_refresh_or_writes() -> None:
    src = DOSSIER_SRC.read_text(encoding="utf-8")
    for token in (
        "refresh_outcomes",
        "capture_decision",
        "confirm_operation_link",
        "session.add",
        ".commit(",
        "persist_registry=True",
        "persist_registry = True",
    ):
        assert token not in src, token


def test_empty_prospective_is_valid_empty() -> None:
    snap = build_prospective_snapshot_v1()
    assert snap["empty"] is True
    assert snap["status"] == STATUS_EMPTY
    assert snap["horizon_contract"] == list(HORIZONS)
    pdm = snap["personal_decision_memory"]
    assert pdm is None or pdm.get("captures_total") in {0, None}
    assert classify_prospective_completeness(snap) == STATUS_EMPTY
    dossier = build_evidence_dossier_v1(identity=_identity(), prospective=snap)
    assert dossier["evidence_completeness"]["PROSPECTIVE"] == STATUS_EMPTY
    assert dossier["schema"] == EVIDENCE_DOSSIER_VERSION


def test_twenty_captures_zero_matured_is_not_observed() -> None:
    records = [_record(rec_id=i) for i in range(1, 21)]
    actions = [_action(action_id=i, record_id=i) for i in range(1, 21)]
    outcomes = [_pending_outcome(action_id=i, horizon=20) for i in range(1, 21)]
    memory = FakeReadSession(
        personal_decision_records=records,
        personal_decision_actions=actions,
        personal_decision_outcomes=outcomes,
        personal_decision_operation_links=[],
    )
    raw = build_prospective_evidence_v1(memory_session=memory)
    assert raw["personal_decision_memory"]["captures_total"] == 20
    h20 = next(h for h in raw["personal_decision_memory"]["horizons"] if h["horizon_sessions"] == 20)
    assert h20["matured_count"] == 0
    snap = build_prospective_snapshot_v1(memory_session=memory)
    assert snap["empty"] is False
    assert snap["status"] != STATUS_OBSERVED
    pdm = snap["personal_decision_memory"]
    assert pdm["captures_total"] == 20
    mapped = next(h for h in pdm["horizons"] if h["horizon_sessions"] == 20)
    assert mapped["matured_count"] == 0
    assert mapped["status"] != STATUS_OBSERVED
    assert {pdm["horizons"][i]["horizon_sessions"] for i in range(len(pdm["horizons"]))} >= set(HORIZONS)
    assert classify_prospective_completeness(snap) == STATUS_INSUFFICIENT_SAMPLE
    assert classify_prospective_completeness(snap) != STATUS_OBSERVED
    freshness = snap["forward_predictions"]["freshness"]
    assert freshness["matured_count"] == 0
    assert freshness["pending_remains_pending"] is True


def test_completeness_statuses_and_owner_review() -> None:
    empty = build_evidence_dossier_v1(identity=_identity())
    for key in DOSSIER_SECTION_KEYS:
        assert key in empty
    comp = empty["evidence_completeness"]
    assert set(comp) == {
        "DATA_INTEGRITY",
        "HISTORICAL_OOS",
        "ECONOMICS",
        "PROSPECTIVE",
        "OWNER_REVIEW_STATE",
    }
    assert comp["DATA_INTEGRITY"] == STATUS_BLOCKED
    assert comp["HISTORICAL_OOS"] == STATUS_BLOCKED
    assert comp["ECONOMICS"] == STATUS_INSUFFICIENT
    assert comp["PROSPECTIVE"] == STATUS_EMPTY
    assert comp["OWNER_REVIEW_STATE"] == OWNER_INCOMPLETE

    complete = build_evidence_dossier_v1(identity=_identity(), **_complete_parts())
    done = complete["evidence_completeness"]
    assert done["DATA_INTEGRITY"] == STATUS_COMPLETE
    assert done["HISTORICAL_OOS"] == STATUS_COMPLETE
    assert done["ECONOMICS"] == STATUS_COMPLETE
    assert done["PROSPECTIVE"] == STATUS_EMPTY
    assert done["OWNER_REVIEW_STATE"] == OWNER_DOSSIER_COMPLETE

    partial = build_evidence_dossier_v1(
        identity=_identity(),
        data_snapshot={"status": STATUS_PARTIAL},
        dataset_pair={"status": STATUS_COMPLETE, "fair_contract_status": "PASS"},
        historical_oos={"status": STATUS_INSUFFICIENT},
        economics_primary={"status": STATUS_PARTIAL},
        economics_robustness={"status": STATUS_COMPLETE},
        prospective=build_prospective_snapshot_v1(),
    )
    mixed = partial["evidence_completeness"]
    assert mixed["DATA_INTEGRITY"] == STATUS_PARTIAL
    assert mixed["HISTORICAL_OOS"] == STATUS_INSUFFICIENT
    assert mixed["ECONOMICS"] == STATUS_PARTIAL
    assert mixed["OWNER_REVIEW_STATE"] == OWNER_DOSSIER_COMPLETE

    blocked_pair = build_evidence_dossier_v1(
        identity=_identity(),
        data_snapshot={"status": STATUS_COMPLETE},
        dataset_pair={"status": "FAIR_CONTRACT_FAIL"},
        historical_oos={"status": STATUS_PENDING},
        economics_primary={"status": STATUS_COMPLETE},
        economics_robustness={"status": STATUS_COMPLETE},
    )
    assert blocked_pair["evidence_completeness"]["HISTORICAL_OOS"] == STATUS_BLOCKED
    assert blocked_pair["evidence_completeness"]["OWNER_REVIEW_STATE"] == OWNER_INCOMPLETE


def test_dossier_has_no_master_score_accuracy_or_winner_keys() -> None:
    dirty = _complete_parts()
    dirty["historical_oos"] = {
        "status": STATUS_COMPLETE,
        "kraken_score": 99,
        "accuracy": 0.8,
        "winner": "V4",
        "overall_accuracy": 0.7,
        "mean_ic": 0.02,
    }
    dossier = build_evidence_dossier_v1(identity=_identity(), **dirty)
    keys = {k.lower() for k in _collect_keys(dossier)}
    for banned in FORBIDDEN_DOSSIER_KEYS:
        assert banned not in keys
        assert banned not in dossier
    assert "kraken_score" not in keys
    assert "accuracy" not in keys
    assert "winner" not in keys
    assert dossier["historical_oos"]["mean_ic"] == 0.02
    for code in ("NO_COMBINED_MASTER_SCORE", "NOT_KRAKEN_ACCURACY", "NO_V4_WINNER_VERDICT"):
        assert code in DEFAULT_LIMITATIONS
        assert code in dossier["limitations"]


def test_hash_stable_without_timestamps(tmp_path: Path) -> None:
    parts = _complete_parts()
    a = build_evidence_dossier_v1(
        identity=_identity(created_at="2026-01-01T00:00:00+00:00", generated_at="t1"),
        **parts,
    )
    b = build_evidence_dossier_v1(
        identity=_identity(created_at="2099-12-31T23:59:59+00:00", generated_at="t2"),
        **parts,
    )
    assert a["campaign_fingerprint"] == b["campaign_fingerprint"]
    assert fingerprint_campaign_identity(a["identity"]) == fingerprint_campaign_identity(b["identity"])
    hash_a = on_disk_semantic_hash(a, tmp_path=tmp_path / "a")
    hash_b = on_disk_semantic_hash(b, tmp_path=tmp_path / "b")
    assert hash_a == hash_b
    assert len(hash_a) == 64


def test_nan_hash_matches_on_disk(tmp_path: Path) -> None:
    dossier = build_evidence_dossier_v1(
        identity=_identity(),
        historical_oos={
            "status": STATUS_COMPLETE,
            "metrics": {"mean_ic": float("nan"), "mae": float("inf")},
        },
        **{k: v for k, v in _complete_parts().items() if k != "historical_oos"},
    )
    written = persist_evidence_dossier(dossier, artifact_root=tmp_path)
    path = Path(written["path"])
    disk = json.loads(path.read_text(encoding="utf-8"))
    assert disk["historical_oos"]["metrics"]["mean_ic"] is None
    assert disk["historical_oos"]["metrics"]["mae"] is None
    assert written["dossier_hash"] == payload_file_hash(disk)
    assert written["dossier_hash"] == on_disk_semantic_hash(dossier, tmp_path=tmp_path / "rehash")


def test_immutable_reuse_or_refuse(tmp_path: Path) -> None:
    first = build_evidence_dossier_v1(identity=_identity(), **_complete_parts())
    written = persist_evidence_dossier(first, artifact_root=tmp_path)
    assert written["reuse"] is False
    dest = campaign_artifact_dir(first["campaign_fingerprint"], root=tmp_path)
    assert Path(written["path"]) == dest / "evidence_dossier.json"

    again = persist_evidence_dossier(
        build_evidence_dossier_v1(
            identity=_identity(created_at="2099-01-01T00:00:00+00:00"),
            **_complete_parts(),
        ),
        artifact_root=tmp_path,
    )
    assert again["reuse"] is True
    assert again["dossier_hash"] == written["dossier_hash"]

    drifted = build_evidence_dossier_v1(
        identity=_identity(),
        **{**_complete_parts(), "historical_oos": {"status": STATUS_COMPLETE, "mean_ic": 0.99}},
    )
    with pytest.raises(DossierImmutabilityError, match="refuse overwrite"):
        persist_evidence_dossier(drifted, artifact_root=tmp_path)

    other_fp = build_evidence_dossier_v1(
        identity=_identity(date_to="2023-12-29"),
        **_complete_parts(),
    )
    other = persist_evidence_dossier(other_fp, artifact_root=tmp_path)
    assert other["reuse"] is False
    assert other["campaign_fingerprint"] != first["campaign_fingerprint"]
