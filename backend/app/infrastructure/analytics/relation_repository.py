"""Batch persistence for relation snapshots and lag metrics."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.analytics.relation_models import RelationLagMetric, RelationSnapshot
from app.modules.relations.application.calculator import PairRelationResult

# Chunk sizes tuned for Postgres parameter limits (~65k).
_SNAPSHOT_CHUNK = 400
_LAG_CHUNK = 2000


def _dec(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(value, 8)))


def persist_pair_results(
    session: Session,
    *,
    relation_run_id: int,
    relation_set_id: UUID,
    relation_set_version: int,
    results: list[PairRelationResult],
) -> dict[str, int]:
    """Bulk upsert snapshots and replace lag metrics (no per-row round-trips)."""
    if not results:
        return {"written": 0, "valid": 0, "invalid": 0, "lags": 0}

    now = datetime.now()
    written = 0
    valid = sum(1 for r in results if r.is_valid)
    invalid = len(results) - valid
    lags = 0

    for offset in range(0, len(results), _SNAPSHOT_CHUNK):
        chunk = results[offset : offset + _SNAPSHOT_CHUNK]
        rows: list[dict[str, Any]] = []
        for rec in chunk:
            rows.append(
                {
                    "relation_run_id": relation_run_id,
                    "relation_set_id": relation_set_id,
                    "relation_set_version": relation_set_version,
                    "as_of_date": rec.as_of_date,
                    "window_observations": rec.window_observations,
                    "input_a_id": rec.input_a_id,
                    "input_b_id": rec.input_b_id,
                    "sample_count": rec.sample_count,
                    "coverage_ratio": _dec(rec.coverage_ratio),
                    "pearson": _dec(rec.pearson),
                    "spearman": _dec(rec.spearman),
                    "rolling_corr_mean": _dec(rec.rolling_corr_mean),
                    "rolling_corr_std": _dec(rec.rolling_corr_std),
                    "sign_consistency": _dec(rec.sign_consistency),
                    "best_leader_input_id": rec.best_leader_input_id,
                    "best_follower_input_id": rec.best_follower_input_id,
                    "best_lag": rec.best_lag,
                    "best_lag_pearson": _dec(rec.best_lag_pearson),
                    "best_lag_spearman": _dec(rec.best_lag_spearman),
                    "is_valid": rec.is_valid,
                    "quality_flags": rec.quality_flags or {},
                    "calculated_at": now,
                }
            )

        stmt = insert(RelationSnapshot).values(rows)
        upsert = stmt.on_conflict_do_update(
            constraint="uq_analytics_relation_snapshots_pair",
            set_={
                "relation_run_id": stmt.excluded.relation_run_id,
                "relation_set_version": stmt.excluded.relation_set_version,
                "sample_count": stmt.excluded.sample_count,
                "coverage_ratio": stmt.excluded.coverage_ratio,
                "pearson": stmt.excluded.pearson,
                "spearman": stmt.excluded.spearman,
                "rolling_corr_mean": stmt.excluded.rolling_corr_mean,
                "rolling_corr_std": stmt.excluded.rolling_corr_std,
                "sign_consistency": stmt.excluded.sign_consistency,
                "best_leader_input_id": stmt.excluded.best_leader_input_id,
                "best_follower_input_id": stmt.excluded.best_follower_input_id,
                "best_lag": stmt.excluded.best_lag,
                "best_lag_pearson": stmt.excluded.best_lag_pearson,
                "best_lag_spearman": stmt.excluded.best_lag_spearman,
                "is_valid": stmt.excluded.is_valid,
                "quality_flags": stmt.excluded.quality_flags,
                "calculated_at": stmt.excluded.calculated_at,
            },
        )
        session.execute(upsert)
        written += len(rows)

        # Resolve snapshot ids for this chunk via unique key lookup (one query).
        key_tuples = [
            (relation_set_id, rec.as_of_date, rec.window_observations, rec.input_a_id, rec.input_b_id)
            for rec in chunk
        ]
        id_rows = session.execute(
            select(
                RelationSnapshot.id,
                RelationSnapshot.as_of_date,
                RelationSnapshot.window_observations,
                RelationSnapshot.input_a_id,
                RelationSnapshot.input_b_id,
            ).where(
                tuple_(
                    RelationSnapshot.relation_set_id,
                    RelationSnapshot.as_of_date,
                    RelationSnapshot.window_observations,
                    RelationSnapshot.input_a_id,
                    RelationSnapshot.input_b_id,
                ).in_(key_tuples)
            )
        ).all()
        id_map = {
            (r.as_of_date, r.window_observations, r.input_a_id, r.input_b_id): r.id for r in id_rows
        }

        snapshot_ids = list(id_map.values())
        if snapshot_ids:
            session.execute(
                delete(RelationLagMetric).where(RelationLagMetric.snapshot_id.in_(snapshot_ids))
            )

        lag_rows: list[dict[str, Any]] = []
        for rec in chunk:
            sid = id_map.get((rec.as_of_date, rec.window_observations, rec.input_a_id, rec.input_b_id))
            if sid is None or not rec.lag_metrics:
                continue
            for lag in rec.lag_metrics:
                lag_rows.append(
                    {
                        "snapshot_id": sid,
                        "leader_input_id": lag.leader_input_id,
                        "follower_input_id": lag.follower_input_id,
                        "lag": lag.lag,
                        "pearson": _dec(lag.pearson),
                        "spearman": _dec(lag.spearman),
                        "sample_count": lag.sample_count,
                        "coverage_ratio": _dec(lag.coverage_ratio),
                    }
                )

        for lag_offset in range(0, len(lag_rows), _LAG_CHUNK):
            lag_chunk = lag_rows[lag_offset : lag_offset + _LAG_CHUNK]
            if lag_chunk:
                session.execute(insert(RelationLagMetric).values(lag_chunk))
        lags += len(lag_rows)

    return {"written": written, "valid": valid, "invalid": invalid, "lags": lags}
