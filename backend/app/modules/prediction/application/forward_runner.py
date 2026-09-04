"""Forward Signal V0 orchestration — live PIT inference, immutable persistence."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.modules.prediction.application.forward_artifact import (
    ForwardArtifactError,
    load_frozen_candidate_v0,
)
from app.modules.prediction.application.forward_assembler import assemble_forward_rows, rows_to_matrix
from app.modules.prediction.application.forward_config import (
    EXPECTED_CANDIDATE_CONFIG_HASH,
    EXPECTED_FEATURE_COUNT,
    EXPECTED_FEATURE_SCHEMA_HASH,
    FORWARD_BASIC_FS_CODE,
    FORWARD_BASIC_FS_VERSION,
    FORWARD_RELATION_SET_CODE,
    FORWARD_RELATION_SET_VERSION,
    FORWARD_SEGMENT,
    FORWARD_TECH_FS_CODE,
    FORWARD_TECH_FS_VERSION,
    FORWARD_TECH_MODEL_CODE,
    FORWARD_TECH_MODEL_VERSION,
    OUTCOME_PENDING,
)
from app.modules.prediction.application.forward_readiness import (
    check_upstream_readiness,
    select_latest_complete_as_of,
)
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG, CandidateV0Config
from app.modules.prediction.infrastructure import forward_repository as repo
from app.modules.prediction.infrastructure.forward_models import ForwardPredictionBatch


@dataclass
class ForwardRunResult:
    status: str
    batch_id: int | None
    as_of: date | None
    summary: dict[str, Any]


def _rank_predictions(
    preds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered = sorted(
        preds,
        key=lambda r: (-float(r["predicted_return_20d"]), int(r["instrument_id"])),
    )
    n = len(ordered)
    for i, row in enumerate(ordered, start=1):
        row["rank"] = i
        row["eligible_count"] = n
        row["percentile"] = (n - i + 1) / n if n else None
    return ordered


def _distribution(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "std": None, "min": None, "max": None}
    arr = np.asarray(values, dtype=float)
    return {
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "std": float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
    }


def run_forward_signal_v0(
    session: Session,
    *,
    as_of: date | None = None,
    config: CandidateV0Config = CANDIDATE_V0_CONFIG,
    artifact_root: Path | None = None,
    persist: bool = True,
) -> ForwardRunResult:
    """Build immutable FORWARD_LIVE predictions for latest complete as_of (or explicit date).

    Never retrains. Never overwrites frozen predictions. Never builds full Dataset history.
    """
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    # --- Artifact ---
    t_art = time.perf_counter()
    try:
        loaded = load_frozen_candidate_v0(config=config, root=artifact_root)
    except ForwardArtifactError as exc:
        return ForwardRunResult(
            status="ERROR",
            batch_id=None,
            as_of=None,
            summary={"error": str(exc), "stage": "artifact"},
        )
    timings["artifact_load_sec"] = round(time.perf_counter() - t_art, 3)

    # --- As-of / completeness ---
    t_ready = time.perf_counter()
    if as_of is None:
        completeness = select_latest_complete_as_of(session)
        if not completeness.complete or completeness.as_of is None:
            timings["readiness_sec"] = round(time.perf_counter() - t_ready, 3)
            return ForwardRunResult(
                status="WARNING",
                batch_id=None,
                as_of=None,
                summary={
                    "error": "market_incomplete",
                    "completeness": completeness.to_dict(),
                    "note": "No partial batch published",
                },
            )
        as_of_date = completeness.as_of
    else:
        completeness = select_latest_complete_as_of(session)
        # Explicit as_of: still report completeness for that date via recompute path
        as_of_date = as_of
        # Build a lightweight completeness for explicit date
        from app.modules.prediction.application.forward_readiness import CompletenessReport

        completeness = CompletenessReport(
            as_of=as_of_date,
            latest_raw_market_date=completeness.latest_raw_market_date,
            expected_instruments=completeness.expected_instruments,
            available_instruments=completeness.available_instruments,
            missing_instrument_ids=completeness.missing_instrument_ids,
            ratio=completeness.ratio,
            threshold=completeness.threshold,
            complete=True,
            reason="explicit_as_of",
        )

    upstream = check_upstream_readiness(session, as_of_date)
    timings["readiness_sec"] = round(time.perf_counter() - t_ready, 3)
    if not upstream.ready:
        return ForwardRunResult(
            status="WARNING",
            batch_id=None,
            as_of=as_of_date,
            summary={
                "error": "upstream_incomplete",
                "completeness": completeness.to_dict(),
                "upstream": upstream.to_dict(),
                "note": "No partial batch published",
            },
        )

    # --- Idempotency: existing frozen predictions ---
    existing = repo.get_existing_predictions(
        session,
        candidate_config_hash=loaded.config_hash,
        as_of_date=as_of_date,
    )
    if existing:
        # Rebuild expected hash from frozen rows
        frozen_rows = [
            {
                "as_of_date": e.as_of_date.isoformat(),
                "instrument_id": e.instrument_id,
                "predicted_return_20d": e.predicted_return_20d,
                "rank": e.rank or 0,
            }
            for e in existing
        ]
        pred_hash = repo.batch_prediction_hash(frozen_rows, config_hash=loaded.config_hash)
        existing_batch = session.get(ForwardPredictionBatch, existing[0].batch_id)
        return ForwardRunResult(
            status="NO_CHANGES",
            batch_id=existing_batch.id if existing_batch else existing[0].batch_id,
            as_of=as_of_date,
            summary={
                "message": "predictions already frozen for as_of",
                "prediction_count": len(existing),
                "prediction_hash": pred_hash,
                "immutable": True,
                "rows_inserted": 0,
                "rows_overwritten": 0,
                "completeness": completeness.to_dict(),
                "upstream": upstream.to_dict(),
                "candidate_config_hash": loaded.config_hash,
                "feature_schema_hash": loaded.feature_schema_hash,
                "segment": FORWARD_SEGMENT,
            },
        )

    # --- Assemble features ---
    t_asm = time.perf_counter()
    assembled = assemble_forward_rows(session, as_of=as_of_date, config=config)
    timings["feature_assembly_sec"] = round(time.perf_counter() - t_asm, 3)

    pit_violations = [r for r in assembled if not r.pit_ok]
    if pit_violations:
        return ForwardRunResult(
            status="ERROR",
            batch_id=None,
            as_of=as_of_date,
            summary={
                "error": "pit_violation",
                "violations": [
                    {"instrument_id": r.instrument_id, "issues": r.pit_violations}
                    for r in pit_violations[:20]
                ],
            },
        )

    eligible_rows = [r for r in assembled if r.eligible]
    ineligible_rows = [r for r in assembled if not r.eligible]
    if not eligible_rows:
        return ForwardRunResult(
            status="WARNING",
            batch_id=None,
            as_of=as_of_date,
            summary={
                "error": "no_eligible_instruments",
                "instrument_count": len(assembled),
                "ineligible_count": len(ineligible_rows),
                "ineligible_reasons": {
                    r.ticker: r.ineligible_reason for r in ineligible_rows[:20]
                },
            },
        )

    # Schema guard
    for r in eligible_rows:
        if list(r.features.keys()) != list(config.feature_names):
            return ForwardRunResult(
                status="ERROR",
                batch_id=None,
                as_of=as_of_date,
                summary={"error": "feature_order_mismatch", "instrument_id": r.instrument_id},
            )

    # --- Inference (no fit) ---
    t_inf = time.perf_counter()
    matrix = rows_to_matrix(eligible_rows, config=config)
    if matrix.shape[1] != EXPECTED_FEATURE_COUNT:
        return ForwardRunResult(
            status="ERROR",
            batch_id=None,
            as_of=as_of_date,
            summary={"error": "matrix_width_mismatch", "width": int(matrix.shape[1])},
        )
    y_pred = loaded.adapter.predict_many(matrix)
    timings["inference_sec"] = round(time.perf_counter() - t_inf, 3)

    generated_at = datetime.now(UTC)
    pred_rows: list[dict[str, Any]] = []
    for row, pred in zip(eligible_rows, y_pred, strict=True):
        pred_rows.append(
            {
                "as_of_date": as_of_date,
                "instrument_id": row.instrument_id,
                "ticker": row.ticker,
                "predicted_return_20d": float(pred),
                "candidate_config_hash": loaded.config_hash,
                "feature_schema_hash": loaded.feature_schema_hash,
                "input_lineage": row.lineage,
                "quality_status": "OK",
                "segment": FORWARD_SEGMENT,
                "outcome_status": OUTCOME_PENDING,
                "generated_at": generated_at,
            }
        )
    ranked = _rank_predictions(pred_rows)
    hash_rows = [
        {
            "as_of_date": as_of_date.isoformat(),
            "instrument_id": r["instrument_id"],
            "predicted_return_20d": r["predicted_return_20d"],
            "rank": r["rank"],
        }
        for r in ranked
    ]
    pred_hash = repo.batch_prediction_hash(hash_rows, config_hash=loaded.config_hash)

    input_lineage = {
        "pins": {
            "analytics": f"{FORWARD_BASIC_FS_CODE} v{FORWARD_BASIC_FS_VERSION}",
            "technical": f"{FORWARD_TECH_FS_CODE} v{FORWARD_TECH_FS_VERSION}",
            "rules": f"{FORWARD_TECH_MODEL_CODE} v{FORWARD_TECH_MODEL_VERSION}",
            "relations": f"{FORWARD_RELATION_SET_CODE} v{FORWARD_RELATION_SET_VERSION}",
            "candidate": f"{config.candidate_name}/{config.candidate_version}",
            "candidate_config_hash": loaded.config_hash,
            "feature_schema_hash": loaded.feature_schema_hash,
            "dataset_values_hash": loaded.dataset_values_hash,
        },
        "artifact_dir": str(loaded.artifact_dir),
        "completeness": completeness.to_dict(),
        "upstream": upstream.to_dict(),
    }
    input_lineage_hash = repo.lineage_hash(input_lineage)

    values = [float(r["predicted_return_20d"]) for r in ranked]
    dist = _distribution(values)
    top10 = [
        {
            "rank": r["rank"],
            "instrument_id": r["instrument_id"],
            "ticker": r["ticker"],
            "predicted_return_20d": r["predicted_return_20d"],
        }
        for r in ranked[:10]
    ]
    bottom5 = [
        {
            "rank": r["rank"],
            "instrument_id": r["instrument_id"],
            "ticker": r["ticker"],
            "predicted_return_20d": r["predicted_return_20d"],
        }
        for r in ranked[-5:]
    ]

    batch_id = None
    inserted = 0
    notes: list[str] = []
    if persist:
        t_pers = time.perf_counter()
        batch = repo.create_batch(
            session,
            as_of_date=as_of_date,
            candidate_name=config.candidate_name,
            candidate_version=config.candidate_version,
            candidate_config_hash=loaded.config_hash,
            feature_schema_hash=loaded.feature_schema_hash,
            dataset_values_hash=loaded.dataset_values_hash,
            segment=FORWARD_SEGMENT,
        )
        inserted, notes = repo.insert_predictions_immutable(session, batch=batch, rows=ranked)
        batch.status = "SUCCESS"
        batch.instrument_count = len(assembled)
        batch.eligible_count = len(eligible_rows)
        batch.ineligible_count = len(ineligible_rows)
        batch.prediction_count = inserted
        batch.input_lineage = input_lineage
        batch.input_lineage_hash = input_lineage_hash
        batch.prediction_hash = pred_hash
        batch.pit_status = "PASSED"
        batch.completeness = completeness.to_dict()
        batch.timings = timings
        batch.generated_at = generated_at
        batch.completed_at = datetime.now(UTC)
        session.flush()
        batch_id = batch.id
        timings["persist_sec"] = round(time.perf_counter() - t_pers, 3)

    timings["total_sec"] = round(time.perf_counter() - t0, 3)
    return ForwardRunResult(
        status="SUCCESS",
        batch_id=batch_id,
        as_of=as_of_date,
        summary={
            "batch_id": batch_id,
            "as_of": as_of_date.isoformat(),
            "generated_at": generated_at.isoformat(),
            "segment": FORWARD_SEGMENT,
            "candidate_name": config.candidate_name,
            "candidate_version": config.candidate_version,
            "candidate_config_hash": loaded.config_hash,
            "feature_schema_hash": loaded.feature_schema_hash,
            "feature_count": EXPECTED_FEATURE_COUNT,
            "expected_config_hash": EXPECTED_CANDIDATE_CONFIG_HASH,
            "expected_feature_schema_hash": EXPECTED_FEATURE_SCHEMA_HASH,
            "instrument_count": len(assembled),
            "eligible_count": len(eligible_rows),
            "ineligible_count": len(ineligible_rows),
            "prediction_count": len(ranked) if not persist else inserted,
            "prediction_hash": pred_hash,
            "input_lineage_hash": input_lineage_hash,
            "pit_status": "PASSED",
            "distribution": dist,
            "top10": top10,
            "bottom5": bottom5,
            "completeness": completeness.to_dict(),
            "upstream": upstream.to_dict(),
            "timings": timings,
            "immutable": True,
            "rows_inserted": inserted,
            "rows_overwritten": 0,
            "notes": notes,
            "outcome_status": OUTCOME_PENDING,
            "model_retrained": False,
        },
    )
