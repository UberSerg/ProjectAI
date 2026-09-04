"""Bounded PIT feature assembler for Forward Signal V0 (exact Candidate V0 X schema)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import InstrumentFeatureDaily
from app.infrastructure.analytics.relation_repository import (
    load_lag_metrics_for_snapshots,
    load_pinned_relation_set,
    load_relation_inputs_by_codes,
    load_relation_snapshots_for_join,
)
from app.infrastructure.market.models import Instrument
from app.infrastructure.technical.models import InstrumentTechnicalFeatureDaily, TechnicalSignalDaily
from app.modules.analytics.application.resolve import resolve_feature_set
from app.modules.learning.application.relations_join import (
    RelationIndex,
    extract_all_relation_features,
    instrument_relation_input_code,
)
from app.modules.learning.application.source_join import merge_phase1_features, select_exact_as_of
from app.modules.prediction.application.forward_config import (
    EXPECTED_FEATURE_COUNT,
    FORWARD_BASIC_FS_CODE,
    FORWARD_BASIC_FS_VERSION,
    FORWARD_MAX_RELATION_AGE_DAYS,
    FORWARD_RELATION_CONTEXTS,
    FORWARD_RELATION_SET_CODE,
    FORWARD_RELATION_SET_VERSION,
    FORWARD_TECH_FS_CODE,
    FORWARD_TECH_FS_VERSION,
    FORWARD_TECH_MODEL_CODE,
    FORWARD_TECH_MODEL_VERSION,
)
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG, CandidateV0Config


@dataclass
class AssembledRow:
    instrument_id: int
    ticker: str
    as_of_date: date
    features: dict[str, float | None]
    eligible: bool
    ineligible_reason: str | None = None
    lineage: dict[str, Any] = field(default_factory=dict)
    pit_ok: bool = True
    pit_violations: list[str] = field(default_factory=list)


def _ordered_feature_vector(
    features: dict[str, float | None],
    feature_names: tuple[str, ...],
) -> np.ndarray:
    vec = []
    for name in feature_names:
        val = features.get(name)
        vec.append(float(val) if val is not None else np.nan)
    return np.asarray(vec, dtype=float)


def assert_no_labels_in_features(features: dict[str, float | None]) -> None:
    for key in features:
        if key.startswith("forward_return_") or key.startswith("target_date_"):
            raise ValueError(f"label leaked into X: {key}")


def assemble_forward_rows(
    session: Session,
    *,
    as_of: date,
    instruments: list[Instrument] | None = None,
    config: CandidateV0Config = CANDIDATE_V0_CONFIG,
) -> list[AssembledRow]:
    """Assemble exact 90-feature X(t) for active instruments without Dataset rebuild."""
    if len(config.feature_names) != EXPECTED_FEATURE_COUNT:
        raise ValueError(f"expected {EXPECTED_FEATURE_COUNT} features, got {len(config.feature_names)}")

    basic_fs = resolve_feature_set(session, FORWARD_BASIC_FS_CODE, FORWARD_BASIC_FS_VERSION)
    tech_fs = resolve_feature_set(session, FORWARD_TECH_FS_CODE, FORWARD_TECH_FS_VERSION)

    if instruments is None:
        instruments = list(
            session.scalars(select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.id))
        )
    inst_ids = [i.id for i in instruments]
    if not inst_ids:
        return []

    basic_rows = list(
        session.scalars(
            select(InstrumentFeatureDaily).where(
                InstrumentFeatureDaily.feature_set_id == basic_fs.id,
                InstrumentFeatureDaily.date == as_of,
                InstrumentFeatureDaily.instrument_id.in_(inst_ids),
            )
        )
    )
    tech_rows = list(
        session.scalars(
            select(InstrumentTechnicalFeatureDaily).where(
                InstrumentTechnicalFeatureDaily.feature_set_id == tech_fs.id,
                InstrumentTechnicalFeatureDaily.date == as_of,
                InstrumentTechnicalFeatureDaily.instrument_id.in_(inst_ids),
            )
        )
    )
    signal_rows = list(
        session.scalars(
            select(TechnicalSignalDaily).where(
                TechnicalSignalDaily.model_code == FORWARD_TECH_MODEL_CODE,
                TechnicalSignalDaily.model_version == FORWARD_TECH_MODEL_VERSION,
                TechnicalSignalDaily.basic_feature_set_id == basic_fs.id,
                TechnicalSignalDaily.technical_feature_set_id == tech_fs.id,
                TechnicalSignalDaily.as_of_date == as_of,
                TechnicalSignalDaily.instrument_id.in_(inst_ids),
            )
        )
    )
    basic_by_inst = {r.instrument_id: {as_of: r} for r in basic_rows}
    tech_by_inst = {r.instrument_id: {as_of: r} for r in tech_rows}
    signal_by_inst = {r.instrument_id: {as_of: r} for r in signal_rows}

    # Relations (optional): latest snapshot as_of <= t within max age
    relation_set = load_pinned_relation_set(
        session, FORWARD_RELATION_SET_CODE, FORWARD_RELATION_SET_VERSION
    )
    contexts = list(FORWARD_RELATION_CONTEXTS)
    subject_codes = [instrument_relation_input_code(i.symbol) for i in instruments]
    context_codes = [str(ctx["input_code"]) for ctx in contexts]
    inputs_by_code = load_relation_inputs_by_codes(session, subject_codes + context_codes)
    subject_input_by_instrument: dict[int, UUID] = {}
    for inst in instruments:
        row = inputs_by_code.get(instrument_relation_input_code(inst.symbol))
        if row is not None:
            subject_input_by_instrument[inst.id] = row.id
    context_input_ids: dict[str, UUID | None] = {}
    for ctx in contexts:
        row = inputs_by_code.get(str(ctx["input_code"]))
        context_input_ids[str(ctx["key"])] = row.id if row is not None else None

    relation_windows = sorted({int(w) for ctx in contexts for w in ctx.get("windows", [20, 60, 120])})
    relation_lag_windows = {int(ctx.get("lag_window", 60)) for ctx in contexts}
    relation_lags: list[int] = []
    for ctx in contexts:
        for lag in ctx.get("lags", [1, 2, 3, 4, 5]):
            if int(lag) not in relation_lags:
                relation_lags.append(int(lag))

    relation_index = RelationIndex.build([], {})
    if relation_set is not None and relation_windows:
        pair_ids = [
            (subj_id, ctx_id)
            for subj_id in subject_input_by_instrument.values()
            for ctx_id in context_input_ids.values()
            if ctx_id is not None and subj_id != ctx_id
        ]
        if pair_ids:
            snapshots = load_relation_snapshots_for_join(
                session,
                relation_set_id=relation_set.id,
                relation_set_version=FORWARD_RELATION_SET_VERSION,
                pair_ids=pair_ids,
                windows=relation_windows,
                date_from=as_of,
                date_to=as_of,
                lookback_days=FORWARD_MAX_RELATION_AGE_DAYS + 1,
            )
            # Hard PIT: never use future snapshots
            snapshots = [s for s in snapshots if s.as_of_date <= as_of]
            lag_snap_ids = [
                snap.id for snap in snapshots if int(snap.window_observations) in relation_lag_windows
            ]
            lags_by_snapshot = load_lag_metrics_for_snapshots(
                session, lag_snap_ids, lags=relation_lags or None
            )
            relation_index = RelationIndex.build(snapshots, lags_by_snapshot)

    out: list[AssembledRow] = []
    for inst in instruments:
        basic = select_exact_as_of(basic_by_inst.get(inst.id, {}), as_of)
        technical = select_exact_as_of(tech_by_inst.get(inst.id, {}), as_of)
        signal = select_exact_as_of(signal_by_inst.get(inst.id, {}), as_of)

        pit_violations: list[str] = []
        if basic is not None and getattr(basic, "date", as_of) > as_of:
            pit_violations.append("analytics_date_gt_as_of")
        if technical is not None and getattr(technical, "date", as_of) > as_of:
            pit_violations.append("technical_date_gt_as_of")
        if signal is not None and getattr(signal, "as_of_date", as_of) > as_of:
            pit_violations.append("signal_date_gt_as_of")

        phase1, _direction = merge_phase1_features(basic, technical, signal)
        rel = extract_all_relation_features(
            contexts=contexts,
            subject_input_id=subject_input_by_instrument.get(inst.id),
            context_input_ids=context_input_ids,
            index=relation_index,
            as_of=as_of,
            max_age_days=FORWARD_MAX_RELATION_AGE_DAYS,
        )
        # Relation PIT: any as_of_dates > t is a hard failure
        for ctx_key, meta in (rel.context_meta or {}).items():
            for _w, d_str in (meta.get("as_of_dates") or {}).items():
                if d_str and date.fromisoformat(str(d_str)) > as_of:
                    pit_violations.append(f"relation_future:{ctx_key}")

        features: dict[str, float | None] = {}
        features.update(phase1)
        features.update(rel.features)
        assert_no_labels_in_features(features)

        # Ensure exact schema keys only
        ordered = {name: features.get(name) for name in config.feature_names}
        if len(ordered) != EXPECTED_FEATURE_COUNT:
            raise ValueError("feature schema size mismatch after assembly")

        core_valid = bool(basic is not None and getattr(basic, "is_valid", False))
        technical_available = technical is not None and signal is not None
        eligible = core_valid and technical_available and not pit_violations
        reason = None
        if pit_violations:
            reason = "pit_violation"
        elif not core_valid:
            reason = "core_invalid_or_missing"
        elif not technical_available:
            reason = "technical_missing"

        lineage = {
            "analytics": {
                "code": FORWARD_BASIC_FS_CODE,
                "version": FORWARD_BASIC_FS_VERSION,
                "date": as_of.isoformat() if basic is not None else None,
                "is_valid": bool(getattr(basic, "is_valid", False)) if basic else False,
            },
            "technical": {
                "code": FORWARD_TECH_FS_CODE,
                "version": FORWARD_TECH_FS_VERSION,
                "date": as_of.isoformat() if technical is not None else None,
            },
            "rules": {
                "code": FORWARD_TECH_MODEL_CODE,
                "version": FORWARD_TECH_MODEL_VERSION,
                "as_of_date": as_of.isoformat() if signal is not None else None,
            },
            "relations": {
                "code": FORWARD_RELATION_SET_CODE,
                "version": FORWARD_RELATION_SET_VERSION,
                "available": rel.available,
                "age_days": rel.age_days,
                "as_of_dates": rel.as_of_dates,
                "max_age_days": FORWARD_MAX_RELATION_AGE_DAYS,
            },
        }
        out.append(
            AssembledRow(
                instrument_id=inst.id,
                ticker=inst.symbol,
                as_of_date=as_of,
                features=ordered,
                eligible=eligible,
                ineligible_reason=reason,
                lineage=lineage,
                pit_ok=not pit_violations,
                pit_violations=pit_violations,
            )
        )
    return out


def rows_to_matrix(
    rows: list[AssembledRow],
    *,
    config: CandidateV0Config = CANDIDATE_V0_CONFIG,
) -> np.ndarray:
    if not rows:
        return np.zeros((0, len(config.feature_names)), dtype=float)
    return np.vstack([_ordered_feature_vector(r.features, config.feature_names) for r in rows])
