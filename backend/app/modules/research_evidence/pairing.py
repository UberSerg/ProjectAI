"""Paired Dataset V3/V4 population proof — reuses existing fair-compare helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetRun, DatasetSpec
from app.modules.learning.application.research_eval import (
    FairCompareError,
    assert_fair_v3_v4_compare_contract,
    assert_v3_v4_run_population_identity,
)
from app.modules.learning.dataset_config import PIT_DAILY_CORE_CODE

_ACCEPTABLE_RUN_STATUSES = frozenset({"SUCCESS", "WARNING"})


def _values_hash(run: DatasetRun) -> str | None:
    manifest = run.manifest or {}
    raw = manifest.get("values_hash")
    return str(raw) if raw is not None else None


def _pit_count(run: DatasetRun) -> int | None:
    raw = getattr(run, "pit_violations", None)
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and raw == raw:
        return int(raw)
    return None


def _ensure_fair_contract_fail(exc: BaseException) -> FairCompareError:
    text = str(exc)
    if "FAIR_CONTRACT_FAIL" not in text:
        text = f"FAIR_CONTRACT_FAIL: {text}"
    if isinstance(exc, FairCompareError) and "FAIR_CONTRACT_FAIL" in str(exc):
        return exc
    return FairCompareError(text)


def _load_run(session: Session, run_id: int, *, label: str) -> DatasetRun:
    run = session.get(DatasetRun, int(run_id))
    if run is None:
        raise FairCompareError(
            f"FAIR_CONTRACT_FAIL: DatasetRun row missing for {label} (run_id={run_id})"
        )
    return run


def _load_spec(session: Session, run: DatasetRun, *, label: str) -> DatasetSpec:
    spec = session.get(DatasetSpec, run.dataset_spec_id)
    if spec is None:
        raise FairCompareError(
            f"FAIR_CONTRACT_FAIL: DatasetSpec missing for {label} run "
            f"(dataset_spec_id={run.dataset_spec_id})"
        )
    return spec


def _require_spec(spec: DatasetSpec, *, expected_version: int, label: str) -> None:
    if spec.code != PIT_DAILY_CORE_CODE or spec.version != expected_version:
        raise FairCompareError(
            "FAIR_CONTRACT_FAIL: argument names are not proof of schema; "
            f"{label} DatasetSpec must be {PIT_DAILY_CORE_CODE} version {expected_version} "
            f"(got code={spec.code!r}, version={spec.version!r})"
        )


def _require_run_status(run: DatasetRun, *, label: str) -> None:
    if run.status not in _ACCEPTABLE_RUN_STATUSES:
        raise FairCompareError(
            f"FAIR_CONTRACT_FAIL: {label} run status={run.status!r} "
            "(only SUCCESS/WARNING are acceptable)"
        )


def _require_matching_windows(run_v3: DatasetRun, run_v4: DatasetRun) -> None:
    if run_v3.date_from is None or run_v3.date_to is None:
        raise FairCompareError("FAIR_CONTRACT_FAIL: v3 run missing date_from/date_to")
    if run_v4.date_from is None or run_v4.date_to is None:
        raise FairCompareError("FAIR_CONTRACT_FAIL: v4 run missing date_from/date_to")
    if run_v3.date_from != run_v4.date_from or run_v3.date_to != run_v4.date_to:
        raise FairCompareError(
            "FAIR_CONTRACT_FAIL: mismatched run windows: "
            f"v3 {run_v3.date_from}→{run_v3.date_to} vs v4 {run_v4.date_from}→{run_v4.date_to}"
        )


def _require_pit_pass(run: DatasetRun, *, label: str) -> int:
    if run.pit_status != "PASS":
        raise FairCompareError(
            f"FAIR_CONTRACT_FAIL: {label} pit_status={run.pit_status!r} is not PASS "
            "(missing/unknown pit_status is not PASS)"
        )
    pit = _pit_count(run)
    if pit != 0:
        raise FairCompareError(
            f"FAIR_CONTRACT_FAIL: {label} pit_violations={pit!r} (required 0)"
        )
    return pit


def _side_payload(run: DatasetRun, *, pit_violations: int) -> dict[str, Any]:
    return {
        "coverage_summary": run.coverage_summary,
        "pit_status": run.pit_status,
        "pit_violations": pit_violations,
        "status": run.status,
    }


def prove_paired_v3_v4(session: Session, v3_run_id: int, v4_run_id: int) -> dict[str, Any]:
    """Hard-fail unless real V3/V4 DatasetRuns match schema, window, PIT, and identity."""
    run_v3 = _load_run(session, int(v3_run_id), label="v3")
    run_v4 = _load_run(session, int(v4_run_id), label="v4")
    spec_v3 = _load_spec(session, run_v3, label="v3")
    spec_v4 = _load_spec(session, run_v4, label="v4")
    _require_spec(spec_v3, expected_version=3, label="v3")
    _require_spec(spec_v4, expected_version=4, label="v4")
    _require_run_status(run_v3, label="v3")
    _require_run_status(run_v4, label="v4")
    _require_matching_windows(run_v3, run_v4)
    pit_v3 = _require_pit_pass(run_v3, label="v3")
    pit_v4 = _require_pit_pass(run_v4, label="v4")
    try:
        schema = assert_fair_v3_v4_compare_contract()
        population = assert_v3_v4_run_population_identity(
            session, v3_run_id=int(v3_run_id), v4_run_id=int(v4_run_id)
        )
    except (FairCompareError, ValueError) as exc:
        raise _ensure_fair_contract_fail(exc) from exc

    status = population.get("fair_contract_status")
    if (
        status != "PASS"
        or population.get("sample_identity_match") is not True
        or population.get("target_identity_match") is not True
    ):
        raise FairCompareError(
            "FAIR_CONTRACT_FAIL: paired V3/V4 sample/target identity was not proven"
        )
    v4_side = _side_payload(run_v4, pit_violations=pit_v4)
    return {
        "dataset_v3_hash": run_v3.dataset_hash,
        "dataset_v3_run_id": int(v3_run_id),
        "dataset_v3_values_hash": _values_hash(run_v3),
        "dataset_v4_hash": run_v4.dataset_hash,
        "dataset_v4_run_id": int(v4_run_id),
        "dataset_v4_values_hash": _values_hash(run_v4),
        "date_from": run_v3.date_from.isoformat() if run_v3.date_from else None,
        "date_to": run_v3.date_to.isoformat() if run_v3.date_to else None,
        "fair_contract_status": "PASS",
        "population": population,
        "sample_identity_match": True,
        "schema": schema,
        "target_identity_match": True,
        "coverage_summary": run_v4.coverage_summary,
        "pit_status": run_v4.pit_status,
        "v3": _side_payload(run_v3, pit_violations=pit_v3),
        "v4": v4_side,
        "pit_violations": pit_v4,
    }


def resolve_or_build_paired_runs(
    session: Session,
    *,
    v3_run_id: int | None = None,
    v4_run_id: int | None = None,
    build_if_missing: bool = False,
) -> dict[str, Any]:
    """Path A: prove existing DatasetRun IDs.

    Path B (materialize new paired runs) is orchestrator-owned: this module must
    not activate the production DatasetSpec or train models.
    """
    if v3_run_id is not None and v4_run_id is not None:
        return prove_paired_v3_v4(session, v3_run_id, v4_run_id)
    if build_if_missing:
        raise NotImplementedError(
            "Building new paired DatasetRun rows is orchestrator-owned; "
            "research_evidence.pairing only proves existing IDs (path A) and "
            "does not activate production spec."
        )
    raise ValueError("v3_run_id and v4_run_id are required (path A: existing paired runs)")
