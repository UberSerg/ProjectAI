"""Batch persistence for relation snapshots and lag metrics."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.analytics.relation_models import (
    RelationInput,
    RelationLagMetric,
    RelationSet,
    RelationSnapshot,
)
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


def load_relation_inputs_by_codes(session: Session, codes: list[str]) -> dict[str, RelationInput]:
    if not codes:
        return {}
    rows = list(session.scalars(select(RelationInput).where(RelationInput.code.in_(codes))))
    return {row.code: row for row in rows}


def load_pinned_relation_set(session: Session, code: str, version: int) -> RelationSet | None:
    return session.scalar(select(RelationSet).where(RelationSet.code == code, RelationSet.version == version))


def load_relation_snapshots_for_join(
    session: Session,
    *,
    relation_set_id: UUID,
    relation_set_version: int,
    pair_ids: list[tuple[UUID, UUID]],
    windows: list[int],
    date_from: date,
    date_to: date,
    lookback_days: int,
) -> list[RelationSnapshot]:
    """Batch-load snapshots for unordered pairs.

    PIT is snapshot.as_of_date (applied in memory: latest as_of <= t).
    RelationRun.source_watermark is compute lineage only and is not used here.
    """
    if not pair_ids:
        return []
    ordered = [(a, b) if a < b else (b, a) for a, b in pair_ids]
    unique_pairs = list({(a, b) for a, b in ordered})
    lower = date_from - timedelta(days=lookback_days)
    # Chunk pair IN lists — deep-history Dataset can request ~40+ instruments × 4 contexts.
    pair_chunk = 80
    out: list[RelationSnapshot] = []
    for offset in range(0, len(unique_pairs), pair_chunk):
        chunk = unique_pairs[offset : offset + pair_chunk]
        stmt = select(RelationSnapshot).where(
            RelationSnapshot.relation_set_id == relation_set_id,
            RelationSnapshot.relation_set_version == relation_set_version,
            RelationSnapshot.window_observations.in_(windows),
            RelationSnapshot.as_of_date <= date_to,
            RelationSnapshot.as_of_date >= lower,
            tuple_(RelationSnapshot.input_a_id, RelationSnapshot.input_b_id).in_(chunk),
        )
        rows = list(session.scalars(stmt))
        for row in rows:
            session.expunge(row)
        out.extend(rows)
    return out


def load_lag_metrics_for_snapshots(
    session: Session,
    snapshot_ids: list[int],
    *,
    lags: list[int] | None = None,
) -> dict[int, list[RelationLagMetric]]:
    """Batch-load lag metrics. Optional ``lags`` filters to Dataset-needed offsets only.

    Chunks IN lists to stay under Postgres bind-parameter limits (~65535).
    """
    if not snapshot_ids:
        return {}
    # Postgres bind limit ~65535; chunk IN lists for deep-history Dataset builds.
    chunk_size = 5_000
    by_snap: dict[int, list[RelationLagMetric]] = {}
    unique_ids = list(dict.fromkeys(snapshot_ids))
    lag_filter = sorted({int(x) for x in lags}) if lags else None
    for offset in range(0, len(unique_ids), chunk_size):
        chunk = unique_ids[offset : offset + chunk_size]
        stmt = select(RelationLagMetric).where(RelationLagMetric.snapshot_id.in_(chunk))
        if lag_filter is not None:
            stmt = stmt.where(RelationLagMetric.lag.in_(lag_filter))
        rows = list(session.scalars(stmt))
        for row in rows:
            by_snap.setdefault(row.snapshot_id, []).append(row)
        # Detach chunk rows so the Session identity map does not retain millions of ORM objects.
        for row in rows:
            session.expunge(row)
    return by_snap
