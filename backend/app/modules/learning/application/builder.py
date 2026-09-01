"""PITDatasetBuilder — assemble X(t) and Y(t+h) with version pins and PIT validation."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application.system.event_log import write_event
from app.core.logging import get_logger
from app.infrastructure.analytics.models import InstrumentFeatureDaily
from app.infrastructure.learning.models import DatasetRun, DatasetSpec
from app.infrastructure.learning.repository import insert_dataset_samples, sample_row
from app.infrastructure.market.models import Candle, DataQualityIssue, Instrument, Workflow
from app.infrastructure.technical.models import InstrumentTechnicalFeatureDaily, TechnicalSignalDaily
from app.modules.analytics.application.resolve import resolve_feature_set
from app.modules.analytics.application.seed import seed_feature_sets
from app.modules.learning.application.contracts import (
    DatasetFeatureVectorV1,
    DatasetLineageV1,
    DatasetQualityV1,
    DatasetSampleV1,
)
from app.modules.learning.application.hash_util import dataset_hash, sample_content_hash
from app.modules.learning.application.labels import ForwardReturnLabelCalculator, PriceObservation
from app.modules.learning.application.seed import seed_dataset_specs
from app.modules.learning.application.source_join import merge_phase1_features, select_exact_as_of
from app.modules.learning.application.validator import PITDatasetValidator, assert_manifest_separation
from app.modules.learning.dataset_config import (
    DATASET_BUILD_STEPS,
    PHASE1_RELATIONS_JOIN_ENABLED,
    PIT_DAILY_CORE_CODE,
    PIT_DAILY_CORE_VERSION,
)
from app.modules.market.application.workflows import create_workflow, finish_workflow, get_step, update_step

logger = get_logger(__name__, component="dataset-pit")


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
    ) -> dict[str, Any]:
        started = time.perf_counter()
        workflow = self._resolve_workflow(workflow_id)
        dataset_run: DatasetRun | None = None

        try:
            self._mark(workflow, "Resolve dataset spec", "RUNNING")
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
            # Pins stay on the spec; Relations join is Phase 2.
            self._mark(workflow, "Resolve pinned source versions", "SUCCESS")

            self._mark(workflow, "Resolve universe", "RUNNING")
            q = select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.id)
            if instrument_ids:
                q = q.where(Instrument.id.in_(instrument_ids))
            instruments = list(self.session.scalars(q))
            resolved_universe = {
                "policy": spec.universe_policy,
                "instrument_ids": [i.id for i in instruments],
                "symbols": [i.symbol for i in instruments],
                "note": "current_active_instruments may contain survivorship bias; PIT universe history is future work",
            }
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
            self._mark(workflow, "Load Analytics", "SUCCESS")

            self._mark(workflow, "Load Technical", "RUNNING")
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
            self._mark(workflow, "Load Technical", "SUCCESS")

            self._mark(workflow, "Load Relations", "RUNNING")
            if PHASE1_RELATIONS_JOIN_ENABLED:
                raise RuntimeError("Relations join is not enabled in Dataset/PIT Phase 1")
            self._heartbeat(workflow, relations_join="disabled_phase1")
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
                "rel_context_hits": {},
                "feature_missing": {},
            }

            total = len(instruments)
            for idx, inst in enumerate(instruments):
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
                for as_of in as_of_dates:
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

                    label_result = label_calc.calculate(prices, as_of=as_of, discontinuity_dates=disc)

                    core_valid = bool(basic and basic.is_valid)
                    tech_available = bool(
                        technical and technical.is_valid and signal and signal.is_valid
                    )
                    if not core_valid:
                        counters["core_invalid"] += 1
                    if not tech_available:
                        counters["technical_missing"] += 1
                    counters["relation_missing"] += 1

                    for fk, fv in feature_values.items():
                        if fv is None:
                            counters["feature_missing"][fk] = counters["feature_missing"].get(fk, 0) + 1

                    training_eligible: dict[str, bool] = {}
                    for h in horizons:
                        key = f"{h}d"
                        label_ok = bool(label_result.label_valid.get(key))
                        if not label_ok:
                            counters["invalid_labels"] += 1
                        eligible = core_valid and tech_available and label_ok
                        training_eligible[f"training_eligible_{key}"] = eligible
                        if eligible:
                            counters[f"eligible_{key}"] = counters.get(f"eligible_{key}", 0) + 1

                    quality = DatasetQualityV1(
                        feature_state_valid=core_valid,
                        technical_available=tech_available,
                        relations_available=False,
                        quality_flags=quality_flags,
                        label_valid=dict(label_result.label_valid),
                        training_eligible=training_eligible,
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
                        label_close_t_candle_id=label_result.close_t_candle_id,
                        label_target_candle_ids=label_result.target_candle_ids,
                        dataset_spec_code=spec.code,
                        dataset_spec_version=spec.version,
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
                            "relations_join": "disabled_phase1",
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

                    features_dict = sample.features.to_dict()
                    labels_dict = sample.labels.to_dict()
                    lineage_dict = sample.lineage.to_dict()
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
            # batch insert
            batch_size = 1000
            for i in range(0, len(persist_rows), batch_size):
                insert_dataset_samples(self.session, persist_rows[i : i + batch_size])
                self._heartbeat(
                    workflow,
                    samples_built=min(i + batch_size, len(persist_rows)),
                    elapsed=round(time.perf_counter() - started, 2),
                )
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
            self._mark(workflow, "Calculate hashes", "SUCCESS")

            coverage = {
                "relations": {
                    "join": "disabled_phase1",
                    "coverage_pct": 0.0,
                },
                "technical_coverage_pct": round(
                    100.0 * (len(samples) - counters["technical_missing"]) / max(len(samples), 1), 2
                ),
                "top_missing_features": sorted(
                    counters["feature_missing"].items(), key=lambda x: -x[1]
                )[:15],
            }

            manifest = {
                "dataset_code": spec.code,
                "dataset_version": spec.version,
                "dataset_hash": d_hash,
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
                    "relations_join": "disabled_phase1",
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
                    "join": "disabled_phase1",
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
