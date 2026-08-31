"""Relations compute orchestration — LATEST / BACKFILL."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application.system.event_log import write_event
from app.core.logging import get_logger
from app.infrastructure.analytics.models import FeatureSet, InstrumentFeatureDaily, SeriesFeatureDaily
from app.infrastructure.analytics.relation_models import RelationInput, RelationRun, RelationSet, RelationSnapshot
from app.infrastructure.analytics.relation_repository import persist_pair_results
from app.infrastructure.market.models import SeriesValue, Workflow
from app.modules.analytics.application.alignment import DatedValue
from app.modules.market.application.workflows import create_workflow, finish_workflow, get_step, update_step
from app.modules.relations.application.calculator import InputSeries, RelationCalculator
from app.modules.relations.application.resolve import resolve_relation_set
from app.modules.relations.application.seed import seed_relation_inputs, seed_relation_sets
from app.modules.relations.application.transforms import asof_level_then_change
from app.modules.relations.relation_config import RELATIONS_COMPUTE_STEPS

logger = get_logger(__name__, component="relations-compute")


def _iter_as_of_dates(date_from: date, date_to: date, cadence: str) -> list[date]:
    if date_from > date_to:
        return []
    if cadence == "DAILY":
        out: list[date] = []
        cur = date_from
        while cur <= date_to:
            out.append(cur)
            cur += timedelta(days=1)
        return out
    # WEEKLY: Fridays in range, plus date_to if not already included
    out = []
    cur = date_from
    # advance to first Friday
    while cur.weekday() != 4 and cur <= date_to:
        cur += timedelta(days=1)
    while cur <= date_to:
        out.append(cur)
        cur += timedelta(days=7)
    if date_to not in out:
        out.append(date_to)
    return sorted(set(out))


class RelationsComputeService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _mark(self, workflow: Workflow, step_name: str, status: str) -> None:
        """Update workflow step and commit so Control Center polling sees progress."""
        update_step(self.session, get_step(workflow, step_name), status)
        self.session.commit()

    def run_latest(
        self,
        *,
        relation_set_code: str = "basic_relations",
        relation_set_version: int = 1,
        workflow_id: int | None = None,
    ) -> dict[str, Any]:
        return self._run(
            run_type="LATEST",
            as_of_from=None,
            as_of_to=None,
            cadence=None,
            relation_set_code=relation_set_code,
            relation_set_version=relation_set_version,
            workflow_id=workflow_id,
        )

    def run_backfill(
        self,
        *,
        as_of_from: date,
        as_of_to: date | None = None,
        cadence: str = "WEEKLY",
        relation_set_code: str = "basic_relations",
        relation_set_version: int = 1,
        workflow_id: int | None = None,
    ) -> dict[str, Any]:
        return self._run(
            run_type="BACKFILL",
            as_of_from=as_of_from,
            as_of_to=as_of_to,
            cadence=cadence.upper(),
            relation_set_code=relation_set_code,
            relation_set_version=relation_set_version,
            workflow_id=workflow_id,
        )

    def _run(
        self,
        *,
        run_type: str,
        as_of_from: date | None,
        as_of_to: date | None,
        cadence: str | None,
        relation_set_code: str,
        relation_set_version: int,
        workflow_id: int | None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        workflow = self._resolve_workflow(workflow_id, run_type)

        try:
            self._mark(workflow, "Resolve relation set", "RUNNING")
            seed_relation_sets(self.session)
            relation_set = resolve_relation_set(self.session, relation_set_code, relation_set_version)
            calculator = RelationCalculator(relation_set.parameters)
            lookback = int(relation_set.parameters.get("max_lookback_buffer", 160))
            exclude_invalid = bool(relation_set.parameters.get("exclude_invalid_features", True))
            exclude_disc = bool(relation_set.parameters.get("exclude_price_discontinuities", True))
            self._mark(workflow, "Resolve relation set", "SUCCESS")

            self._mark(workflow, "Resolve / seed inputs", "RUNNING")
            seed_relation_inputs(self.session)
            inputs = list(
                self.session.scalars(
                    select(RelationInput).where(RelationInput.is_active.is_(True)).order_by(RelationInput.code)
                )
            )
            if not inputs:
                raise RuntimeError("No active relation inputs after seed")
            self._mark(workflow, "Resolve / seed inputs", "SUCCESS")

            self._mark(workflow, "Resolve as-of dates", "RUNNING")
            feature_set = self.session.scalar(select(FeatureSet).where(FeatureSet.is_active.is_(True)))
            if feature_set is None:
                raise RuntimeError("No active analytics feature set — run FeatureBackfill first")

            max_feat_date = self.session.scalar(
                select(func.max(InstrumentFeatureDaily.date)).where(
                    InstrumentFeatureDaily.feature_set_id == feature_set.id
                )
            )
            source_watermark = self.session.scalar(
                select(func.max(InstrumentFeatureDaily.calculated_at)).where(
                    InstrumentFeatureDaily.feature_set_id == feature_set.id
                )
            )

            if run_type == "LATEST":
                if max_feat_date is None:
                    return self._finish_empty(
                        workflow,
                        relation_set,
                        run_type,
                        as_of_from=None,
                        as_of_to=None,
                        cadence=None,
                        inputs_total=len(inputs),
                        source_watermark=source_watermark,
                        reason="no_feature_data",
                    )
                as_of_dates = [max_feat_date]
                as_of_from = max_feat_date
                as_of_to = max_feat_date
            else:
                assert as_of_from is not None
                end = as_of_to or max_feat_date or as_of_from
                if max_feat_date is not None and end > max_feat_date:
                    end = max_feat_date
                as_of_to = end
                as_of_dates = _iter_as_of_dates(as_of_from, end, cadence or "WEEKLY")
                # Keep only dates that exist in feature calendar (or <= max)
                if max_feat_date is not None:
                    as_of_dates = [d for d in as_of_dates if d <= max_feat_date]
                if not as_of_dates:
                    return self._finish_empty(
                        workflow,
                        relation_set,
                        run_type,
                        as_of_from=as_of_from,
                        as_of_to=as_of_to,
                        cadence=cadence,
                        inputs_total=len(inputs),
                        source_watermark=source_watermark,
                        reason="empty_as_of_range",
                    )

            # NO_CHANGES for LATEST when identical as_of/version/watermark already stored
            if run_type == "LATEST":
                existing = self._find_identical_latest(
                    relation_set.id, as_of_dates[0], source_watermark
                )
                if existing is not None:
                    self._mark(workflow, "Resolve as-of dates", "SUCCESS")
                    for step_name in RELATIONS_COMPUTE_STEPS[3:-1]:
                        self._mark(workflow, step_name, "SUCCESS")
                    run = RelationRun(
                        relation_set_id=relation_set.id,
                        run_type=run_type,
                        as_of_from=as_of_from,
                        as_of_to=as_of_to,
                        cadence=cadence,
                        started_at=datetime.now(UTC),
                        finished_at=datetime.now(UTC),
                        status="NO_CHANGES",
                        inputs_total=len(inputs),
                        source_watermark=source_watermark,
                        workflow_id=workflow.id,
                    )
                    self.session.add(run)
                    self._mark(workflow, "Finish", "SUCCESS")
                    finish_workflow(self.session, workflow, "SUCCESS")
                    self.session.commit()
                    write_event(
                        self.session,
                        level="INFO",
                        component="relations",
                        event_type="relations.compute_no_changes",
                        message="Relations LATEST skipped — same as_of/version/watermark",
                        workflow_id=workflow.id,
                    )
                    self.session.commit()
                    return {
                        "workflow_id": workflow.id,
                        "relation_run_id": run.id,
                        "status": "NO_CHANGES",
                        "as_of_date": as_of_dates[0].isoformat(),
                    }

            self._mark(workflow, "Resolve as-of dates", "SUCCESS")

            relation_run = RelationRun(
                relation_set_id=relation_set.id,
                run_type=run_type,
                as_of_from=as_of_from,
                as_of_to=as_of_to,
                cadence=cadence,
                started_at=datetime.now(UTC),
                status="RUNNING",
                inputs_total=len(inputs),
                source_watermark=source_watermark,
                workflow_id=workflow.id,
            )
            self.session.add(relation_run)
            self.session.flush()

            event_start = (
                "relations.backfill_started" if run_type == "BACKFILL" else "relations.compute_started"
            )
            write_event(
                self.session,
                level="INFO",
                component="relations",
                event_type=event_start,
                message=f"Relations {run_type} started",
                workflow_id=workflow.id,
                trace_id=(workflow.meta or {}).get("trace_id"),
            )

            self._mark(workflow, "Load feature matrix", "RUNNING")
            min_load = min(as_of_dates) - timedelta(days=lookback * 2)
            try:
                series_by_id = self._load_input_matrix(
                    inputs,
                    feature_set_id=feature_set.id,
                    date_from=min_load,
                    date_to=max(as_of_dates),
                    exclude_invalid=exclude_invalid,
                    exclude_discontinuities=exclude_disc,
                )
            except Exception as exc:
                write_event(
                    self.session,
                    level="ERROR",
                    component="relations",
                    event_type="relations.input_resolution_failed",
                    message=str(exc),
                    workflow_id=workflow.id,
                )
                raise
            self._mark(workflow, "Load feature matrix", "SUCCESS")

            self._mark(workflow, "Calculate relations", "RUNNING")
            all_results = []
            input_ids = [inp.id for inp in inputs if inp.id in series_by_id]
            calc_started = time.perf_counter()
            for idx, as_of in enumerate(as_of_dates):
                as_of_t0 = time.perf_counter()
                pair_results = calculator.calculate_as_of(
                    series_by_id, as_of_date=as_of, input_ids=input_ids
                )
                all_results.extend(pair_results)
                # Heartbeat every as_of so watchdog/UI see progress (meta must be in API).
                pairs_expected = (
                    len(input_ids) * max(len(input_ids) - 1, 0) // 2 * len(calculator.windows) * len(as_of_dates)
                )
                workflow.meta = {
                    **(workflow.meta or {}),
                    "as_of_progress": f"{idx + 1}/{len(as_of_dates)}",
                    "as_of_current": as_of.isoformat(),
                    "pairs_done": len(all_results),
                    "pairs_expected": pairs_expected,
                    "last_as_of_calc_s": round(time.perf_counter() - as_of_t0, 2),
                    "calc_elapsed_s": round(time.perf_counter() - calc_started, 2),
                }
                self.session.commit()
            relation_run.pairs_calculated = len(all_results)
            self._mark(workflow, "Calculate relations", "SUCCESS")

            self._mark(workflow, "Persist snapshots", "RUNNING")
            # Larger batches — persist_pair_results is now true bulk SQL
            batch_size = 2000
            totals = {"written": 0, "valid": 0, "invalid": 0, "lags": 0}
            persist_started = time.perf_counter()
            for i in range(0, len(all_results), batch_size):
                batch = all_results[i : i + batch_size]
                stats = persist_pair_results(
                    self.session,
                    relation_run_id=relation_run.id,
                    relation_set_id=relation_set.id,
                    relation_set_version=relation_set.version,
                    results=batch,
                )
                for k in totals:
                    totals[k] += stats[k]
                self.session.commit()
                workflow.meta = {
                    **(workflow.meta or {}),
                    "persist_progress": f"{min(i + batch_size, len(all_results))}/{len(all_results)}",
                    "lags_written": totals["lags"],
                    "persist_elapsed_s": round(time.perf_counter() - persist_started, 2),
                }
                self.session.commit()
            relation_run.snapshots_written = totals["written"]
            relation_run.snapshots_valid = totals["valid"]
            relation_run.snapshots_invalid = totals["invalid"]
            self._mark(workflow, "Persist snapshots", "SUCCESS")

            self._mark(workflow, "Run quality summary", "RUNNING")
            insufficient = sum(
                1 for r in all_results if r.quality_flags.get("insufficient_samples")
            )
            if insufficient:
                write_event(
                    self.session,
                    level="WARNING",
                    component="relations",
                    event_type="relations.insufficient_samples",
                    message=f"{insufficient} pair-windows marked insufficient_samples",
                    workflow_id=workflow.id,
                )
            self._mark(workflow, "Run quality summary", "SUCCESS")

            relation_run.status = "SUCCESS"
            relation_run.finished_at = datetime.now(UTC)
            self._mark(workflow, "Finish", "SUCCESS")
            finish_workflow(self.session, workflow, "SUCCESS")

            event_done = (
                "relations.backfill_completed" if run_type == "BACKFILL" else "relations.compute_completed"
            )
            duration = time.perf_counter() - started
            write_event(
                self.session,
                level="INFO",
                component="relations",
                event_type=event_done,
                message=(
                    f"Relations {run_type} completed: snapshots={totals['written']} "
                    f"valid={totals['valid']} invalid={totals['invalid']} "
                    f"as_of_count={len(as_of_dates)} duration_s={duration:.1f}"
                ),
                workflow_id=workflow.id,
            )
            self.session.commit()
            return {
                "workflow_id": workflow.id,
                "relation_run_id": relation_run.id,
                "status": "SUCCESS",
                "snapshots_written": totals["written"],
                "snapshots_valid": totals["valid"],
                "snapshots_invalid": totals["invalid"],
                "as_of_count": len(as_of_dates),
                "inputs_total": len(inputs),
                "duration_s": round(duration, 2),
            }

        except Exception as exc:
            logger.exception("relations_compute_failed")
            write_event(
                self.session,
                level="ERROR",
                component="relations",
                event_type="relations.calculation_failed",
                message=str(exc),
                workflow_id=workflow.id if workflow else None,
            )
            try:
                update_step(self.session, get_step(workflow, "Finish"), "ERROR")
                finish_workflow(self.session, workflow, "ERROR", error=str(exc))
            except Exception:
                pass
            self.session.commit()
            raise

    def _find_identical_latest(
        self,
        relation_set_id: UUID,
        as_of: date,
        watermark: datetime | None,
    ) -> RelationRun | None:
        q = (
            select(RelationRun)
            .where(
                RelationRun.relation_set_id == relation_set_id,
                RelationRun.run_type == "LATEST",
                RelationRun.status.in_(["SUCCESS", "NO_CHANGES"]),
                RelationRun.as_of_to == as_of,
            )
            .order_by(RelationRun.finished_at.desc())
            .limit(1)
        )
        last = self.session.scalar(q)
        if last is None:
            return None
        # Must have snapshots for this as_of
        has_snap = self.session.scalar(
            select(func.count())
            .select_from(RelationSnapshot)
            .where(
                RelationSnapshot.relation_set_id == relation_set_id,
                RelationSnapshot.as_of_date == as_of,
            )
        )
        if not has_snap:
            return None
        if watermark is None and last.source_watermark is None:
            return last
        if watermark is not None and last.source_watermark is not None and watermark == last.source_watermark:
            return last
        return None

    def _load_input_matrix(
        self,
        inputs: list[RelationInput],
        *,
        feature_set_id: UUID,
        date_from: date,
        date_to: date,
        exclude_invalid: bool,
        exclude_discontinuities: bool,
    ) -> dict[UUID, InputSeries]:
        instrument_inputs = [i for i in inputs if i.input_family == "instrument_feature"]
        series_inputs = [i for i in inputs if i.input_family == "series_feature"]

        # Market calendar from instrument features
        market_dates = list(
            self.session.scalars(
                select(InstrumentFeatureDaily.date)
                .where(
                    InstrumentFeatureDaily.feature_set_id == feature_set_id,
                    InstrumentFeatureDaily.date >= date_from,
                    InstrumentFeatureDaily.date <= date_to,
                )
                .distinct()
                .order_by(InstrumentFeatureDaily.date)
            )
        )

        result: dict[UUID, InputSeries] = {}

        # Batch-load instrument log_return_1d
        if instrument_inputs:
            inst_ids = [i.subject_id for i in instrument_inputs]
            rows = list(
                self.session.scalars(
                    select(InstrumentFeatureDaily).where(
                        InstrumentFeatureDaily.feature_set_id == feature_set_id,
                        InstrumentFeatureDaily.instrument_id.in_(inst_ids),
                        InstrumentFeatureDaily.date >= date_from,
                        InstrumentFeatureDaily.date <= date_to,
                    )
                )
            )
            by_inst: dict[int, list[InstrumentFeatureDaily]] = {}
            for row in rows:
                by_inst.setdefault(row.instrument_id, []).append(row)

            for inp in instrument_inputs:
                feat_rows = sorted(by_inst.get(inp.subject_id, []), key=lambda r: r.date)
                dates: list[date] = []
                values: list[float] = []
                for row in feat_rows:
                    if exclude_invalid and not row.is_valid:
                        continue
                    flags = row.quality_flags or {}
                    if exclude_discontinuities and flags.get("price_discontinuity"):
                        continue
                    if row.log_return_1d is None:
                        continue
                    dates.append(row.date)
                    values.append(float(row.log_return_1d))
                if dates:
                    result[inp.id] = InputSeries(input_id=inp.id, dates=tuple(dates), values=tuple(values))

        # Series: load levels and transform via as-of then change
        if series_inputs and market_dates:
            series_ids = [i.subject_id for i in series_inputs]
            # Prefer RAW series values for level as-of; fall back to SeriesFeatureDaily.value
            level_from = datetime.combine(date_from - timedelta(days=30), datetime.min.time(), tzinfo=UTC)
            level_to = datetime.combine(date_to, datetime.max.time(), tzinfo=UTC)
            level_rows = list(
                self.session.scalars(
                    select(SeriesValue).where(
                        SeriesValue.series_id.in_(series_ids),
                        SeriesValue.timestamp >= level_from,
                        SeriesValue.timestamp <= level_to,
                    )
                )
            )
            levels_by_series: dict[int, list[DatedValue]] = {}
            for row in level_rows:
                levels_by_series.setdefault(row.series_id, []).append(
                    DatedValue(date=row.timestamp.date(), value=float(row.value))
                )

            # Fallback from features if no raw values
            missing = [sid for sid in series_ids if sid not in levels_by_series]
            if missing:
                feat_rows = list(
                    self.session.scalars(
                        select(SeriesFeatureDaily).where(
                            SeriesFeatureDaily.feature_set_id == feature_set_id,
                            SeriesFeatureDaily.series_id.in_(missing),
                            SeriesFeatureDaily.date >= date_from - timedelta(days=30),
                            SeriesFeatureDaily.date <= date_to,
                        )
                    )
                )
                for row in feat_rows:
                    if row.value is None:
                        continue
                    levels_by_series.setdefault(row.series_id, []).append(
                        DatedValue(date=row.date, value=float(row.value))
                    )

            for inp in series_inputs:
                levels = levels_by_series.get(inp.subject_id, [])
                if not levels:
                    write_event(
                        self.session,
                        level="WARNING",
                        component="relations",
                        event_type="relations.input_resolution_failed",
                        message=f"No levels for relation input {inp.code}",
                    )
                    continue
                mode = "pct_change" if inp.feature_key == "pct_change" else "absolute_change"
                changed = asof_level_then_change(market_dates, levels, mode=mode)
                if changed:
                    result[inp.id] = InputSeries(
                        input_id=inp.id,
                        dates=tuple(p.date for p in changed),
                        values=tuple(p.value for p in changed),
                    )

        return result

    def _finish_empty(
        self,
        workflow: Workflow,
        relation_set: RelationSet,
        run_type: str,
        *,
        as_of_from: date | None,
        as_of_to: date | None,
        cadence: str | None,
        inputs_total: int,
        source_watermark: datetime | None,
        reason: str,
    ) -> dict[str, Any]:
        for step_name in RELATIONS_COMPUTE_STEPS[1:-1]:
            try:
                update_step(self.session, get_step(workflow, step_name), "SUCCESS")
            except Exception:
                pass
        run = RelationRun(
            relation_set_id=relation_set.id,
            run_type=run_type,
            as_of_from=as_of_from,
            as_of_to=as_of_to,
            cadence=cadence,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            status="SUCCESS",
            inputs_total=inputs_total,
            source_watermark=source_watermark,
            workflow_id=workflow.id,
            error_message=reason,
        )
        self.session.add(run)
        update_step(self.session, get_step(workflow, "Finish"), "SUCCESS")
        finish_workflow(self.session, workflow, "SUCCESS")
        self.session.commit()
        return {"workflow_id": workflow.id, "relation_run_id": run.id, "status": "SUCCESS", "reason": reason}

    def _resolve_workflow(self, workflow_id: int | None, run_type: str) -> Workflow:
        if workflow_id is not None:
            workflow = self.session.get(Workflow, workflow_id)
            if workflow is None:
                raise ValueError(f"Workflow {workflow_id} not found")
            return workflow
        wf_type = "RelationsBackfill" if run_type == "BACKFILL" else "RelationsComputeLatest"
        return create_workflow(
            self.session,
            wf_type,
            f"Relations {run_type}",
            RELATIONS_COMPUTE_STEPS,
        )
