"""Research-only helpers for Dataset V2 vs V3 evaluation (coverage, not alpha)."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetRun, DatasetSampleDaily, DatasetSpec
from app.infrastructure.market.models import Instrument
from app.modules.learning.dataset_config import (
    PIT_DAILY_CORE_CODE,
    PIT_DAILY_CORE_V2,
    PIT_DAILY_CORE_V3,
    feature_names_from_manifest,
    label_names_from_manifest,
)

SampleKey = tuple[int, date]


def assert_fair_compare_contract() -> dict[str, Any]:
    """V2 and V3 share X schema + mechanical labels; only universe policy differs."""
    v2_features = feature_names_from_manifest(PIT_DAILY_CORE_V2["feature_manifest"])
    v3_features = feature_names_from_manifest(PIT_DAILY_CORE_V3["feature_manifest"])
    v2_labels = label_names_from_manifest(PIT_DAILY_CORE_V2["feature_manifest"])
    v3_labels = label_names_from_manifest(PIT_DAILY_CORE_V3["feature_manifest"])
    pins_match = (
        PIT_DAILY_CORE_V2["basic_feature_set_code"] == PIT_DAILY_CORE_V3["basic_feature_set_code"]
        and PIT_DAILY_CORE_V2["basic_feature_set_version"]
        == PIT_DAILY_CORE_V3["basic_feature_set_version"]
        and PIT_DAILY_CORE_V2["technical_feature_set_code"]
        == PIT_DAILY_CORE_V3["technical_feature_set_code"]
        and PIT_DAILY_CORE_V2["technical_feature_set_version"]
        == PIT_DAILY_CORE_V3["technical_feature_set_version"]
        and PIT_DAILY_CORE_V2["technical_model_code"] == PIT_DAILY_CORE_V3["technical_model_code"]
        and PIT_DAILY_CORE_V2["technical_model_version"]
        == PIT_DAILY_CORE_V3["technical_model_version"]
        and PIT_DAILY_CORE_V2["technical_model_config_hash"]
        == PIT_DAILY_CORE_V3["technical_model_config_hash"]
        and PIT_DAILY_CORE_V2["relation_set_code"] == PIT_DAILY_CORE_V3["relation_set_code"]
        and PIT_DAILY_CORE_V2["relation_set_version"] == PIT_DAILY_CORE_V3["relation_set_version"]
        and PIT_DAILY_CORE_V2["label_spec"] == PIT_DAILY_CORE_V3["label_spec"]
    )
    if v2_features != v3_features:
        raise ValueError("V2/V3 feature schema mismatch — not a fair universe-only compare")
    if v2_labels != v3_labels:
        raise ValueError("V2/V3 label schema mismatch — not a fair universe-only compare")
    if not pins_match:
        raise ValueError("V2/V3 source pins / label_spec mismatch — not a fair universe-only compare")
    return {
        "feature_count": len(v2_features),
        "label_names": v2_labels,
        "pins_match": True,
        "universe_policies": {
            "v2": PIT_DAILY_CORE_V2["universe_policy"],
            "v3": PIT_DAILY_CORE_V3["universe_policy"],
        },
        "contract": (
            "Same date range, feature schema, source pins, and mechanical labels; "
            "only universe policy differs (current_active vs historical_equity_universe_v2)."
        ),
    }


def sample_keys_for_run(session: Session, run_id: int) -> set[SampleKey]:
    rows = session.execute(
        select(DatasetSampleDaily.instrument_id, DatasetSampleDaily.as_of_date).where(
            DatasetSampleDaily.dataset_run_id == run_id
        )
    ).all()
    return {(int(r[0]), r[1]) for r in rows}


def _year_coverage_from_samples(session: Session, run_id: int) -> list[dict[str, Any]]:
    rows = session.execute(
        select(DatasetSampleDaily.as_of_date, DatasetSampleDaily.instrument_id).where(
            DatasetSampleDaily.dataset_run_id == run_id
        )
    ).all()
    by_year: dict[int, dict[str, Any]] = {}
    for as_of, instrument_id in rows:
        year = as_of.year
        bucket = by_year.setdefault(year, {"samples": 0, "instruments": set()})
        bucket["samples"] += 1
        bucket["instruments"].add(int(instrument_id))
    return [
        {
            "year": year,
            "samples": data["samples"],
            "sampled_instruments": len(data["instruments"]),
        }
        for year, data in sorted(by_year.items())
    ]


def _missingness_summary(session: Session, run_id: int, *, limit: int = 2000) -> dict[str, Any]:
    """Bounded missingness scan over feature JSON (research diagnostic)."""
    samples = list(
        session.scalars(
            select(DatasetSampleDaily)
            .where(DatasetSampleDaily.dataset_run_id == run_id)
            .limit(limit)
        )
    )
    if not samples:
        return {"scanned_samples": 0, "feature_null_rates": {}, "note": "no samples"}
    null_counts: Counter[str] = Counter()
    feature_names = feature_names_from_manifest(PIT_DAILY_CORE_V2["feature_manifest"])
    for sample in samples:
        feats = sample.features or {}
        for name in feature_names:
            val = feats.get(name)
            if val is None:
                null_counts[name] += 1
    n = len(samples)
    rates = {
        name: round(null_counts.get(name, 0) / n, 4)
        for name in feature_names
        if null_counts.get(name, 0) > 0
    }
    top = sorted(rates.items(), key=lambda x: -x[1])[:15]
    return {
        "scanned_samples": n,
        "scanned_capped": n >= limit,
        "features_with_nulls": len(rates),
        "top_missing_features": top,
    }


def summarize_run_side(
    session: Session,
    run: DatasetRun,
    *,
    side: str,
) -> dict[str, Any]:
    spec = session.get(DatasetSpec, run.dataset_spec_id)
    cov = dict(run.coverage_summary or {})
    univ = dict((run.resolved_universe if run.resolved_universe else None) or {})
    univ_diag = dict(cov.get("universe") or {})
    labels_cov = dict(cov.get("labels") or {})
    year_cov = cov.get("by_year")
    if not year_cov:
        year_cov = _year_coverage_from_samples(session, run.id)

    instrument_ids = list(univ.get("instrument_ids") or [])
    inactive_now = univ.get("inactive_now")
    if inactive_now is None and instrument_ids:
        inactive_now = session.scalar(
            select(Instrument.id)
            .where(Instrument.id.in_(instrument_ids), Instrument.is_active.is_(False))
            .limit(1)
        )
        # recount properly
        inactive_now = len(
            list(
                session.scalars(
                    select(Instrument.id).where(
                        Instrument.id.in_(instrument_ids),
                        Instrument.is_active.is_(False),
                    )
                )
            )
        )

    return {
        "side": side,
        "spec": f"{(spec.code if spec else PIT_DAILY_CORE_CODE)}/v{(spec.version if spec else '?')}",
        "dataset_spec_version": spec.version if spec else None,
        "run_id": run.id,
        "status": run.status,
        "date_from": run.date_from.isoformat() if run.date_from else None,
        "date_to": run.date_to.isoformat() if run.date_to else None,
        "universe_policy": univ.get("policy") or (spec.universe_policy if spec else None),
        "instruments_resolved": len(instrument_ids) or run.instruments_total,
        "instruments_with_samples": univ_diag.get("instruments_with_samples"),
        "samples_total": run.samples_total,
        "trainable": {
            "eligible_1d": run.eligible_1d,
            "eligible_5d": run.eligible_5d,
            "eligible_10d": run.eligible_10d,
            "eligible_20d": run.eligible_20d,
        },
        "label_coverage": {
            "valid": labels_cov.get("valid"),
            "invalid": labels_cov.get("invalid", run.invalid_labels),
            "eligible": labels_cov.get("eligible")
            or {
                "1d": run.eligible_1d,
                "5d": run.eligible_5d,
                "10d": run.eligible_10d,
                "20d": run.eligible_20d,
            },
            "labels_rejected_after_eligible_to": labels_cov.get(
                "labels_rejected_after_eligible_to"
            ),
        },
        "quality_counts": {
            "core_invalid": run.core_invalid,
            "technical_missing": run.technical_missing,
            "relation_missing": run.relation_missing,
            "invalid_labels": run.invalid_labels,
        },
        "inactive_representation": {
            "inactive_now_in_universe": inactive_now,
            "inactive_instruments_with_samples": univ_diag.get(
                "inactive_instruments_with_samples", 0 if side == "v2" else None
            ),
            "samples_from_currently_inactive": univ_diag.get(
                "samples_from_currently_inactive_instruments",
                0 if side == "v2" else None,
            ),
            "historical_instruments": univ.get("historically_eligible_instruments"),
            "rejected_before_eligible_from": univ_diag.get("samples_rejected_before_eligible_from"),
            "rejected_after_eligible_to": univ_diag.get("samples_rejected_after_eligible_to"),
        },
        "year_coverage": year_cov,
        "boundary_quality": univ_diag.get("boundary_quality")
        or {
            "eligible_from_quality_counts": univ.get("eligible_from_quality_counts"),
            "eligible_to_quality_counts": univ.get("eligible_to_quality_counts"),
            "universe_quality": univ.get("universe_quality"),
        },
        "pit_status": run.pit_status,
        "pit_violations": run.pit_violations,
        "dataset_hash": run.dataset_hash,
        "values_hash": (run.manifest or {}).get("values_hash"),
        "missingness": _missingness_summary(session, run.id),
        "source_versions": (run.manifest or {}).get("source_versions"),
    }


def compare_sample_sets(
    session: Session,
    *,
    v2_run_id: int,
    v3_run_id: int,
) -> dict[str, Any]:
    keys_v2 = sample_keys_for_run(session, v2_run_id)
    keys_v3 = sample_keys_for_run(session, v3_run_id)
    only_v2 = keys_v2 - keys_v3
    only_v3 = keys_v3 - keys_v2
    both = keys_v2 & keys_v3

    only_v3_instrument_ids = {iid for iid, _ in only_v3}
    only_v2_instrument_ids = {iid for iid, _ in only_v2}
    historical_only_in_v3: list[dict[str, Any]] = []
    if only_v3_instrument_ids:
        rows = session.execute(
            select(Instrument.id, Instrument.symbol, Instrument.is_active, Instrument.active_to).where(
                Instrument.id.in_(sorted(only_v3_instrument_ids))
            )
        ).all()
        for iid, symbol, is_active, active_to in rows:
            if iid in only_v2_instrument_ids:
                continue
            # Name appears in V3-only keys and never in V2 sample keys.
            if iid not in {k[0] for k in keys_v2}:
                historical_only_in_v3.append(
                    {
                        "instrument_id": int(iid),
                        "symbol": symbol,
                        "is_active": bool(is_active),
                        "active_to": active_to.isoformat() if active_to else None,
                        "v3_only_samples": sum(1 for k in only_v3 if k[0] == iid),
                    }
                )
    historical_only_in_v3.sort(key=lambda r: (-r["v3_only_samples"], r["symbol"] or ""))

    return {
        "v2_samples": len(keys_v2),
        "v3_samples": len(keys_v3),
        "intersection_samples": len(both),
        "unique_v2_samples": len(only_v2),
        "unique_v3_samples": len(only_v3),
        "unique_v2_instruments": len({iid for iid, _ in only_v2}),
        "unique_v3_instruments": len({iid for iid, _ in only_v3}),
        "historical_names_only_in_v3_count": len(historical_only_in_v3),
        "historical_names_only_in_v3": historical_only_in_v3[:50],
        "historical_names_truncated": len(historical_only_in_v3) > 50,
    }


def factual_interpretation(
    *,
    v2: dict[str, Any],
    v3: dict[str, Any],
    sample_diff: dict[str, Any],
    fair: dict[str, Any],
) -> list[str]:
    """Factual statements only — no ranking language ('V3 wins', etc.)."""
    notes: list[str] = [
        fair["contract"],
        (
            f"V2 samples={v2.get('samples_total')}, V3 samples={v3.get('samples_total')}; "
            f"intersection={sample_diff.get('intersection_samples')}, "
            f"unique_v2={sample_diff.get('unique_v2_samples')}, "
            f"unique_v3={sample_diff.get('unique_v3_samples')}."
        ),
        (
            f"Trainable eligible_20d: V2={v2.get('trainable', {}).get('eligible_20d')}, "
            f"V3={v3.get('trainable', {}).get('eligible_20d')}."
        ),
        (
            f"PIT: V2 status={v2.get('pit_status')} violations={v2.get('pit_violations')}; "
            f"V3 status={v3.get('pit_status')} violations={v3.get('pit_violations')}."
        ),
    ]
    hist_n = sample_diff.get("historical_names_only_in_v3_count") or 0
    if hist_n:
        notes.append(
            f"{hist_n} instrument(s) appear in V3 samples but not in V2 "
            "(typically currently inactive / historically eligible names)."
        )
    else:
        notes.append(
            "No V3-only instruments in this bounded window "
            "(V3 may still apply date eligibility within shared names)."
        )
    v3_inactive = (v3.get("inactive_representation") or {}).get(
        "samples_from_currently_inactive"
    )
    if v3_inactive:
        notes.append(
            f"V3 includes {v3_inactive} sample(s) from instruments that are inactive now."
        )
    notes.append(
        "This artifact measures dataset coverage/correctness under a fair pin contract; "
        "it is not a model performance or alpha claim."
    )
    return notes
