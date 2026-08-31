"""Feature backfill/update orchestration."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.application.system.event_log import write_event
from app.core.logging import get_logger
from app.infrastructure.analytics.models import FeatureRun, FeatureSet, InstrumentFeatureDaily
from app.infrastructure.analytics.repository import (
    count_feature_quality,
    upsert_instrument_features,
    upsert_series_features,
)
from app.infrastructure.market.models import Candle, DataQualityIssue, Instrument, Series, SeriesValue, Workflow
from app.modules.analytics.application.calculator import CandleObservation, DailyFeatureCalculator
from app.modules.analytics.application.seed import seed_feature_sets
from app.modules.analytics.application.series_calculator import SeriesObservation, calculate_series_features
from app.modules.analytics.feature_config import FEATURE_BACKFILL_STEPS
from app.modules.market.application.workflows import create_workflow, finish_workflow, get_step, update_step

logger = get_logger(__name__, component="analytics-compute")

# Series where pct_change is meaningful (FX rates)
PCT_CHANGE_SERIES_CODES = frozenset({"USD_RUB_CBR", "EUR_RUB_CBR", "CNY_RUB_CBR"})


class FeatureComputeService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def run_backfill(
        self,
        *,
        date_from: date,
        date_to: date | None = None,
        feature_set_code: str = "basic_daily",
        feature_set_version: int = 1,
        workflow_id: int | None = None,
    ) -> dict[str, Any]:
        return self._run(
            run_type="BACKFILL",
            date_from=date_from,
            date_to=date_to,
            feature_set_code=feature_set_code,
            feature_set_version=feature_set_version,
            workflow_id=workflow_id,
        )

    def run_update(
        self,
        *,
        feature_set_code: str = "basic_daily",
        feature_set_version: int = 1,
        workflow_id: int | None = None,
    ) -> dict[str, Any]:
        latest = self.session.scalar(select(func.max(Candle.timestamp)))
        if latest is None:
            return self._run(
                run_type="UPDATE",
                date_from=date.today(),
                date_to=date.today(),
                feature_set_code=feature_set_code,
                feature_set_version=feature_set_version,
                workflow_id=workflow_id,
                no_market_data=True,
            )
        return self._run(
            run_type="UPDATE",
            date_from=None,
            date_to=latest.date(),
            feature_set_code=feature_set_code,
            feature_set_version=feature_set_version,
            workflow_id=workflow_id,
        )

    def _run(
        self,
        *,
        run_type: str,
        date_from: date | None,
        date_to: date | None,
        feature_set_code: str,
        feature_set_version: int,
        workflow_id: int | None,
        no_market_data: bool = False,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        workflow = self._resolve_workflow(workflow_id, run_type)

        try:
            update_step(self.session, get_step(workflow, "Resolve feature set"), "RUNNING")
            seed_feature_sets(self.session)
            feature_set = self._get_feature_set(feature_set_code, feature_set_version)
            calculator = DailyFeatureCalculator(feature_set.parameters)
            safety = int(feature_set.parameters.get("incremental_safety_observations", 25))
            update_step(self.session, get_step(workflow, "Resolve feature set"), "SUCCESS")

            feature_run = FeatureRun(
                feature_set_id=feature_set.id,
                run_type=run_type,
                date_from=date_from,
                date_to=date_to,
                started_at=datetime.now(UTC),
                status="RUNNING",
                workflow_id=workflow.id,
            )
            self.session.add(feature_run)
            self.session.flush()

            write_event(
                self.session,
                level="INFO",
                component="analytics",
                event_type="analytics.feature_backfill_started"
                if run_type == "BACKFILL"
                else "analytics.feature_update_started",
                message=f"Feature {run_type.lower()} started",
                workflow_id=workflow.id,
                trace_id=(workflow.meta or {}).get("trace_id"),
            )

            if no_market_data:
                update_step(self.session, get_step(workflow, "Resolve universe"), "SUCCESS")
                for step_name in FEATURE_BACKFILL_STEPS[2:-1]:
                    update_step(self.session, get_step(workflow, step_name), "SUCCESS")
                feature_run.status = "SUCCESS"
                feature_run.finished_at = datetime.now(UTC)
                update_step(self.session, get_step(workflow, "Finish"), "SUCCESS")
                finish_workflow(self.session, workflow, "SUCCESS")
                return {"workflow_id": workflow.id, "feature_run_id": feature_run.id, "new_rows": 0}

            update_step(self.session, get_step(workflow, "Resolve universe"), "RUNNING")
            instruments = list(
                self.session.scalars(select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.symbol))
            )
            series_list = list(
                self.session.scalars(select(Series).where(Series.is_active.is_(True)).order_by(Series.code))
            )
            feature_run.instruments_total = len(instruments)
            update_step(self.session, get_step(workflow, "Resolve universe"), "SUCCESS")

            update_step(self.session, get_step(workflow, "Load source market data"), "RUNNING")
            source_watermark = self.session.scalar(select(func.max(Candle.ingested_at)))
            feature_run.source_watermark = source_watermark
            update_step(self.session, get_step(workflow, "Load source market data"), "SUCCESS")

            update_step(self.session, get_step(workflow, "Load source quality issues"), "RUNNING")
            dq_issues = list(
                self.session.scalars(
                    select(DataQualityIssue).where(
                        DataQualityIssue.issue_type == "abnormal_price_jump",
                        DataQualityIssue.resolved_at.is_(None),
                    )
                )
            )
            discontinuity_by_instrument: dict[int, set[date]] = {}
            for issue in dq_issues:
                if issue.instrument_id is None or issue.timestamp is None:
                    continue
                discontinuity_by_instrument.setdefault(issue.instrument_id, set()).add(issue.timestamp.date())
            update_step(self.session, get_step(workflow, "Load source quality issues"), "SUCCESS")

            update_step(self.session, get_step(workflow, "Calculate instrument features"), "RUNNING")
            instrument_rows = 0
            rows_valid = 0
            rows_invalid = 0

            for instrument in instruments:
                last_feat = None
                if run_type == "UPDATE":
                    last_feat = self.session.scalar(
                        select(func.max(InstrumentFeatureDaily.date)).where(
                            InstrumentFeatureDaily.instrument_id == instrument.id,
                            InstrumentFeatureDaily.feature_set_id == feature_set.id,
                        )
                    )
                candles = self._load_candles(
                    instrument.id, date_from, date_to, run_type, safety, last_feature_date=last_feat
                )
                if not candles:
                    continue
                observations = [
                    CandleObservation(
                        date=c.timestamp.date(),
                        close=float(c.close),
                        volume=float(c.volume) if c.volume is not None else None,
                        source_updated_at=c.ingested_at,
                    )
                    for c in candles
                ]
                calc_from = date_from
                calc_to = date_to
                if run_type == "UPDATE":
                    if last_feat and candles:
                        tail_start_idx = max(0, len(observations) - safety - 1)
                        calc_from = observations[tail_start_idx].date
                        calc_to = observations[-1].date
                    elif candles:
                        calc_from = observations[0].date
                        calc_to = observations[-1].date

                records = calculator.calculate(
                    observations,
                    discontinuity_dates=discontinuity_by_instrument.get(instrument.id, set()),
                    date_from=calc_from,
                    date_to=calc_to,
                )
                if records:
                    instrument_rows += upsert_instrument_features(
                        self.session,
                        instrument_id=instrument.id,
                        feature_set_id=feature_set.id,
                        feature_version=feature_set.version,
                        records=records,
                    )
                    rows_valid += sum(1 for r in records if r.is_valid)
                    rows_invalid += sum(1 for r in records if not r.is_valid)

            feature_run.instrument_rows_calculated = instrument_rows
            update_step(self.session, get_step(workflow, "Calculate instrument features"), "SUCCESS")

            update_step(self.session, get_step(workflow, "Calculate series features"), "RUNNING")
            series_rows = 0
            for series in series_list:
                values = list(
                    self.session.scalars(
                        select(SeriesValue)
                        .where(SeriesValue.series_id == series.id)
                        .order_by(SeriesValue.timestamp)
                    )
                )
                if not values:
                    continue
                observations = [
                    SeriesObservation(date=v.timestamp.date(), value=float(v.value)) for v in values
                ]
                allow_pct = series.code in PCT_CHANGE_SERIES_CODES
                s_from = date_from if run_type == "BACKFILL" else None
                s_to = date_to
                s_records = calculate_series_features(
                    observations,
                    allow_pct_change=allow_pct,
                    date_from=s_from,
                    date_to=s_to,
                )
                if s_records:
                    series_rows += upsert_series_features(
                        self.session,
                        series_id=series.id,
                        feature_set_id=feature_set.id,
                        records=s_records,
                    )
            feature_run.series_rows_calculated = series_rows
            update_step(self.session, get_step(workflow, "Calculate series features"), "SUCCESS")

            update_step(self.session, get_step(workflow, "Persist batches"), "RUNNING")
            self.session.flush()
            update_step(self.session, get_step(workflow, "Persist batches"), "SUCCESS")

            update_step(self.session, get_step(workflow, "Run feature quality summary"), "RUNNING")
            quality = count_feature_quality(self.session, feature_set.id)
            feature_run.rows_valid = quality["valid"]
            feature_run.rows_invalid = quality["invalid"]
            update_step(self.session, get_step(workflow, "Run feature quality summary"), "SUCCESS")

            status = "WARNING" if quality["warnings"] or quality["invalid"] else "SUCCESS"
            feature_run.status = status
            feature_run.finished_at = datetime.now(UTC)
            update_step(self.session, get_step(workflow, "Finish"), "SUCCESS")
            finish_workflow(self.session, workflow, status)

            write_event(
                self.session,
                level="INFO" if status == "SUCCESS" else "WARNING",
                component="analytics",
                event_type="analytics.feature_backfill_completed"
                if run_type == "BACKFILL"
                else "analytics.feature_update_completed",
                message=f"Feature {run_type.lower()} completed ({status})",
                details={
                    "instrument_rows": instrument_rows,
                    "series_rows": series_rows,
                    "duration_seconds": round(time.perf_counter() - started, 2),
                },
                workflow_id=workflow.id,
                trace_id=(workflow.meta or {}).get("trace_id"),
            )

            return {
                "workflow_id": workflow.id,
                "feature_run_id": feature_run.id,
                "status": status,
                "instrument_rows": instrument_rows,
                "series_rows": series_rows,
                "duration_seconds": round(time.perf_counter() - started, 2),
            }
        except Exception as exc:
            logger.exception("feature_compute_failed", extra={"error": str(exc)})
            if "feature_run" in locals():
                feature_run.status = "ERROR"
                feature_run.error_message = str(exc)[:2000]
                feature_run.finished_at = datetime.now(UTC)
            for step in workflow.steps:
                if step.status not in {"SUCCESS", "WARNING", "ERROR"}:
                    update_step(self.session, step, "ERROR", error=str(exc)[:500])
            finish_workflow(self.session, workflow, "ERROR", error=str(exc)[:500])
            write_event(
                self.session,
                level="ERROR",
                component="analytics",
                event_type="analytics.feature_calculation_failed",
                message=str(exc)[:500],
                workflow_id=workflow.id,
            )
            raise

    def _resolve_workflow(self, workflow_id: int | None, run_type: str) -> Workflow:
        if workflow_id is not None:
            workflow = self.session.get(
                Workflow, workflow_id, options=(selectinload(Workflow.steps),)
            )
            if workflow is None:
                raise ValueError(f"Workflow {workflow_id} not found")
            return workflow
        name = "Feature backfill" if run_type == "BACKFILL" else "Feature update"
        wf_type = "FeatureBackfill" if run_type == "BACKFILL" else "FeatureUpdate"
        return create_workflow(self.session, wf_type, name, FEATURE_BACKFILL_STEPS)

    def _get_feature_set(self, code: str, version: int) -> FeatureSet:
        row = self.session.scalar(
            select(FeatureSet).where(FeatureSet.code == code, FeatureSet.version == version)
        )
        if row is None:
            raise ValueError(f"Feature set {code} v{version} not found")
        return row

    def _load_candles(
        self,
        instrument_id: int,
        date_from: date | None,
        date_to: date | None,
        run_type: str,
        safety: int,
        *,
        last_feature_date: date | None = None,
    ) -> list[Candle]:
        stmt = (
            select(Candle)
            .where(Candle.instrument_id == instrument_id, Candle.timeframe == "1d")
            .order_by(Candle.timestamp)
        )
        if date_to:
            end_dt = datetime.combine(date_to, datetime.max.time().replace(microsecond=0), tzinfo=UTC)
            stmt = stmt.where(Candle.timestamp <= end_dt)
        if run_type == "UPDATE" and last_feature_date:
            start_dt = datetime.combine(last_feature_date, datetime.min.time(), tzinfo=UTC)
            stmt = stmt.where(Candle.timestamp >= start_dt)
        candles = list(self.session.scalars(stmt))
        if run_type == "BACKFILL" and date_from and candles:
            first_needed = datetime.combine(date_from, datetime.min.time(), tzinfo=UTC)
            idx = next((i for i, c in enumerate(candles) if c.timestamp >= first_needed), len(candles))
            lookback_start = max(0, idx - safety)
            candles = candles[lookback_start:]
        elif run_type == "UPDATE" and candles:
            extended = list(
                self.session.scalars(
                    select(Candle)
                    .where(
                        Candle.instrument_id == instrument_id,
                        Candle.timeframe == "1d",
                        Candle.timestamp < candles[0].timestamp,
                    )
                    .order_by(Candle.timestamp.desc())
                    .limit(safety)
                )
            )
            candles = sorted(extended + candles, key=lambda c: c.timestamp)
        return candles
