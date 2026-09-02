"""In-memory Relations as-of join for Dataset V0 (PIT, no look-ahead)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from app.infrastructure.analytics.relation_models import RelationLagMetric, RelationSnapshot
from app.modules.learning.dataset_config import relation_feature_names
from app.modules.relations.relation_config import INSTRUMENT_FEATURE_KEY


def instrument_relation_input_code(symbol: str) -> str:
    return f"instrument:{symbol}:{INSTRUMENT_FEATURE_KEY}"


def ordered_pair(a: UUID, b: UUID) -> tuple[UUID, UUID]:
    """Zero-lag snapshots are unordered (input_a_id < input_b_id). Lookup only."""
    return (a, b) if a < b else (b, a)


@dataclass
class RelationIndex:
    """Snapshots indexed by unordered (input_a, input_b, window) -> sorted (as_of, snapshot, lags)."""

    by_pair_window: dict[tuple[UUID, UUID, int], list[tuple[date, RelationSnapshot, list[RelationLagMetric]]]]

    @classmethod
    def build(
        cls,
        snapshots: list[RelationSnapshot],
        lags_by_snapshot: dict[int, list[RelationLagMetric]],
    ) -> RelationIndex:
        index: dict[tuple[UUID, UUID, int], list[tuple[date, RelationSnapshot, list[RelationLagMetric]]]] = {}
        for snap in snapshots:
            lo, hi = ordered_pair(snap.input_a_id, snap.input_b_id)
            key = (lo, hi, int(snap.window_observations))
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
        """Latest snapshot with as_of_date <= sample t and age <= max_age_days.

        PIT key is snapshot.as_of_date, not RelationRun.source_watermark
        (that field is compute lineage only).
        Never selects as_of_date > t. Age exactly max_age_days is allowed.
        Stale (age > max) returns (None, [], age). Missing returns (None, [], None).
        """
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


def _null_context_features(context_key: str, windows: list[int], lags: list[int]) -> dict[str, float | None]:
    features: dict[str, float | None] = {}
    for w in windows:
        features[f"rel_{context_key}_w{w}_pearson"] = None
        features[f"rel_{context_key}_w{w}_spearman"] = None
        if w == 60:
            features[f"rel_{context_key}_w{w}_rolling_corr_std"] = None
            features[f"rel_{context_key}_w{w}_sign_consistency"] = None
    for lag in lags:
        features[f"rel_{context_key}_subject_leads_lag{lag}_pearson"] = None
        features[f"rel_{context_key}_context_leads_lag{lag}_pearson"] = None
    return features


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
    features = _null_context_features(context_key, windows, lags)
    meta: dict[str, Any] = {
        "snapshot_ids": {},
        "as_of_dates": {},
        "age_days": None,
        "available": False,
        "reason": None,
    }

    if subject_input_id == context_input_id:
        meta["reason"] = "self_relation"
        return features, meta

    ages: list[int] = []
    any_available = False
    reasons: list[str] = []
    window_reason: dict[int, str] = {}
    for w in windows:
        snap, lag_rows, age = index.as_of(
            subject_input_id, context_input_id, w, as_of, max_age_days=max_age_days
        )
        if age is not None:
            ages.append(age)
        if snap is None:
            meta["snapshot_ids"][str(w)] = None
            meta["as_of_dates"][str(w)] = None
            reason = "stale" if age is not None and age > max_age_days else "missing"
            reasons.append(reason)
            window_reason[w] = reason
            continue
        if not getattr(snap, "is_valid", True):
            meta["snapshot_ids"][str(w)] = snap.id
            meta["as_of_dates"][str(w)] = snap.as_of_date.isoformat()
            reasons.append("invalid")
            window_reason[w] = "invalid"
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
            # Directional lag: leader(t) vs follower(t+lag). Do not sort the pair.
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

    meta["available"] = any_available
    meta["age_days"] = min(ages) if ages else None
    if not any_available:
        primary = window_reason.get(lag_window) or window_reason.get(60)
        if primary:
            meta["reason"] = primary
        elif reasons and all(r == "stale" for r in reasons):
            meta["reason"] = "stale"
        elif reasons and all(r == "invalid" for r in reasons):
            meta["reason"] = "invalid"
        elif reasons and all(r == "missing" for r in reasons):
            meta["reason"] = "missing"
        else:
            meta["reason"] = "missing_or_stale"
    return features, meta


@dataclass
class RelationJoinResult:
    features: dict[str, float | None]
    available: bool
    age_days: int | None
    as_of_date: date | None
    snapshot_ids: dict[str, int | None]
    as_of_dates: dict[str, str | None]
    context_meta: dict[str, dict[str, Any]]
    expected_feature_count: int
    available_feature_count: int
    expected_context_count: int
    available_context_count: int
    quality_flags: dict[str, Any] = field(default_factory=dict)


def empty_relation_join(contexts: list[dict[str, Any]], *, reason: str) -> RelationJoinResult:
    names = relation_feature_names(contexts)
    features = {name: None for name in names}
    return RelationJoinResult(
        features=features,
        available=False,
        age_days=None,
        as_of_date=None,
        snapshot_ids={},
        as_of_dates={},
        context_meta={ctx["key"]: {"available": False, "reason": reason} for ctx in contexts},
        expected_feature_count=len(names),
        available_feature_count=0,
        expected_context_count=len(contexts),
        available_context_count=0,
        quality_flags={"relations_join": reason},
    )


def extract_all_relation_features(
    *,
    contexts: list[dict[str, Any]],
    subject_input_id: UUID | None,
    context_input_ids: dict[str, UUID | None],
    index: RelationIndex,
    as_of: date,
    max_age_days: int,
) -> RelationJoinResult:
    """Join all pinned contexts for one sample. Missing/stale/self → NULL, never 0."""
    if subject_input_id is None:
        return empty_relation_join(contexts, reason="missing_subject_input")

    features: dict[str, float | None] = {}
    context_meta: dict[str, dict[str, Any]] = {}
    snapshot_ids: dict[str, int | None] = {}
    as_of_dates: dict[str, str | None] = {}
    ages: list[int] = []
    used_as_ofs: list[date] = []
    available_contexts = 0

    for ctx in contexts:
        key = ctx["key"]
        context_id = context_input_ids.get(key)
        windows = list(ctx.get("windows", [20, 60, 120]))
        lags = list(ctx.get("lags", [1, 2, 3, 4, 5]))
        lag_window = int(ctx.get("lag_window", 60))
        if context_id is None:
            feats = _null_context_features(key, windows, lags)
            meta = {
                "available": False,
                "reason": "missing_context_input",
                "snapshot_ids": {},
                "as_of_dates": {},
                "age_days": None,
            }
        else:
            feats, meta = extract_relation_features(
                context_key=key,
                subject_input_id=subject_input_id,
                context_input_id=context_id,
                windows=windows,
                lag_window=lag_window,
                lags=lags,
                index=index,
                as_of=as_of,
                max_age_days=max_age_days,
            )
        features.update(feats)
        context_meta[key] = meta
        if meta.get("available"):
            available_contexts += 1
        if meta.get("age_days") is not None:
            ages.append(int(meta["age_days"]))
        for w, sid in (meta.get("snapshot_ids") or {}).items():
            snapshot_ids[f"{key}_w{w}"] = sid
        for w, as_of_s in (meta.get("as_of_dates") or {}).items():
            as_of_dates[f"{key}_w{w}"] = as_of_s
            if as_of_s:
                used_as_ofs.append(date.fromisoformat(as_of_s) if isinstance(as_of_s, str) else as_of_s)

    available_features = sum(1 for value in features.values() if value is not None)
    return RelationJoinResult(
        features=features,
        available=available_contexts > 0,
        age_days=min(ages) if ages else None,
        as_of_date=max(used_as_ofs) if used_as_ofs else None,
        snapshot_ids=snapshot_ids,
        as_of_dates=as_of_dates,
        context_meta=context_meta,
        expected_feature_count=len(features),
        available_feature_count=available_features,
        expected_context_count=len(contexts),
        available_context_count=available_contexts,
        quality_flags={
            "relations_join": "enabled",
            "relation_context_reasons": {k: v.get("reason") for k, v in context_meta.items()},
        },
    )
