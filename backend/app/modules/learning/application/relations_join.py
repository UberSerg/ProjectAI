"""In-memory Relations as-of join for Dataset V0."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from app.infrastructure.analytics.relation_models import RelationLagMetric, RelationSnapshot


@dataclass(slots=True)
class RelationPairKey:
    input_low: UUID
    input_high: UUID


def ordered_pair(a: UUID, b: UUID) -> tuple[UUID, UUID]:
    return (a, b) if a < b else (b, a)


@dataclass
class RelationIndex:
    """Snapshots indexed by (input_a, input_b, window) -> sorted (as_of, snapshot, lags)."""

    by_pair_window: dict[tuple[UUID, UUID, int], list[tuple[date, RelationSnapshot, list[RelationLagMetric]]]]

    @classmethod
    def build(
        cls,
        snapshots: list[RelationSnapshot],
        lags_by_snapshot: dict[int, list[RelationLagMetric]],
    ) -> RelationIndex:
        index: dict[tuple[UUID, UUID, int], list[tuple[date, RelationSnapshot, list[RelationLagMetric]]]] = {}
        for snap in snapshots:
            key = (snap.input_a_id, snap.input_b_id, int(snap.window_observations))
            index.setdefault(key, []).append(
                (snap.as_of_date, snap, lags_by_snapshot.get(snap.id, []))
            )
        for key in index:
            index[key].sort(key=lambda x: x[0])
        return cls(by_pair_window=index)

    def as_of(
        self,
        input_a: UUID,
        input_b: UUID,
        window: int,
        as_of: date,
        *,
        max_age_days: int,
    ) -> tuple[RelationSnapshot | None, list[RelationLagMetric], int | None]:
        """Return latest snapshot with as_of_date <= sample as_of and within max age."""
        lo, hi = ordered_pair(input_a, input_b)
        rows = self.by_pair_window.get((lo, hi, window), [])
        chosen: tuple[date, RelationSnapshot, list[RelationLagMetric]] | None = None
        for snap_date, snap, lags in rows:
            if snap_date <= as_of:
                chosen = (snap_date, snap, lags)
            else:
                break
        if chosen is None:
            return None, [], None
        age = (as_of - chosen[0]).days
        if age > max_age_days:
            return None, [], age
        return chosen[1], chosen[2], age


def extract_relation_features(
    *,
    context_key: str,
    subject_input_id: UUID,
    context_input_id: UUID,
    windows: list[int],
    lag_window: int,
    lags: list[int],
    index: RelationIndex,
    as_of: date,
    max_age_days: int,
) -> tuple[dict[str, float | None], dict[str, Any]]:
    """Build relation feature dict + metadata for one context."""
    features: dict[str, float | None] = {}
    meta: dict[str, Any] = {
        "snapshot_ids": {},
        "as_of_dates": {},
        "age_days": None,
        "available": False,
        "reason": None,
    }

    if subject_input_id == context_input_id:
        for w in windows:
            features[f"rel_{context_key}_w{w}_pearson"] = None
            features[f"rel_{context_key}_w{w}_spearman"] = None
            if w == 60:
                features[f"rel_{context_key}_w{w}_rolling_corr_std"] = None
                features[f"rel_{context_key}_w{w}_sign_consistency"] = None
        for lag in lags:
            features[f"rel_{context_key}_subject_leads_lag{lag}_pearson"] = None
            features[f"rel_{context_key}_context_leads_lag{lag}_pearson"] = None
        meta["reason"] = "self_relation"
        return features, meta

    ages: list[int] = []
    any_available = False
    for w in windows:
        snap, lag_rows, age = index.as_of(
            subject_input_id, context_input_id, w, as_of, max_age_days=max_age_days
        )
        if age is not None:
            ages.append(age)
        if snap is None:
            features[f"rel_{context_key}_w{w}_pearson"] = None
            features[f"rel_{context_key}_w{w}_spearman"] = None
            if w == 60:
                features[f"rel_{context_key}_w{w}_rolling_corr_std"] = None
                features[f"rel_{context_key}_w{w}_sign_consistency"] = None
            meta["snapshot_ids"][str(w)] = None
            meta["as_of_dates"][str(w)] = None
            continue
        any_available = True
        meta["snapshot_ids"][str(w)] = snap.id
        meta["as_of_dates"][str(w)] = snap.as_of_date.isoformat()
        features[f"rel_{context_key}_w{w}_pearson"] = float(snap.pearson) if snap.pearson is not None else None
        features[f"rel_{context_key}_w{w}_spearman"] = (
            float(snap.spearman) if snap.spearman is not None else None
        )
        if w == 60:
            features[f"rel_{context_key}_w{w}_rolling_corr_std"] = (
                float(snap.rolling_corr_std) if snap.rolling_corr_std is not None else None
            )
            features[f"rel_{context_key}_w{w}_sign_consistency"] = (
                float(snap.sign_consistency) if snap.sign_consistency is not None else None
            )

        if w == lag_window:
            # Fixed lag profile: subject→context and context→subject
            by_dir: dict[tuple[UUID, UUID, int], RelationLagMetric] = {}
            for lm in lag_rows:
                by_dir[(lm.leader_input_id, lm.follower_input_id, int(lm.lag))] = lm
            for lag in lags:
                subj_lead = by_dir.get((subject_input_id, context_input_id, lag))
                ctx_lead = by_dir.get((context_input_id, subject_input_id, lag))
                features[f"rel_{context_key}_subject_leads_lag{lag}_pearson"] = (
                    float(subj_lead.pearson) if subj_lead and subj_lead.pearson is not None else None
                )
                features[f"rel_{context_key}_context_leads_lag{lag}_pearson"] = (
                    float(ctx_lead.pearson) if ctx_lead and ctx_lead.pearson is not None else None
                )

    # Ensure lag keys exist even if lag_window snapshot missing
    for lag in lags:
        features.setdefault(f"rel_{context_key}_subject_leads_lag{lag}_pearson", None)
        features.setdefault(f"rel_{context_key}_context_leads_lag{lag}_pearson", None)

    meta["available"] = any_available
    meta["age_days"] = min(ages) if ages else None
    if not any_available:
        meta["reason"] = "missing_or_stale"
    return features, meta
