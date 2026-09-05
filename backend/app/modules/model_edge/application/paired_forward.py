"""Run Candidate V0 and Candidate V1 Ranker on one shared PIT feature snapshot.

Both sides see the exact same as_of, the same assembled X rows and the same eligibility
decision, so any difference in the resulting portfolios is attributable to the model.
A failure on one side never discards the other side's frozen predictions.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.model_edge.application.experiment import (
    activation_watermark,
    candidate_a_ref,
    candidate_b_ref,
    latest_raw_market_date,
    require_experiment,
)
from app.modules.model_edge.config import (
    DIAGNOSTICS_OVERLAP_TOP_N,
    FULL_COMPARABILITY_MIN_OVERLAP,
    FULLY_COMPARABLE,
    NOT_COMPARABLE,
    PARTIAL_COMPARABILITY_MIN_OVERLAP,
    PARTIALLY_COMPARABLE,
    STATUS_ACTIVE,
)
from app.modules.model_edge.domain.types import (
    CandidateRef,
    PairedComparison,
    ProspectiveExperimentError,
    SideRunSummary,
)
from app.modules.model_edge.infrastructure.models import (
    ProspectiveModelComparisonBatch,
    ProspectiveModelExperiment,
)
from app.modules.prediction.application.forward_artifact import (
    LoadedForwardModel,
    load_frozen_candidate_v0,
    load_frozen_candidate_v1_ranker,
)
from app.modules.prediction.application.forward_assembler import (
    AssembledRow,
    assemble_forward_rows,
)
from app.modules.prediction.application.forward_readiness import select_latest_complete_as_of
from app.modules.prediction.application.forward_runner import run_forward_for_loaded_model
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
from app.modules.prediction.infrastructure.forward_models import ForwardPrediction


@dataclass
class PairedForwardResult:
    status: str
    as_of: date | None
    comparison_batch_id: int | None
    side_a: SideRunSummary | None = None
    side_b: SideRunSummary | None = None
    comparison: PairedComparison | None = None
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "comparison_batch_id": self.comparison_batch_id,
            "side_a": self.side_a.to_dict() if self.side_a else None,
            "side_b": self.side_b.to_dict() if self.side_b else None,
            "comparison": self.comparison.to_dict() if self.comparison else None,
            **self.summary,
        }


def feature_snapshot_hash(rows: list[AssembledRow]) -> str:
    """Deterministic fingerprint of the exact X matrix both candidates consumed."""
    lines: list[str] = []
    for row in sorted(rows, key=lambda r: int(r.instrument_id)):
        if not row.eligible:
            continue
        values = ",".join(
            "nan" if row.features.get(name) is None else f"{float(row.features[name]):.12g}"
            for name in CANDIDATE_V0_CONFIG.feature_names
        )
        lines.append(f"{row.as_of_date.isoformat()},{row.instrument_id},{values}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _spearman(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 2:
        return None
    ra = _average_ranks(a)
    rb = _average_ranks(b)
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    denom = float(np.sqrt((ra * ra).sum() * (rb * rb).sum()))
    if denom <= 0:
        return None
    return float((ra * rb).sum() / denom)


def _average_ranks(values: list[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    order = np.argsort(arr, kind="stable")
    ranks = np.empty(len(arr), dtype=float)
    i = 0
    while i < len(arr):
        j = i
        while j + 1 < len(arr) and arr[order[j + 1]] == arr[order[i]]:
            j += 1
        avg = 0.5 * (i + j) + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _predictions_by_instrument(
    session: Session, batch_id: int
) -> dict[int, ForwardPrediction]:
    rows = session.scalars(
        select(ForwardPrediction).where(ForwardPrediction.batch_id == batch_id)
    ).all()
    return {int(r.instrument_id): r for r in rows}


def compare_sides(
    session: Session,
    *,
    as_of: date,
    batch_a_id: int | None,
    batch_b_id: int | None,
    top_n: int = DIAGNOSTICS_OVERLAP_TOP_N,
) -> PairedComparison:
    """Agreement diagnostics on the instruments both candidates actually scored."""
    notes: list[str] = []
    if batch_a_id is None or batch_b_id is None:
        missing = "A" if batch_a_id is None else "B"
        notes.append(f"side_{missing.lower()}_missing")
        rows_a = _predictions_by_instrument(session, batch_a_id) if batch_a_id else {}
        rows_b = _predictions_by_instrument(session, batch_b_id) if batch_b_id else {}
        return PairedComparison(
            as_of=as_of,
            eligible_a=len(rows_a),
            eligible_b=len(rows_b),
            common_eligible=0,
            comparability_status=NOT_COMPARABLE,
            rank_correlation=None,
            top20_overlap=None,
            notes=notes,
        )

    rows_a = _predictions_by_instrument(session, batch_a_id)
    rows_b = _predictions_by_instrument(session, batch_b_id)
    common = sorted(set(rows_a) & set(rows_b))
    union = set(rows_a) | set(rows_b)
    overlap_share = (len(common) / len(union)) if union else 0.0

    if not common:
        status = NOT_COMPARABLE
    elif overlap_share >= FULL_COMPARABILITY_MIN_OVERLAP:
        status = FULLY_COMPARABLE
    elif overlap_share >= PARTIAL_COMPARABILITY_MIN_OVERLAP:
        status = PARTIALLY_COMPARABLE
        notes.append(f"eligible_set_overlap={overlap_share:.4f}")
    else:
        status = NOT_COMPARABLE
        notes.append(f"eligible_set_overlap={overlap_share:.4f}")

    rank_corr = None
    top_overlap = None
    if len(common) >= 2:
        # V0 stores an expected return, V1 a ranking score; both are compared as ranks
        # only, never as values.
        scores_a = [float(rows_a[i].predicted_return_20d) for i in common]
        scores_b = [float(rows_b[i].predicted_return_20d) for i in common]
        rank_corr = _spearman(scores_a, scores_b)
        k = min(top_n, len(common))
        top_a = {
            i for i, _ in sorted(
                ((i, s) for i, s in zip(common, scores_a, strict=True)),
                key=lambda p: (-p[1], p[0]),
            )[:k]
        }
        top_b = {
            i for i, _ in sorted(
                ((i, s) for i, s in zip(common, scores_b, strict=True)),
                key=lambda p: (-p[1], p[0]),
            )[:k]
        }
        top_overlap = len(top_a & top_b) / k if k else None

    return PairedComparison(
        as_of=as_of,
        eligible_a=len(rows_a),
        eligible_b=len(rows_b),
        common_eligible=len(common),
        comparability_status=status,
        rank_correlation=rank_corr,
        top20_overlap=top_overlap,
        notes=notes,
    )


def _run_side(
    session: Session,
    *,
    candidate: CandidateRef,
    loaded: LoadedForwardModel,
    as_of: date,
    assembled: list[AssembledRow],
    persist: bool,
) -> SideRunSummary:
    try:
        result = run_forward_for_loaded_model(
            session,
            loaded=loaded,
            feature_config=CANDIDATE_V0_CONFIG,
            as_of=as_of,
            persist=persist,
            assembled_rows=assembled,
        )
    except Exception as exc:  # noqa: BLE001 — one side must never break the other
        return SideRunSummary(
            candidate=candidate,
            status="ERROR",
            batch_id=None,
            eligible_count=0,
            prediction_count=0,
            feature_schema_hash=loaded.feature_schema_hash,
            error=str(exc)[:2000],
        )
    summary = result.summary or {}
    return SideRunSummary(
        candidate=candidate,
        status=result.status,
        batch_id=result.batch_id,
        eligible_count=int(summary.get("eligible_count") or 0),
        prediction_count=int(summary.get("prediction_count") or 0),
        feature_schema_hash=loaded.feature_schema_hash,
        error=str(summary.get("error")) if summary.get("error") else None,
        summary=summary,
    )


def _upsert_comparison_batch(
    session: Session,
    *,
    experiment: ProspectiveModelExperiment,
    as_of: date,
    values: dict[str, Any],
) -> ProspectiveModelComparisonBatch:
    row = session.scalar(
        select(ProspectiveModelComparisonBatch).where(
            ProspectiveModelComparisonBatch.experiment_id == experiment.id,
            ProspectiveModelComparisonBatch.as_of_date == as_of,
        )
    )
    if row is None:
        row = ProspectiveModelComparisonBatch(
            experiment_id=experiment.id, as_of_date=as_of, **values
        )
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()
    return row


def run_paired_forward(
    session: Session,
    *,
    as_of: date | None = None,
    artifact_root: Path | None = None,
    persist: bool = True,
    now: datetime | None = None,
) -> PairedForwardResult:
    """Score one as_of with both candidates and persist the comparison batch."""
    started = time.perf_counter()
    moment = now or datetime.now(UTC)
    experiment = require_experiment(session)
    if experiment.status != STATUS_ACTIVE:
        raise ProspectiveExperimentError(
            f"{experiment.code} status is {experiment.status}; activate it first"
        )

    if as_of is None:
        completeness = select_latest_complete_as_of(session)
        if not completeness.complete or completeness.as_of is None:
            return PairedForwardResult(
                status="WARNING",
                as_of=None,
                comparison_batch_id=None,
                summary={
                    "reason": "market_incomplete",
                    "completeness": completeness.to_dict(),
                },
            )
        as_of_date = completeness.as_of
    else:
        as_of_date = as_of

    watermark = activation_watermark(experiment)
    if not watermark.allows(as_of_date):
        return PairedForwardResult(
            status="SKIPPED_NOT_PROSPECTIVE",
            as_of=as_of_date,
            comparison_batch_id=None,
            summary={
                "reason": "as_of_not_after_activation_watermark",
                "activation_market_watermark": (
                    watermark.market_watermark.isoformat()
                    if watermark.market_watermark
                    else None
                ),
                "historical_backfill": False,
            },
        )

    existing = session.scalar(
        select(ProspectiveModelComparisonBatch).where(
            ProspectiveModelComparisonBatch.experiment_id == experiment.id,
            ProspectiveModelComparisonBatch.as_of_date == as_of_date,
        )
    )
    if existing is not None and existing.status in {"SUCCESS", "PARTIAL", "NO_CHANGES"}:
        # Immutable: never overwrite a persisted paired comparison for the same as_of.
        return PairedForwardResult(
            status="NO_CHANGES",
            as_of=as_of_date,
            comparison_batch_id=existing.id,
            comparison=PairedComparison(
                as_of=as_of_date,
                eligible_a=existing.eligible_a,
                eligible_b=existing.eligible_b,
                common_eligible=existing.common_eligible,
                comparability_status=existing.comparability_status,  # type: ignore[arg-type]
                rank_correlation=existing.rank_correlation,
                top20_overlap=existing.top20_overlap,
            ),
            summary={
                "immutable": True,
                "feature_snapshot_hash": existing.feature_snapshot_hash,
                "historical_backfill": False,
            },
        )

    a_ref, b_ref = candidate_a_ref(), candidate_b_ref()
    load_errors: dict[str, str] = {}
    loaded_a: LoadedForwardModel | None = None
    loaded_b: LoadedForwardModel | None = None
    try:
        loaded_a = load_frozen_candidate_v0(root=artifact_root)
    except Exception as exc:  # noqa: BLE001 — a missing V1 artifact must not block V0
        load_errors["a"] = str(exc)[:2000]
    try:
        loaded_b = load_frozen_candidate_v1_ranker(root=artifact_root)
    except Exception as exc:  # noqa: BLE001 — and vice versa
        load_errors["b"] = str(exc)[:2000]

    if loaded_a is None and loaded_b is None:
        return PairedForwardResult(
            status="ERROR",
            as_of=as_of_date,
            comparison_batch_id=None,
            summary={"reason": "no_candidate_artifacts", "errors": load_errors},
        )

    assembled = assemble_forward_rows(session, as_of=as_of_date, config=CANDIDATE_V0_CONFIG)
    snapshot_hash = feature_snapshot_hash(assembled)

    side_a = (
        _run_side(
            session,
            candidate=a_ref,
            loaded=loaded_a,
            as_of=as_of_date,
            assembled=assembled,
            persist=persist,
        )
        if loaded_a is not None
        else SideRunSummary(
            candidate=a_ref,
            status="ERROR",
            batch_id=None,
            eligible_count=0,
            prediction_count=0,
            feature_schema_hash=None,
            error=load_errors.get("a"),
        )
    )
    side_b = (
        _run_side(
            session,
            candidate=b_ref,
            loaded=loaded_b,
            as_of=as_of_date,
            assembled=assembled,
            persist=persist,
        )
        if loaded_b is not None
        else SideRunSummary(
            candidate=b_ref,
            status="ERROR",
            batch_id=None,
            eligible_count=0,
            prediction_count=0,
            feature_schema_hash=None,
            error=load_errors.get("b"),
        )
    )

    comparison = compare_sides(
        session,
        as_of=as_of_date,
        batch_a_id=side_a.batch_id if side_a.ok else None,
        batch_b_id=side_b.batch_id if side_b.ok else None,
    )

    if side_a.ok and side_b.ok:
        status = "SUCCESS"
    elif side_a.ok or side_b.ok:
        status = "PARTIAL"
    else:
        status = "ERROR"

    batch_id = None
    if persist:
        errors = [
            f"A: {side_a.error}" if side_a.error else "",
            f"B: {side_b.error}" if side_b.error else "",
        ]
        error_message = "; ".join(e for e in errors if e) or None
        row = _upsert_comparison_batch(
            session,
            experiment=experiment,
            as_of=as_of_date,
            values={
                "generated_at": moment,
                "market_watermark": latest_raw_market_date(session),
                "feature_snapshot_hash": snapshot_hash,
                "feature_schema_hash": side_a.feature_schema_hash
                or side_b.feature_schema_hash,
                "candidate_a_batch_id": side_a.batch_id,
                "candidate_b_batch_id": side_b.batch_id,
                "eligible_a": comparison.eligible_a,
                "eligible_b": comparison.eligible_b,
                "common_eligible": comparison.common_eligible,
                "comparability_status": comparison.comparability_status,
                "rank_correlation": comparison.rank_correlation,
                "top20_overlap": comparison.top20_overlap,
                "status": status,
                "error_message": error_message,
                "summary": {
                    "side_a": side_a.to_dict(),
                    "side_b": side_b.to_dict(),
                    "notes": comparison.notes,
                    "duration_seconds": round(time.perf_counter() - started, 3),
                },
            },
        )
        batch_id = row.id
        if experiment.first_eligible_market_date is None:
            experiment.first_eligible_market_date = as_of_date
        experiment.updated_at = moment
        session.flush()

    return PairedForwardResult(
        status=status,
        as_of=as_of_date,
        comparison_batch_id=batch_id,
        side_a=side_a,
        side_b=side_b,
        comparison=comparison,
        summary={
            "feature_snapshot_hash": snapshot_hash,
            "shared_feature_snapshot": True,
            "historical_backfill": False,
            "duration_seconds": round(time.perf_counter() - started, 3),
        },
    )
