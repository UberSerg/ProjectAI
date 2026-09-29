"""PITDatasetBuilder — assemble X(t) and Y(t+h) with version pins and PIT validation."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application.system.event_log import write_event
from app.core.logging import get_logger
from app.infrastructure.analytics.models import InstrumentFeatureDaily
from app.infrastructure.analytics.relation_repository import (
    load_lag_metrics_for_snapshots,
    load_pinned_relation_set,
    load_relation_inputs_by_codes,
    load_relation_snapshots_for_join,
)
from app.infrastructure.learning.models import DatasetRun, DatasetSpec
from app.infrastructure.learning.repository import insert_dataset_samples, sample_row
from app.infrastructure.market.models import Candle, DataQualityIssue, Workflow
from app.infrastructure.technical.models import InstrumentTechnicalFeatureDaily, TechnicalSignalDaily
from app.modules.analytics.application.resolve import resolve_feature_set
from app.modules.analytics.application.seed import seed_feature_sets
from app.modules.learning.application.contracts import (
    DatasetFeatureVectorV1,
    DatasetLineageV1,
    DatasetQualityV1,
    DatasetSampleV1,
)
from app.modules.learning.application.hash_util import (
    dataset_hash,
    dataset_values_hash,
    sample_content_hash,
    sample_values_hash,
)
from app.modules.learning.application.labels import (
    ForwardReturnLabelCalculator,
    LabelResult,
    PriceObservation,
)
from app.modules.learning.application.relations_join import (
    RelationIndex,
    empty_relation_join,
    extract_all_relation_features,
    instrument_relation_input_code,
)
from app.modules.learning.application.seed import seed_dataset_specs
from app.modules.learning.application.source_join import merge_phase1_features, select_exact_as_of
from app.modules.learning.application.universe_resolve import (
    HistoricalUniverseResolutionError,
    eligibility_audit,
    resolve_dataset_universe,
)
from app.modules.learning.application.validator import PITDatasetValidator, assert_manifest_separation
from app.modules.learning.dataset_config import (
    DATASET_BUILD_STEPS,
    PIT_DAILY_CORE_CODE,
    PIT_DAILY_CORE_RESEARCH_VERSION,
    PIT_DAILY_CORE_V3_VERSION,
    PIT_DAILY_CORE_VERSION,
    RESEARCH_CORE_GRADE_NOT_READY,
    RESEARCH_CORE_GRADE_PARTIAL,
    RESEARCH_CORE_GRADE_READY,
    RESEARCH_CORE_PARTIAL_PROXY_FROM_PCT,
    RESEARCH_CORE_READY_MIN_SAMPLES,
    RESEARCH_CORE_READY_MIN_YEARS_WITH_SAMPLES,
    is_horizon_training_eligible,
    is_sample_relation_missing,
    relation_feature_names,
    uses_mechanical_label_basis,
)
from app.modules.market.application.historical_universe import (
    HISTORICAL_EQUITY_UNIVERSE_V2,
    HistoricalEligibility,
)
from app.modules.market.application.mechanical_adjustment import MechanicalAction, load_mechanical_actions
from app.modules.market.application.workflows import create_workflow, finish_workflow, get_step, update_step

logger = get_logger(__name__, component="dataset-pit")


def _clip_prices_to_eligibility(
    prices: list[PriceObservation],
    elig: HistoricalEligibility,
) -> list[PriceObservation]:
    """Restrict label observations to the historical eligibility window (V3 only)."""
    return [
        p
        for p in prices
        if p.date >= elig.eligible_from
        and (elig.eligible_to is None or p.date <= elig.eligible_to)
    ]


def _invalidate_labels_past_eligible_to(
    label_result: LabelResult,
    *,
    full_prices: list[PriceObservation],
    as_of: date,
    eligible_to: date,
    horizons: list[int],
) -> int:
    """Invalidate Y(t+h) when the target observation is after eligible_to.

    Distinguishes ``target_after_eligible_to_*`` from ordinary ``missing_future_*``.
    Returns the number of horizons invalidated.
    """
    full_dates = sorted({p.date for p in full_prices})
    if as_of not in full_dates:
        return 0
    idx = full_dates.index(as_of)
    rejected = 0
    for h in horizons:
        key = f"{h}d"
        target_idx = idx + h
        if target_idx >= len(full_dates):
            continue
        target_date = full_dates[target_idx]
        if target_date <= eligible_to:
            continue
        attr = f"forward_return_{h}d"
        date_attr = f"target_date_{h}d"
        if hasattr(label_result.labels, attr):
            setattr(label_result.labels, attr, None)
        prior_target = None
        if hasattr(label_result.labels, date_attr):
            prior_target = getattr(label_result.labels, date_attr, None)
            setattr(label_result.labels, date_attr, None)
        label_result.label_valid[key] = False
        label_result.label_flags[f"target_after_eligible_to_{key}"] = True
        label_result.label_flags[f"rejected_target_date_{key}"] = (
            prior_target.isoformat()
            if isinstance(prior_target, date)
            else target_date.isoformat()
        )
        # Prefer the explicit boundary reason over truncation-induced missing_future.
        label_result.label_flags.pop(f"missing_future_{key}", None)
        label_result.target_candle_ids[key] = None
        rejected += 1
    return rejected


def _pct_or_none(numerator: int, denominator: int | None) -> float | None:
    """Coverage percentage; None when denominator unknown/empty (never invent 0/100)."""
    if denominator is None or denominator <= 0:
        return None
    return round(100.0 * numerator / denominator, 2)


def _build_year_coverage(
    *,
    by_year: dict[str, Any],
    eligibility_by_id: dict[int, HistoricalEligibility],
    date_from: date,
    date_to: date,
    horizons: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Bounded per-year summary for Dataset V3 coverage diagnostics."""
    hs = list(horizons or [1, 5, 10, 20])
    years = sorted({y for y in range(date_from.year, date_to.year + 1)} | {int(k) for k in by_year})
    out: list[dict[str, Any]] = []
    for year in years:
        y_start = date(year, 1, 1)
        y_end = date(year, 12, 31)
        window_start = max(date_from, y_start)
        window_end = min(date_to, y_end)
        if window_start > window_end:
            continue
        eligible: int | None
        if eligibility_by_id:
            eligible = 0
            for elig in eligibility_by_id.values():
                # Any overlap of eligibility window with the year slice.
                e_to = elig.eligible_to or window_end
                if elig.eligible_from <= window_end and e_to >= window_start:
                    eligible += 1
        else:
            # Unknown universe eligibility — do not zero-fill or invent coverage.
            eligible = None
        bucket = by_year.get(str(year), {})
        sampled_ids = bucket.get("sampled_instruments") or set()
        inactive_ids = bucket.get("inactive_now_instruments") or set()
        samples_n = int(bucket.get("samples") or 0)
        sampled_n = len(sampled_ids)
        te = bucket.get("training_eligible") or {}
        lv = bucket.get("label_valid") or {}
        training_eligible = {f"{h}d": int(te.get(f"{h}d") or 0) for h in hs}
        label_valid = {f"{h}d": int(lv.get(f"{h}d") or 0) for h in hs}
        label_coverage_pct = {
            key: _pct_or_none(label_valid[key], samples_n if samples_n > 0 else None)
            for key in label_valid
        }
        training_eligible_pct = {
            key: _pct_or_none(training_eligible[key], samples_n if samples_n > 0 else None)
            for key in training_eligible
        }
        row: dict[str, Any] = {
            "year": year,
            "eligible_instruments": eligible,
            "sampled_instruments": sampled_n,
            "samples": samples_n,
            "inactive_now_instruments_represented": len(inactive_ids),
            # Prefer explicit sample_coverage_pct; keep coverage_pct alias.
            "sample_coverage_pct": _pct_or_none(sampled_n, eligible),
            "coverage_pct": _pct_or_none(sampled_n, eligible),
            "label_coverage_pct": label_coverage_pct,
            "training_eligible_pct": training_eligible_pct,
        }
        for h in hs:
            key = f"{h}d"
            row[f"training_eligible_{key}"] = training_eligible[key]
            row[f"label_valid_{key}"] = label_valid[key]
        out.append(row)
    return out


def grade_v3_core_research_quality(
    *,
    samples_total: int,
    apply_date_eligibility: bool,
    resolved_universe: dict[str, Any],
    universe_cov: dict[str, Any],
    by_year: list[dict[str, Any]],
) -> dict[str, Any]:
    """RESEARCH-ONLY grade from measurable CORE evidence. Never production-ready."""
    reasons: list[str] = []
    proxy_from_pct = resolved_universe.get("proxy_from_pct")
    authoritative_from_pct = resolved_universe.get("authoritative_from_pct")
    inactive_now = int(resolved_universe.get("inactive_now") or 0)
    inactive_with_samples = int(universe_cov.get("inactive_instruments_with_samples") or 0)
    years_with_samples = sum(1 for y in by_year if int(y.get("samples") or 0) > 0)

    if not apply_date_eligibility:
        reasons.append("date_eligibility_not_applied")
    if samples_total < RESEARCH_CORE_READY_MIN_SAMPLES:
        reasons.append("insufficient_samples")
    if years_with_samples < RESEARCH_CORE_READY_MIN_YEARS_WITH_SAMPLES:
        reasons.append("no_year_coverage")

    if reasons:
        grade = RESEARCH_CORE_GRADE_NOT_READY
    else:
        grade = RESEARCH_CORE_GRADE_READY
        if (
            isinstance(proxy_from_pct, int | float)
            and float(proxy_from_pct) > RESEARCH_CORE_PARTIAL_PROXY_FROM_PCT
        ):
            grade = RESEARCH_CORE_GRADE_PARTIAL
            reasons.append(
                f"proxy_from_pct>{RESEARCH_CORE_PARTIAL_PROXY_FROM_PCT}"
            )
        if inactive_now > 0 and inactive_with_samples <= 0:
            grade = RESEARCH_CORE_GRADE_PARTIAL
            reasons.append("inactive_now_present_but_not_represented_in_samples")
        if resolved_universe.get("universe_quality") == "PARTIAL" and grade == RESEARCH_CORE_GRADE_READY:
            # HU completeness is PARTIAL by contract; still READY_FOR_RESEARCH when
            # measurable CORE evidence is otherwise adequate — note the limitation.
            reasons.append("historical_universe_completeness_partial_td008")

    return {
        "grade": grade,
        "scope": "research_only",
        "production_ready": False,
        "activated": False,
        "dataset_research_version": PIT_DAILY_CORE_RESEARCH_VERSION,
        "thresholds": {
            "min_samples": RESEARCH_CORE_READY_MIN_SAMPLES,
            "min_years_with_samples": RESEARCH_CORE_READY_MIN_YEARS_WITH_SAMPLES,
            "partial_proxy_from_pct": RESEARCH_CORE_PARTIAL_PROXY_FROM_PCT,
        },
        "evidence": {
            "samples_total": samples_total,
            "years_with_samples": years_with_samples,
            "inactive_now": inactive_now,
            "inactive_instruments_with_samples": inactive_with_samples,
            "proxy_from_pct": proxy_from_pct,
            "authoritative_from_pct": authoritative_from_pct,
            "universe_quality": resolved_universe.get("universe_quality"),
            "apply_date_eligibility": apply_date_eligibility,
        },
        "reasons": reasons,
        "notes": [
            "READY_FOR_RESEARCH means measurable CORE evidence is usable for research builds.",
            "Never interpret as production-ready, Candidate/Shadow switch, or auto-activation.",
            "Historical universe completeness remains PARTIAL (TD-008).",
        ],
    }


class PITDatasetBuilder:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _mark(self, workflow: Workflow, step_name: str, status: str) -> None:
        update_step(self.session, get_step(workflow, step_name), status)
        self.session.commit()

    def _heartbeat(self, workflow: Workflow, **meta: Any) -> None:
        current = dict(workflow.meta or {})
        current.update(meta)
        workflow.meta = current
        self.session.commit()

    def run_build(
        self,
        *,
        date_from: date,
        date_to: date | None = None,
        dataset_spec_code: str = PIT_DAILY_CORE_CODE,
        dataset_spec_version: int = PIT_DAILY_CORE_VERSION,
        instrument_ids: list[int] | None = None,
        workflow_id: int | None = None,
        seed_specs: bool = True,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        workflow = self._resolve_workflow(workflow_id)
        dataset_run: DatasetRun | None = None

        try:
            self._mark(workflow, "Resolve dataset spec", "RUNNING")
            if seed_specs:
                seed_dataset_specs(self.session)
            spec = self.session.scalar(
                select(DatasetSpec).where(
                    DatasetSpec.code == dataset_spec_code,
                    DatasetSpec.version == dataset_spec_version,
                )
            )
            if spec is None:
                raise ValueError(f"Dataset spec not found: {dataset_spec_code} v{dataset_spec_version}")
            assert_manifest_separation(list(spec.feature_manifest or []))
            self._mark(workflow, "Resolve dataset spec", "SUCCESS")

            write_event(
                self.session,
                level="INFO",
                component="dataset",
                event_type="dataset.build_started",
                message=f"Dataset build started {spec.code} v{spec.version}",
                workflow_id=workflow.id,
                trace_id=(workflow.meta or {}).get("trace_id"),
            )

            self._mark(workflow, "Resolve pinned source versions", "RUNNING")
            seed_feature_sets(self.session)
            basic_fs = resolve_feature_set(
                self.session, spec.basic_feature_set_code, spec.basic_feature_set_version
            )
            tech_fs = resolve_feature_set(
                self.session, spec.technical_feature_set_code, spec.technical_feature_set_version
            )
            quality_policy = spec.quality_policy or {}
            relations_enabled = bool(quality_policy.get("relations_join_enabled", True))
            relations_optional = bool(quality_policy.get("relations_optional", True))
            max_relation_age_days = int(quality_policy.get("max_relation_age_days", 8))
            relation_contexts = list(spec.relation_contexts or [])
            self._mark(workflow, "Resolve pinned source versions", "SUCCESS")

            self._mark(workflow, "Resolve universe", "RUNNING")
            t_universe = time.perf_counter()
            try:
                universe = resolve_dataset_universe(
                    self.session,
                    universe_policy=str(spec.universe_policy or ""),
                    instrument_ids=instrument_ids,
                    parameters=dict(spec.parameters or {}),
                )
            except HistoricalUniverseResolutionError as exc:
                self._mark(workflow, "Resolve universe", "FAILED")
                write_event(
                    self.session,
                    level="ERROR",
                    component="dataset",
                    event_type="dataset.universe_failed",
                    message=str(exc),
                    workflow_id=workflow.id,
                    trace_id=(workflow.meta or {}).get("trace_id"),
                )
                raise
            # V3 contract: never silently resolve to current_active / no date eligibility.
            if int(spec.version) == PIT_DAILY_CORE_V3_VERSION and not universe.apply_date_eligibility:
                self._mark(workflow, "Resolve universe", "FAILED")
                err = HistoricalUniverseResolutionError(
                    "pit_daily_core v3 requires historical_equity_universe_v2 date eligibility; "
                    "refusing current_active_instruments fallback"
                )
                write_event(
                    self.session,
                    level="ERROR",
                    component="dataset",
                    event_type="dataset.universe_failed",
                    message=str(err),
                    workflow_id=workflow.id,
                    trace_id=(workflow.meta or {}).get("trace_id"),
                )
                raise err
            instruments = universe.instruments
            resolved_universe = dict(universe.resolved_universe)
            eligibility_by_id = universe.eligibility_by_id
            apply_date_eligibility = universe.apply_date_eligibility
            universe_sec = round(time.perf_counter() - t_universe, 3)
            self._mark(workflow, "Resolve universe", "SUCCESS")

            effective_to = date_to or self.session.scalar(select(func.max(Candle.timestamp)))
            if effective_to is not None and hasattr(effective_to, "date"):
                effective_to = effective_to.date()
            if effective_to is None:
                effective_to = date_from

            dataset_run = DatasetRun(
                dataset_spec_id=spec.id,
                date_from=date_from,
                date_to=effective_to,
                started_at=datetime.now(UTC),
                status="RUNNING",
                instruments_total=len(instruments),
                workflow_id=workflow.id,
                resolved_universe=resolved_universe,
                pit_status="PENDING",
            )
            self.session.add(dataset_run)
            self.session.flush()

            # --- Load sources (batch) ---
            self._mark(workflow, "Load Analytics", "RUNNING")
            t_load_a = time.perf_counter()
            inst_ids = [i.id for i in instruments]
            basic_rows = list(
                self.session.scalars(
                    select(InstrumentFeatureDaily).where(
                        InstrumentFeatureDaily.feature_set_id == basic_fs.id,
                        InstrumentFeatureDaily.date >= date_from,
                        InstrumentFeatureDaily.date <= effective_to,
                        InstrumentFeatureDaily.instrument_id.in_(inst_ids) if inst_ids else False,
                    )
                )
            ) if inst_ids else []

            basic_by_inst: dict[int, dict[date, InstrumentFeatureDaily]] = {}
            for row in basic_rows:
                basic_by_inst.setdefault(row.instrument_id, {})[row.date] = row
            load_analytics_sec = round(time.perf_counter() - t_load_a, 3)
            self._mark(workflow, "Load Analytics", "SUCCESS")

            self._mark(workflow, "Load Technical", "RUNNING")
            t_load_t = time.perf_counter()
            tech_rows = list(
                self.session.scalars(
                    select(InstrumentTechnicalFeatureDaily).where(
                        InstrumentTechnicalFeatureDaily.feature_set_id == tech_fs.id,
                        InstrumentTechnicalFeatureDaily.date >= date_from,
                        InstrumentTechnicalFeatureDaily.date <= effective_to,
                        InstrumentTechnicalFeatureDaily.instrument_id.in_(inst_ids),
                    )
                )
            ) if inst_ids else []

            tech_by_inst: dict[int, dict[date, InstrumentTechnicalFeatureDaily]] = {}
            for row in tech_rows:
                tech_by_inst.setdefault(row.instrument_id, {})[row.date] = row

            signal_rows = list(
                self.session.scalars(
                    select(TechnicalSignalDaily).where(
                        TechnicalSignalDaily.model_code == spec.technical_model_code,
                        TechnicalSignalDaily.model_version == spec.technical_model_version,
                        TechnicalSignalDaily.basic_feature_set_id == basic_fs.id,
                        TechnicalSignalDaily.technical_feature_set_id == tech_fs.id,
                        TechnicalSignalDaily.as_of_date >= date_from,
                        TechnicalSignalDaily.as_of_date <= effective_to,
                        TechnicalSignalDaily.instrument_id.in_(inst_ids),
                    )
                )
            ) if inst_ids else []

            signal_by_inst: dict[int, dict[date, TechnicalSignalDaily]] = {}
            for row in signal_rows:
                signal_by_inst.setdefault(row.instrument_id, {})[row.as_of_date] = row
            load_technical_sec = round(time.perf_counter() - t_load_t, 3)
            self._mark(workflow, "Load Technical", "SUCCESS")

            self._mark(workflow, "Load Relations", "RUNNING")
            t_load_r = time.perf_counter()
            # Deep-history Relations V2: do not preload all instruments' snapshots/lags at once
            # (hundreds of thousands of rows → Docker OOM). Resolve inputs here; load per batch below.
            relation_index = RelationIndex.build([], {})
            subject_input_by_instrument: dict[int, UUID] = {}
            context_input_ids: dict[str, UUID] = {}
            relation_set_row = None
            relation_windows: list[int] = []
            relation_lag_windows: set[int] = set()
            relation_lags: list[int] = []
            relation_instrument_batch = 5
            if relations_enabled:
                relation_set_row = load_pinned_relation_set(
                    self.session, spec.relation_set_code, spec.relation_set_version
                )
                subject_codes = [instrument_relation_input_code(inst.symbol) for inst in instruments]
                context_codes = [str(ctx["input_code"]) for ctx in relation_contexts]
                inputs_by_code = load_relation_inputs_by_codes(
                    self.session, subject_codes + context_codes
                )
                for inst in instruments:
                    row = inputs_by_code.get(instrument_relation_input_code(inst.symbol))
                    if row is not None:
                        subject_input_by_instrument[inst.id] = row.id
                for ctx in relation_contexts:
                    row = inputs_by_code.get(str(ctx["input_code"]))
                    if row is not None:
                        context_input_ids[str(ctx["key"])] = row.id
                    relation_lag_windows.add(int(ctx.get("lag_window", 60)))
                    for lag in ctx.get("lags", [1, 2, 3, 4, 5]):
                        if int(lag) not in relation_lags:
                            relation_lags.append(int(lag))
                relation_windows = sorted(
                    {
                        int(w)
                        for ctx in relation_contexts
                        for w in ctx.get("windows", [20, 60, 120])
                    }
                )
                self._heartbeat(
                    workflow,
                    relations_join="enabled",
                    relation_set=f"{spec.relation_set_code} v{spec.relation_set_version}",
                    relation_load="batched",
                    relation_batch_size=relation_instrument_batch,
                )
            else:
                self._heartbeat(workflow, relations_join="disabled")
            load_relations_sec = round(time.perf_counter() - t_load_r, 3)
            self._mark(workflow, "Load Relations", "SUCCESS")

            # DQ discontinuities
            dq = list(
                self.session.scalars(
                    select(DataQualityIssue).where(
                        DataQualityIssue.issue_type == "abnormal_price_jump",
                        DataQualityIssue.resolved_at.is_(None),
                    )
                )
            )
            disc_by_inst: dict[int, set[date]] = {}
            for issue in dq:
                if issue.instrument_id is None or issue.timestamp is None:
                    continue
                disc_by_inst.setdefault(issue.instrument_id, set()).add(issue.timestamp.date())

            mechanical_label = uses_mechanical_label_basis(spec.label_spec)
            label_price_basis = "mechanical_adjusted" if mechanical_label else "raw"
            actions_by_inst: dict[int, list[MechanicalAction]] = {}
            if mechanical_label and inst_ids:
                for instrument_id in inst_ids:
                    actions_by_inst[instrument_id] = load_mechanical_actions(self.session, instrument_id)

            candles_by_inst: dict[int, list[PriceObservation]] = {}
            if inst_ids:
                all_candles = list(
                    self.session.scalars(
                        select(Candle)
                        .where(Candle.instrument_id.in_(inst_ids), Candle.timeframe == "1d")
                        .order_by(Candle.instrument_id, Candle.timestamp)
                    )
                )
                for candle in all_candles:
                    candles_by_inst.setdefault(candle.instrument_id, []).append(
                        PriceObservation(
                            date=candle.timestamp.date(),
                            close=float(candle.close),
                            candle_id=candle.id,
                        )
                    )

            horizons = list((spec.label_spec or {}).get("horizons", [1, 5, 10, 20]))
            label_calc = ForwardReturnLabelCalculator(horizons)
            validator = PITDatasetValidator(list(spec.feature_manifest or []))

            self._mark(workflow, "Build PIT features", "RUNNING")
            samples: list[DatasetSampleV1] = []
            sample_hashes: list[str] = []
            persist_rows: list[dict[str, Any]] = []

            counters = {
                "core_invalid": 0,
                "technical_missing": 0,
                "relation_missing": 0,
                "invalid_labels": 0,
                "eligible_1d": 0,
                "eligible_5d": 0,
                "eligible_10d": 0,
                "eligible_20d": 0,
                "rel_expected_feature_slots": 0,
                "rel_available_feature_slots": 0,
                "rel_expected_context_slots": 0,
                "rel_available_context_slots": 0,
                "rel_context_hits": {},
                "rel_context_available": {},
                "feature_missing": {},
                "label_valid": {"1d": 0, "5d": 0, "10d": 0, "20d": 0},
                "discontinuity_labels": 0,
                "mechanical_ca_normalized_labels": 0,
                "feature_valid_samples": 0,
                "rejected_before_eligible_from": 0,
                "rejected_after_eligible_to": 0,
                "labels_rejected_after_eligible_to": 0,
                "samples_from_inactive_now": 0,
                "instruments_with_samples": set(),
                "inactive_instruments_with_samples": set(),
                "by_year": {},
            }
            universe_version = str(
                (spec.parameters or {}).get("historical_universe_version")
                or (
                    HISTORICAL_EQUITY_UNIVERSE_V2
                    if apply_date_eligibility
                    else str(spec.universe_policy or "")
                )
            )
            for ctx in relation_contexts:
                counters["rel_context_available"][ctx["key"]] = 0
                counters["rel_context_hits"][ctx["key"]] = 0
            timings = {
                "universe_sec": universe_sec,
                "analytics_sec": load_analytics_sec,
                "technical_sec": load_technical_sec,
                "relations_sec": load_relations_sec,
                "load_analytics_sec": load_analytics_sec,
                "load_technical_sec": load_technical_sec,
                "load_relations_sec": load_relations_sec,
                "labels_sec": 0.0,
                "validation_sec": 0.0,
                "persistence_sec": 0.0,
            }
            t_build = time.perf_counter()
            labels_sec_acc = 0.0
            value_hashes: list[str] = []

            total = len(instruments)
            for idx, inst in enumerate(instruments):
                if (
                    relations_enabled
                    and relation_set_row is not None
                    and relation_windows
                    and idx % relation_instrument_batch == 0
                ):
                    t_batch_r = time.perf_counter()
                    batch = instruments[idx : idx + relation_instrument_batch]
                    batch_subject_ids = [
                        subject_input_by_instrument[i.id]
                        for i in batch
                        if i.id in subject_input_by_instrument
                    ]
                    pair_ids = [
                        (subj_id, ctx_id)
                        for subj_id in batch_subject_ids
                        for ctx_id in context_input_ids.values()
                        if subj_id != ctx_id
                    ]
                    lag_snap_count = 0
                    if pair_ids:
                        snapshots = load_relation_snapshots_for_join(
                            self.session,
                            relation_set_id=relation_set_row.id,
                            relation_set_version=spec.relation_set_version,
                            pair_ids=pair_ids,
                            windows=relation_windows,
                            date_from=date_from,
                            date_to=effective_to,
                            lookback_days=max_relation_age_days + 1,
                        )
                        # Lag features only attach to lag_window snapshots (typically 60).
                        lag_snap_ids = [
                            snap.id
                            for snap in snapshots
                            if int(snap.window_observations) in relation_lag_windows
                        ]
                        lag_snap_count = len(lag_snap_ids)
                        lags_by_snapshot = load_lag_metrics_for_snapshots(
                            self.session,
                            lag_snap_ids,
                            lags=relation_lags or None,
                        )
                        relation_index = RelationIndex.build(snapshots, lags_by_snapshot)
                    else:
                        relation_index = RelationIndex.build([], {})
                    load_relations_sec = round(
                        load_relations_sec + (time.perf_counter() - t_batch_r), 3
                    )
                    timings["load_relations_sec"] = load_relations_sec
                    self._heartbeat(
                        workflow,
                        relation_batch_offset=idx,
                        relation_batch_instruments=[i.symbol for i in batch],
                        relation_snapshots=len(relation_index.by_pair_window),
                        relation_lag_snapshots=lag_snap_count,
                        samples_assembled=len(samples),
                    )

                basic_map = basic_by_inst.get(inst.id, {})
                tech_map = tech_by_inst.get(inst.id, {})
                sig_map = signal_by_inst.get(inst.id, {})
                prices = candles_by_inst.get(inst.id, [])
                disc = disc_by_inst.get(inst.id, set()) | {
                    d
                    for d, r in basic_map.items()
                    if (r.quality_flags or {}).get("price_discontinuity")
                }

                as_of_dates = sorted(
                    d for d in basic_map.keys() if date_from <= d <= effective_to
                )
                elig = eligibility_by_id.get(inst.id) if apply_date_eligibility else None
                for as_of in as_of_dates:
                    if apply_date_eligibility:
                        if elig is None:
                            counters["rejected_before_eligible_from"] += 1
                            continue
                        if as_of < elig.eligible_from:
                            counters["rejected_before_eligible_from"] += 1
                            continue
                        if elig.eligible_to is not None and as_of > elig.eligible_to:
                            counters["rejected_after_eligible_to"] += 1
                            continue

                    basic = select_exact_as_of(basic_map, as_of)
                    technical = select_exact_as_of(tech_map, as_of)
                    signal = select_exact_as_of(sig_map, as_of)

                    feature_values, direction = merge_phase1_features(basic, technical, signal)
                    meta: dict[str, Any] = {}
                    if direction is not None:
                        meta["technical_direction"] = direction
                    quality_flags: dict[str, Any] = {}
                    if basic is not None:
                        quality_flags.update(basic.quality_flags or {})
                    if technical is not None:
                        quality_flags.update(technical.quality_flags or {})
                    if signal is not None:
                        quality_flags.update(signal.quality_flags or {})

                    if relations_enabled:
                        rel_join = extract_all_relation_features(
                            contexts=relation_contexts,
                            subject_input_id=subject_input_by_instrument.get(inst.id),
                            context_input_ids=context_input_ids,
                            index=relation_index,
                            as_of=as_of,
                            max_age_days=max_relation_age_days,
                        )
                    else:
                        rel_join = empty_relation_join(relation_contexts, reason="disabled")
                    feature_values.update(rel_join.features)
                    quality_flags.update(rel_join.quality_flags)
                    quality_flags["relations_enabled"] = relations_enabled
                    quality_flags["relations_optional"] = relations_optional
                    quality_flags["max_relation_age_days"] = max_relation_age_days
                    if rel_join.as_of_date is not None:
                        meta["relation_as_of_date"] = rel_join.as_of_date.isoformat()
                    if rel_join.age_days is not None:
                        meta["relation_age_days"] = rel_join.age_days

                    label_prices = prices
                    if apply_date_eligibility and elig is not None:
                        label_prices = _clip_prices_to_eligibility(prices, elig)
                    t_label = time.perf_counter()
                    label_result = label_calc.calculate(
                        label_prices,
                        as_of=as_of,
                        discontinuity_dates=disc,
                        mechanical_actions=actions_by_inst.get(inst.id, []),
                        price_basis=label_price_basis,
                    )
                    if (
                        apply_date_eligibility
                        and elig is not None
                        and elig.eligible_to is not None
                    ):
                        n_rejected = _invalidate_labels_past_eligible_to(
                            label_result,
                            full_prices=prices,
                            as_of=as_of,
                            eligible_to=elig.eligible_to,
                            horizons=horizons,
                        )
                        counters["labels_rejected_after_eligible_to"] += n_rejected
                    labels_sec_acc += time.perf_counter() - t_label

                    core_valid = bool(basic and basic.is_valid)
                    tech_available = bool(
                        technical and technical.is_valid and signal and signal.is_valid
                    )
                    if not core_valid:
                        counters["core_invalid"] += 1
                    else:
                        counters["feature_valid_samples"] += 1
                    if not tech_available:
                        counters["technical_missing"] += 1
                    for ctx_key, ctx_meta in (rel_join.context_meta or {}).items():
                        counters["rel_context_hits"][ctx_key] = counters["rel_context_hits"].get(ctx_key, 0) + 1
                        if ctx_meta.get("available"):
                            counters["rel_context_available"][ctx_key] = (
                                counters["rel_context_available"].get(ctx_key, 0) + 1
                            )
                    sample_relation_missing = is_sample_relation_missing(
                        relations_enabled=relations_enabled,
                        relations_available=rel_join.available,
                    )
                    if sample_relation_missing:
                        counters["relation_missing"] += 1
                    quality_flags["relation_missing"] = sample_relation_missing
                    counters["rel_expected_feature_slots"] = (
                        counters.get("rel_expected_feature_slots", 0) + rel_join.expected_feature_count
                    )
                    counters["rel_available_feature_slots"] = (
                        counters.get("rel_available_feature_slots", 0) + rel_join.available_feature_count
                    )
                    counters["rel_expected_context_slots"] = (
                        counters.get("rel_expected_context_slots", 0) + rel_join.expected_context_count
                    )
                    counters["rel_available_context_slots"] = (
                        counters.get("rel_available_context_slots", 0) + rel_join.available_context_count
                    )

                    for fk, fv in feature_values.items():
                        if fv is None:
                            counters["feature_missing"][fk] = counters["feature_missing"].get(fk, 0) + 1

                    training_eligible: dict[str, bool] = {}
                    for h in horizons:
                        key = f"{h}d"
                        label_ok = bool(label_result.label_valid.get(key))
                        if not label_ok:
                            counters["invalid_labels"] += 1
                        else:
                            counters["label_valid"][key] = counters["label_valid"].get(key, 0) + 1
                        eligible = is_horizon_training_eligible(
                            core_valid=core_valid,
                            technical_available=tech_available,
                            label_valid=label_ok,
                            relations_optional=relations_optional,
                            relations_available=rel_join.available,
                        )
                        training_eligible[f"training_eligible_{key}"] = eligible
                        if eligible:
                            counters[f"eligible_{key}"] = counters.get(f"eligible_{key}", 0) + 1
                    if any(
                        str(flag).startswith("price_discontinuity")
                        for flag in (label_result.label_flags or {})
                    ):
                        counters["discontinuity_labels"] += 1
                    if any(
                        str(flag).startswith("mechanical_ca_normalized_")
                        for flag in (label_result.label_flags or {})
                    ):
                        counters["mechanical_ca_normalized_labels"] = (
                            counters.get("mechanical_ca_normalized_labels", 0) + 1
                        )

                    quality = DatasetQualityV1(
                        feature_state_valid=core_valid,
                        technical_available=tech_available,
                        relations_available=rel_join.available,
                        quality_flags=quality_flags,
                        label_valid=dict(label_result.label_valid),
                        training_eligible=training_eligible,
                        relation_age_days=rel_join.age_days,
                        relation_as_of_date=rel_join.as_of_date,
                    )

                    lineage = DatasetLineageV1(
                        basic_feature_id=basic.id if basic else None,
                        basic_feature_set_code=spec.basic_feature_set_code,
                        basic_feature_set_version=spec.basic_feature_set_version,
                        basic_feature_date=basic.date if basic else None,
                        technical_feature_id=technical.id if technical else None,
                        technical_feature_set_code=spec.technical_feature_set_code,
                        technical_feature_set_version=spec.technical_feature_set_version,
                        technical_feature_date=technical.date if technical else None,
                        technical_signal_id=signal.id if signal else None,
                        technical_model_code=spec.technical_model_code,
                        technical_model_version=spec.technical_model_version,
                        technical_model_config_hash=spec.technical_model_config_hash,
                        technical_signal_as_of=signal.as_of_date if signal else None,
                        relation_set_code=spec.relation_set_code,
                        relation_set_version=spec.relation_set_version,
                        relation_snapshot_ids=rel_join.snapshot_ids,
                        relation_as_of_dates=rel_join.as_of_dates,
                        label_close_t_candle_id=label_result.close_t_candle_id,
                        label_target_candle_ids=label_result.target_candle_ids,
                        dataset_spec_code=spec.code,
                        dataset_spec_version=spec.version,
                    )

                    universe_meta = eligibility_audit(
                        elig,
                        as_of=as_of,
                        policy=str(spec.universe_policy or ""),
                        version=universe_version,
                    )
                    sample = DatasetSampleV1(
                        instrument_id=inst.id,
                        ticker=inst.symbol,
                        as_of_date=as_of,
                        features=DatasetFeatureVectorV1(values=feature_values),
                        labels=label_result.labels,
                        lineage=lineage,
                        quality=quality,
                        metadata={
                            **meta,
                            "label_flags": label_result.label_flags,
                            "relations_join": "enabled" if relations_enabled else "disabled",
                            "relation_contexts": rel_join.context_meta,
                            **universe_meta,
                        },
                    )
                    pit = validator.validate_sample(sample)
                    quality.pit_pass = pit.ok
                    quality.pit_violations = list(pit.violations)
                    if not pit.ok:
                        # Fail hard after collecting all? Spec: FAIL the run
                        samples.append(sample)
                        # continue collecting to report, then raise
                    else:
                        samples.append(sample)

                    counters["instruments_with_samples"].add(inst.id)
                    if not inst.is_active:
                        counters["samples_from_inactive_now"] += 1
                        counters["inactive_instruments_with_samples"].add(inst.id)
                    year_key = str(as_of.year)
                    year_bucket = counters["by_year"].setdefault(
                        year_key,
                        {
                            "year": as_of.year,
                            "samples": 0,
                            "sampled_instruments": set(),
                            "inactive_now_instruments": set(),
                            "training_eligible": {"1d": 0, "5d": 0, "10d": 0, "20d": 0},
                            "label_valid": {"1d": 0, "5d": 0, "10d": 0, "20d": 0},
                        },
                    )
                    year_bucket["samples"] += 1
                    year_bucket["sampled_instruments"].add(inst.id)
                    if not inst.is_active:
                        year_bucket["inactive_now_instruments"].add(inst.id)
                    for h in horizons:
                        key = f"{h}d"
                        if bool(label_result.label_valid.get(key)):
                            year_bucket["label_valid"][key] = (
                                year_bucket["label_valid"].get(key, 0) + 1
                            )
                        if training_eligible.get(f"training_eligible_{key}"):
                            year_bucket["training_eligible"][key] = (
                                year_bucket["training_eligible"].get(key, 0) + 1
                            )

                    features_dict = sample.features.to_dict()
                    labels_dict = sample.labels.to_dict()
                    lineage_dict = sample.lineage.to_dict()
                    # Audit-only: eligible_to must never enter X(t) / content hash identity.
                    lineage_dict.update(universe_meta)
                    ch = sample_content_hash(
                        instrument_id=inst.id,
                        as_of_date=as_of.isoformat(),
                        features=features_dict,
                        labels=labels_dict,
                        lineage_identity={
                            "basic_feature_id": lineage.basic_feature_id,
                            "technical_feature_id": lineage.technical_feature_id,
                            "technical_signal_id": lineage.technical_signal_id,
                            "relation_snapshot_ids": lineage.relation_snapshot_ids,
                            "label_close_t_candle_id": lineage.label_close_t_candle_id,
                            "label_target_candle_ids": lineage.label_target_candle_ids,
                            "dataset_spec": f"{spec.code}:v{spec.version}",
                        },
                    )
                    sample_hashes.append(ch)
                    vh = sample_values_hash(
                        instrument_id=inst.id,
                        as_of_date=as_of.isoformat(),
                        features=features_dict,
                        labels=labels_dict,
                    )
                    value_hashes.append(vh)
                    persist_rows.append(
                        sample_row(
                            dataset_run_id=dataset_run.id,
                            dataset_spec_id=spec.id,
                            instrument_id=inst.id,
                            as_of_date=as_of,
                            features=features_dict,
                            labels=labels_dict,
                            feature_quality=quality.to_feature_quality_dict(),
                            label_quality={
                                **quality.to_label_quality_dict(),
                                "flags": label_result.label_flags,
                            },
                            training_eligibility=quality.to_eligibility_dict(),
                            lineage=lineage_dict,
                            content_hash=ch,
                        )
                    )

                self._heartbeat(
                    workflow,
                    processed_instruments=idx + 1,
                    total_instruments=total,
                    current_instrument=inst.symbol,
                    samples_built=len(samples),
                    elapsed=round(time.perf_counter() - started, 2),
                )

            timings["build_sec"] = round(time.perf_counter() - t_build, 3)
            self._mark(workflow, "Build PIT features", "SUCCESS")
            self._mark(workflow, "Build labels", "SUCCESS")
            self._mark(workflow, "Apply quality", "SUCCESS")

            self._mark(workflow, "Run PIT validation", "RUNNING")
            batch_pit = validator.validate_batch(samples)
            dataset_run.pit_violations = len(batch_pit.violations)
            if not batch_pit.ok:
                dataset_run.pit_status = "FAILED"
                dataset_run.status = "ERROR"
                dataset_run.error_message = "; ".join(batch_pit.violations[:20])
                dataset_run.finished_at = datetime.now(UTC)
                write_event(
                    self.session,
                    level="ERROR",
                    component="dataset",
                    event_type="dataset.pit_validation_failed",
                    message=dataset_run.error_message[:500],
                    workflow_id=workflow.id,
                )
                self._mark(workflow, "Run PIT validation", "ERROR")
                finish_workflow(self.session, workflow, "ERROR", error=dataset_run.error_message)
                self.session.commit()
                raise RuntimeError(f"PIT validation failed: {dataset_run.error_message}")
            dataset_run.pit_status = "PASS"
            self._mark(workflow, "Run PIT validation", "SUCCESS")

            self._mark(workflow, "Materialize samples", "RUNNING")
            t_persist = time.perf_counter()
            batch_size = 1000
            for i in range(0, len(persist_rows), batch_size):
                insert_dataset_samples(self.session, persist_rows[i : i + batch_size])
                self._heartbeat(
                    workflow,
                    samples_built=min(i + batch_size, len(persist_rows)),
                    elapsed=round(time.perf_counter() - started, 2),
                )
            timings["persist_sec"] = round(time.perf_counter() - t_persist, 3)
            self._mark(workflow, "Materialize samples", "SUCCESS")

            self._mark(workflow, "Calculate hashes", "RUNNING")
            d_hash = dataset_hash(
                dataset_spec_code=spec.code,
                dataset_spec_version=spec.version,
                date_from=date_from.isoformat(),
                date_to=effective_to.isoformat(),
                sample_hashes=sample_hashes,
            )
            dataset_run.dataset_hash = d_hash
            v_hash = dataset_values_hash(
                dataset_spec_code=spec.code,
                dataset_spec_version=spec.version,
                date_from=date_from.isoformat(),
                date_to=effective_to.isoformat(),
                sample_hashes=value_hashes,
            )
            self._mark(workflow, "Calculate hashes", "SUCCESS")

            n_samples = max(len(samples), 1)
            expected_feat = max(int(counters.get("rel_expected_feature_slots", 0)), 1)
            expected_ctx = max(int(counters.get("rel_expected_context_slots", 0)), 1)
            by_context = {}
            for ctx in relation_contexts:
                key = ctx["key"]
                hits = int(counters["rel_context_hits"].get(key, 0))
                avail = int(counters["rel_context_available"].get(key, 0))
                by_context[key] = {
                    "input_code": ctx.get("input_code"),
                    "available": avail,
                    "expected": hits or n_samples,
                    "coverage_pct": round(100.0 * avail / max(hits or n_samples, 1), 2),
                }
            timings["total_sec"] = round(time.perf_counter() - started, 3)
            coverage = {
                "features": {
                    "valid_samples": counters["feature_valid_samples"],
                    "core_invalid": counters["core_invalid"],
                    "top_missing": sorted(counters["feature_missing"].items(), key=lambda x: -x[1])[:15],
                },
                "technical_coverage_pct": round(
                    100.0 * (len(samples) - counters["technical_missing"]) / n_samples, 2
                ),
                "relations": {
                    "join": "enabled" if relations_enabled else "disabled",
                    "relations_enabled": relations_enabled,
                    "expected_features_per_sample": len(relation_feature_names(relation_contexts)),
                    "available_feature_slots": counters.get("rel_available_feature_slots", 0),
                    "expected_feature_slots": counters.get("rel_expected_feature_slots", 0),
                    "feature_coverage_pct": round(
                        100.0 * counters.get("rel_available_feature_slots", 0) / expected_feat, 2
                    ),
                    "available_context_slots": counters.get("rel_available_context_slots", 0),
                    "expected_context_slots": counters.get("rel_expected_context_slots", 0),
                    "context_coverage_pct": round(
                        100.0 * counters.get("rel_available_context_slots", 0) / expected_ctx, 2
                    ),
                    "by_context": by_context,
                    "samples_missing_all_relations": counters["relation_missing"],
                    "max_relation_age_days": max_relation_age_days,
                },
                "labels": {
                    "valid": counters["label_valid"],
                    "invalid": counters["invalid_labels"],
                    "discontinuity_exclusions": counters["discontinuity_labels"],
                    "mechanical_ca_normalized_labels": counters.get(
                        "mechanical_ca_normalized_labels", 0
                    ),
                    "labels_rejected_after_eligible_to": counters.get(
                        "labels_rejected_after_eligible_to", 0
                    ),
                    "eligible": {
                        "1d": counters.get("eligible_1d", 0),
                        "5d": counters.get("eligible_5d", 0),
                        "10d": counters.get("eligible_10d", 0),
                        "20d": counters.get("eligible_20d", 0),
                    },
                },
                "universe": {
                    "policy": spec.universe_policy,
                    "historical_candidate_instruments": len(eligibility_by_id)
                    if apply_date_eligibility
                    else len(instruments),
                    "instruments_with_samples": len(counters["instruments_with_samples"]),
                    "inactive_instruments_with_samples": len(
                        counters["inactive_instruments_with_samples"]
                    ),
                    "samples_from_currently_inactive_instruments": counters[
                        "samples_from_inactive_now"
                    ],
                    "samples_rejected_before_eligible_from": counters[
                        "rejected_before_eligible_from"
                    ],
                    "samples_rejected_after_eligible_to": counters["rejected_after_eligible_to"],
                    "labels_rejected_after_eligible_to": counters.get(
                        "labels_rejected_after_eligible_to", 0
                    ),
                    "missing_feature_rows": counters["core_invalid"],
                    "missing_technical_rows": counters["technical_missing"],
                    "invalid_labels": counters["invalid_labels"],
                    "pit_violations": 0,
                    "boundary_quality": {
                        "eligible_from_quality_counts": resolved_universe.get(
                            "eligible_from_quality_counts"
                        ),
                        "eligible_to_quality_counts": resolved_universe.get(
                            "eligible_to_quality_counts"
                        ),
                        "universe_quality": resolved_universe.get("universe_quality"),
                        "proxy_boundaries": resolved_universe.get("proxy_boundaries"),
                        "authoritative_boundaries": resolved_universe.get(
                            "authoritative_boundaries"
                        ),
                    },
                },
                "by_year": _build_year_coverage(
                    by_year=counters["by_year"],
                    eligibility_by_id=eligibility_by_id if apply_date_eligibility else {},
                    date_from=date_from,
                    date_to=effective_to,
                ),
                "timings": timings,
                "top_missing_features": sorted(
                    counters["feature_missing"].items(), key=lambda x: -x[1]
                )[:15],
            }
            if apply_date_eligibility and int(spec.version) == PIT_DAILY_CORE_V3_VERSION:
                year_rows = coverage["by_year"]
                coverage["research_quality"] = grade_v3_core_research_quality(
                    samples_total=len(samples),
                    apply_date_eligibility=True,
                    resolved_universe=resolved_universe,
                    universe_cov=coverage["universe"],
                    by_year=year_rows,
                )
                # Align stage timing keys for research diagnostics (additive).
                timings.setdefault("universe_sec", timings.get("load_universe_sec"))
                timings.setdefault("analytics_sec", timings.get("load_analytics_sec"))
                timings.setdefault("technical_sec", timings.get("load_technical_sec"))
                timings.setdefault("relations_sec", timings.get("load_relations_sec"))
                timings.setdefault("labels_sec", timings.get("build_sec"))
                timings.setdefault("validation_sec", None)
                timings.setdefault("persistence_sec", timings.get("persist_sec"))

            manifest = {
                "dataset_code": spec.code,
                "dataset_version": spec.version,
                "dataset_hash": d_hash,
                "values_hash": v_hash,
                "hash_policy": {
                    "dataset_hash": "features+labels+lineage_surrogate_ids",
                    "values_hash": "features+labels_only_no_row_ids",
                },
                "date_from": date_from.isoformat(),
                "date_to": effective_to.isoformat(),
                "universe": resolved_universe,
                "feature_columns": sorted(k for k in (persist_rows[0]["features"] if persist_rows else {})),
                "label_columns": ["forward_return_1d", "forward_return_5d", "forward_return_10d", "forward_return_20d"],
                "source_versions": {
                    "basic": f"{spec.basic_feature_set_code} v{spec.basic_feature_set_version}",
                    "technical_features": f"{spec.technical_feature_set_code} v{spec.technical_feature_set_version}",
                    "technical_model": f"{spec.technical_model_code} v{spec.technical_model_version}",
                    "technical_model_config_hash": spec.technical_model_config_hash,
                    "relations": f"{spec.relation_set_code} v{spec.relation_set_version}",
                    "relations_join": "enabled" if relations_enabled else "disabled",
                },
                "relation_contexts": spec.relation_contexts,
                "quality_policy": spec.quality_policy,
                "label_formula": spec.label_spec,
                "sample_counts": {
                    "total": len(samples),
                    "eligible_1d": counters.get("eligible_1d", 0),
                    "eligible_5d": counters.get("eligible_5d", 0),
                    "eligible_10d": counters.get("eligible_10d", 0),
                    "eligible_20d": counters.get("eligible_20d", 0),
                },
                "pit_status": "PASS",
                "created_at": datetime.now(UTC).isoformat(),
            }

            self._mark(workflow, "Persist summary", "RUNNING")
            dataset_run.samples_total = len(samples)
            dataset_run.eligible_1d = counters.get("eligible_1d", 0)
            dataset_run.eligible_5d = counters.get("eligible_5d", 0)
            dataset_run.eligible_10d = counters.get("eligible_10d", 0)
            dataset_run.eligible_20d = counters.get("eligible_20d", 0)
            dataset_run.core_invalid = counters["core_invalid"]
            dataset_run.technical_missing = counters["technical_missing"]
            dataset_run.relation_missing = counters["relation_missing"]
            dataset_run.invalid_labels = counters["invalid_labels"]
            dataset_run.coverage_summary = coverage
            dataset_run.manifest = manifest
            dataset_run.source_watermark = {
                "latest_market_date": effective_to.isoformat(),
                "basic_feature_set": {"code": basic_fs.code, "version": basic_fs.version, "id": str(basic_fs.id)},
                "technical_feature_set": {"code": tech_fs.code, "version": tech_fs.version, "id": str(tech_fs.id)},
                "relation_set": {
                    "code": spec.relation_set_code,
                    "version": spec.relation_set_version,
                    "id": str(relation_set_row.id) if relation_set_row is not None else None,
                    "join": "enabled" if relations_enabled else "disabled",
                    "pit": "snapshot.as_of_date",
                    "run_source_watermark": "compute_lineage_not_pit",
                },
                "technical_model": {
                    "code": spec.technical_model_code,
                    "version": spec.technical_model_version,
                    "config_hash": spec.technical_model_config_hash,
                },
            }
            dataset_run.status = "SUCCESS"
            dataset_run.finished_at = datetime.now(UTC)
            self._mark(workflow, "Persist summary", "SUCCESS")
            self._mark(workflow, "Finish", "SUCCESS")
            finish_workflow(self.session, workflow, "SUCCESS")
            write_event(
                self.session,
                level="INFO",
                component="dataset",
                event_type="dataset.build_completed",
                message=f"Dataset build completed samples={len(samples)} hash={d_hash[:12]}",
                details={
                    "samples": len(samples),
                    "dataset_hash": d_hash,
                    "duration_sec": round(time.perf_counter() - started, 2),
                },
                workflow_id=workflow.id,
                trace_id=(workflow.meta or {}).get("trace_id"),
            )
            self.session.commit()
            return {
                "workflow_id": workflow.id,
                "dataset_run_id": dataset_run.id,
                "samples_total": len(samples),
                "dataset_hash": d_hash,
                "values_hash": v_hash,
                "pit_status": "PASS",
                "duration_sec": round(time.perf_counter() - started, 2),
                "eligible_1d": dataset_run.eligible_1d,
                "eligible_5d": dataset_run.eligible_5d,
                "eligible_10d": dataset_run.eligible_10d,
                "eligible_20d": dataset_run.eligible_20d,
            }
        except Exception as exc:
            logger.exception("dataset_build_failed")
            write_event(
                self.session,
                level="ERROR",
                component="dataset",
                event_type="dataset.build_failed",
                message=str(exc)[:500],
                workflow_id=workflow.id if workflow else None,
            )
            if dataset_run is not None:
                dataset_run.status = "ERROR"
                dataset_run.error_message = str(exc)[:2000]
                dataset_run.finished_at = datetime.now(UTC)
            try:
                finish_workflow(self.session, workflow, "ERROR", error=str(exc)[:2000])
            except Exception:
                pass
            self.session.commit()
            raise

    def _resolve_workflow(self, workflow_id: int | None) -> Workflow:
        if workflow_id is not None:
            workflow = self.session.get(Workflow, workflow_id)
            if workflow is None:
                raise ValueError(f"Workflow {workflow_id} not found")
            return workflow
        return create_workflow(self.session, "DatasetBuild", "DatasetBuild", DATASET_BUILD_STEPS)
