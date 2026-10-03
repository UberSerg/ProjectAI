"""Paired Dataset V3/V4 population proof — reuses existing fair-compare helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetRun
from app.modules.learning.application.research_eval import (
    FairCompareError,
    assert_fair_v3_v4_compare_contract,
    assert_v3_v4_run_population_identity,
)


def _values_hash(run: DatasetRun) -> str | None:
    manifest = run.manifest or {}
    raw = manifest.get("values_hash")
    return str(raw) if raw is not None else None


def _ensure_fair_contract_fail(exc: BaseException) -> FairCompareError:
    text = str(exc)
    if "FAIR_CONTRACT_FAIL" not in text:
        text = f"FAIR_CONTRACT_FAIL: {text}"
    if isinstance(exc, FairCompareError) and "FAIR_CONTRACT_FAIL" in str(exc):
        return exc
    return FairCompareError(text)


def prove_paired_v3_v4(session: Session, v3_run_id: int, v4_run_id: int) -> dict[str, Any]:
    """Hard-fail unless V3/V4 schema pins and sample/target identity match."""
    try:
        schema = assert_fair_v3_v4_compare_contract()
        population = assert_v3_v4_run_population_identity(
            session, v3_run_id=int(v3_run_id), v4_run_id=int(v4_run_id)
        )
    except (FairCompareError, ValueError) as exc:
        raise _ensure_fair_contract_fail(exc) from exc

    run_v3 = session.get(DatasetRun, int(v3_run_id))
    run_v4 = session.get(DatasetRun, int(v4_run_id))
    if run_v3 is None or run_v4 is None:
        raise FairCompareError(
            "FAIR_CONTRACT_FAIL: DatasetRun row missing for paired V3/V4 proof "
            f"(v3_run_id={v3_run_id}, v4_run_id={v4_run_id})"
        )
    return {
        "dataset_v3_hash": run_v3.dataset_hash,
        "dataset_v3_run_id": int(v3_run_id),
        "dataset_v3_values_hash": _values_hash(run_v3),
        "dataset_v4_hash": run_v4.dataset_hash,
        "dataset_v4_run_id": int(v4_run_id),
        "dataset_v4_values_hash": _values_hash(run_v4),
        "date_from": run_v3.date_from.isoformat() if run_v3.date_from else None,
        "date_to": run_v3.date_to.isoformat() if run_v3.date_to else None,
        "fair_contract_status": population.get("fair_contract_status", "PASS"),
        "population": population,
        "sample_identity_match": bool(population.get("sample_identity_match")),
        "schema": schema,
        "target_identity_match": bool(population.get("target_identity_match")),
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
