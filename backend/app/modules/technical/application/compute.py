"""Technical Backfill / Update orchestration."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application.system.event_log import write_event
from app.core.logging import get_logger
from app.infrastructure.analytics.models import InstrumentFeatureDaily
from app.infrastructure.market.models import Candle, DataQualityIssue, Instrument, Workflow
from app.infrastructure.ml.technical_rules import RuleBasedTechnicalModel
from app.infrastructure.technical.models import InstrumentTechnicalFeatureDaily, TechnicalRun
from app.infrastructure.technical.repository import upsert_technical_features, upsert_technical_signals
from app.modules.analytics.application.resolve import resolve_feature_set
from app.modules.analytics.application.seed import seed_feature_sets
from app.modules.market.application.workflows import create_workflow, finish_workflow, get_step, update_step
from app.modules.technical.application.calculator import OhlcObservation, TechnicalFeatureCalculator
from app.modules.technical.application.signal_service import TechnicalSignalService, feature_set_ref
from app.modules.technical.technical_config import (
    RULES_V1_CODE,
    RULES_V1_CONFIG,
    RULES_V1_CONFIG_HASH,
    RULES_V1_VERSION,
    TECHNICAL_BACKFILL_STEPS,
)

logger = get_logger(__name__, component="technical-compute")


def _dec(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


class TechnicalComputeService:
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

    def run_backfill(
        self,
        *,
        date_from: date,
        date_to: date | None = None,
        instrument_ids: list[int] | None = None,
        model_code: str = RULES_V1_CODE,
        model_version: int = RULES_V1_VERSION,
        workflow_id: int | None = None,
    ) -> dict[str, Any]:
        return self._run(
            run_type="BACKFILL",
            date_from=date_from,
            date_to=date_to,
            instrument_ids=instrument_ids,
            model_code=model_code,
            model_version=model_version,
            workflow_id=workflow_id,
        )

    def run_update(
        self,
        *,
        model_code: str = RULES_V1_CODE,
        model_version: int = RULES_V1_VERSION,
        workflow_id: int | None = None,
    ) -> dict[str, Any]:
        latest = self.session.scalar(select(func.max(Candle.timestamp)))
        if latest is None:
            return self._run(
                run_type="UPDATE",
                date_from=date.today(),
                date_to=date.today(),
                instrument_ids=None,
                model_code=model_code,
                model_version=model_version,
                workflow_id=workflow_id,
                no_market_data=True,
            )
        return self._run(
            run_type="UPDATE",
            date_from=None,
            date_to=latest.date(),
            instrument_ids=None,
            model_code=model_code,
            model_version=model_version,
            workflow_id=workflow_id,
        )

    def _run(
        self,
        *,
        run_type: str,
        date_from: date | None,
        date_to: date | None,
        instrument_ids: list[int] | None,
        model_code: str,
        model_version: int,
        workflow_id: int | None,
        no_market_data: bool = False,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        workflow = self._resolve_workflow(workflow_id, run_type)

        try:
            self._mark(workflow, "Resolve model", "RUNNING")
            if model_code != RULES_V1_CODE or model_version != RULES_V1_VERSION:
                raise ValueError(f"Unknown model {model_code} v{model_version}")
            model = RuleBasedTechnicalModel(RULES_V1_CONFIG)
            signal_service = TechnicalSignalService(model)
            self._mark(workflow, "Resolve model", "SUCCESS")

            self._mark(workflow, "Resolve feature sets", "RUNNING")
            seed_feature_sets(self.session)
            basic_fs = resolve_feature_set(self.session, "basic_daily", 1)
            tech_fs = resolve_feature_set(self.session, "technical_daily", 1)
            calculator = TechnicalFeatureCalculator(tech_fs.parameters)
            basic_ref = feature_set_ref(basic_fs.id, basic_fs.code, basic_fs.version)
            tech_ref = feature_set_ref(tech_fs.id, tech_fs.code, tech_fs.version)
            self._mark(workflow, "Resolve feature sets", "SUCCESS")

            tech_run = TechnicalRun(
                run_type=run_type,
                model_code=model_code,
                model_version=model_version,
                model_config_hash=RULES_V1_CONFIG_HASH,
                basic_feature_set_id=basic_fs.id,
                technical_feature_set_id=tech_fs.id,
                date_from=date_from,
                date_to=date_to,
                started_at=datetime.now(UTC),
                status="RUNNING",
                workflow_id=workflow.id,
            )
            self.session.add(tech_run)
            self.session.flush()

            write_event(
                self.session,
                level="INFO",
                component="technical",
                event_type="technical.backfill_started"
                if run_type == "BACKFILL"
                else "technical.update_started",
                message=f"Technical {run_type.lower()} started",
                workflow_id=workflow.id,
                trace_id=(workflow.meta or {}).get("trace_id"),
            )

            if no_market_data:
                for step_name in TECHNICAL_BACKFILL_STEPS[2:-1]:
                    self._mark(workflow, step_name, "SUCCESS")
                tech_run.status = "SUCCESS"
                tech_run.finished_at = datetime.now(UTC)
                self._mark(workflow, "Finish", "SUCCESS")
                finish_workflow(self.session, workflow, "SUCCESS")
                self.session.commit()
                return {
                    "workflow_id": workflow.id,
                    "technical_run_id": tech_run.id,
                    "technical_feature_rows": 0,
                    "signal_rows": 0,
                    "delta": 0,
                }

            self._mark(workflow, "Resolve universe", "RUNNING")
            q = select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.symbol)
            if instrument_ids:
                q = q.where(Instrument.id.in_(instrument_ids))
            instruments = list(self.session.scalars(q))
            tech_run.instruments_total = len(instruments)
            self._mark(workflow, "Resolve universe", "SUCCESS")

            self._mark(workflow, "Load source market/basic analytics", "RUNNING")
            market_latest = self.session.scalar(select(func.max(Candle.timestamp)))
            basic_latest = self.session.scalar(
                select(func.max(InstrumentFeatureDaily.date)).where(
                    InstrumentFeatureDaily.feature_set_id == basic_fs.id
                )
            )
            source_watermark = {
                "latest_market_date": market_latest.date().isoformat() if market_latest else None,
                "basic_feature_set": {"code": basic_fs.code, "version": basic_fs.version, "id": str(basic_fs.id)},
                "technical_feature_set": {"code": tech_fs.code, "version": tech_fs.version, "id": str(tech_fs.id)},
                "basic_latest_date": basic_latest.isoformat() if basic_latest else None,
            }
            tech_run.source_watermark = source_watermark

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
            self._mark(workflow, "Load source market/basic analytics", "SUCCESS")

            self._mark(workflow, "Calculate technical features", "RUNNING")
            feature_rows = 0
            signal_rows = 0
            valid_signals = 0
            invalid_signals = 0
            total = len(instruments)

            effective_to = date_to or (market_latest.date() if market_latest else date.today())
            effective_from = date_from

            for idx, instrument in enumerate(instruments):
                last_tech = None
                if run_type == "UPDATE":
                    last_tech = self.session.scalar(
                        select(func.max(InstrumentTechnicalFeatureDaily.date)).where(
                            InstrumentTechnicalFeatureDaily.instrument_id == instrument.id,
                            InstrumentTechnicalFeatureDaily.feature_set_id == tech_fs.id,
                        )
                    )

                # Warm-up / incremental strategy: load ALL available OHLC for the instrument
                # (exact Wilder/EMA equivalence), persist only the requested/output window.
                candles = list(
                    self.session.scalars(
                        select(Candle)
                        .where(Candle.instrument_id == instrument.id)
                        .order_by(Candle.timestamp)
                    )
                )
                if not candles:
                    self._heartbeat(
                        workflow,
                        processed_instruments=idx + 1,
                        total_instruments=total,
                        current_instrument=instrument.symbol,
                        technical_feature_rows=feature_rows,
                        signal_rows=signal_rows,
                        elapsed=round(time.perf_counter() - started, 2),
                    )
                    continue

                observations = [
                    OhlcObservation(
                        date=c.timestamp.date(),
                        open=float(c.open),
                        high=float(c.high),
                        low=float(c.low),
                        close=float(c.close),
                        volume=float(c.volume) if c.volume is not None else None,
                        source_updated_at=c.ingested_at,
                    )
                    for c in candles
                ]

                calc_from: date | None
                calc_to: date | None = effective_to
                if run_type == "BACKFILL":
                    calc_from = effective_from
                else:
                    # UPDATE: recompute from last persisted date (safety overlap) through latest.
                    safety = int(tech_fs.parameters.get("incremental_safety_observations", 5))
                    if last_tech is not None:
                        # Find observation index of last_tech and step back `safety`.
                        dates = [o.date for o in observations]
                        try:
                            li = dates.index(last_tech)
                            calc_from = dates[max(0, li - safety)]
                        except ValueError:
                            calc_from = last_tech
                    else:
                        calc_from = observations[0].date

                tech_records = calculator.calculate(
                    observations,
                    discontinuity_dates=discontinuity_by_instrument.get(instrument.id, set()),
                    date_from=calc_from,
                    date_to=calc_to,
                )

                # Map basic feature ids for lineage.
                basic_rows = list(
                    self.session.scalars(
                        select(InstrumentFeatureDaily).where(
                            InstrumentFeatureDaily.instrument_id == instrument.id,
                            InstrumentFeatureDaily.feature_set_id == basic_fs.id,
                            InstrumentFeatureDaily.date >= (calc_from or observations[0].date),
                            InstrumentFeatureDaily.date <= (calc_to or observations[-1].date),
                        )
                    )
                )
                basic_by_date = {r.date: r for r in basic_rows}
                source_basic_ids = {d: r.id for d, r in basic_by_date.items()}

                if tech_records:
                    feature_rows += upsert_technical_features(
                        self.session,
                        instrument_id=instrument.id,
                        feature_set_id=tech_fs.id,
                        records=tech_records,
                        source_basic_feature_ids=source_basic_ids,
                    )

                # Reload technical rows with ids for signal lineage.
                tech_persisted = list(
                    self.session.scalars(
                        select(InstrumentTechnicalFeatureDaily).where(
                            InstrumentTechnicalFeatureDaily.instrument_id == instrument.id,
                            InstrumentTechnicalFeatureDaily.feature_set_id == tech_fs.id,
                            InstrumentTechnicalFeatureDaily.date >= (calc_from or observations[0].date),
                            InstrumentTechnicalFeatureDaily.date <= (calc_to or observations[-1].date),
                        )
                    )
                )
                tech_by_date = {r.date: r for r in tech_persisted}

                signal_payload: list[dict[str, Any]] = []
                now = datetime.now(UTC)
                for as_of in sorted(tech_by_date.keys()):
                    basic = basic_by_date.get(as_of)
                    technical = tech_by_date[as_of]
                    _frozen, output = signal_service.evaluate(
                        instrument_id=instrument.id,
                        ticker=instrument.symbol,
                        as_of_date=as_of,
                        basic_ref=basic_ref,
                        technical_ref=tech_ref,
                        basic=basic,
                        technical=technical,
                    )
                    fc = output.factor_contributions
                    signal_payload.append(
                        {
                            "instrument_id": instrument.id,
                            "as_of_date": as_of,
                            "timeframe": "1d",
                            "run_id": tech_run.id,
                            "model_code": output.model_code,
                            "model_version": output.model_version,
                            "model_config_hash": RULES_V1_CONFIG_HASH,
                            "basic_feature_set_id": basic_fs.id,
                            "technical_feature_set_id": tech_fs.id,
                            "source_basic_feature_id": basic.id if basic else None,
                            "source_technical_feature_id": technical.id,
                            "score": Decimal(str(output.score)),
                            "confidence": Decimal(str(output.confidence)),
                            "direction": output.direction.value,
                            "trend_contribution": _dec(fc.trend),
                            "momentum_contribution": _dec(fc.momentum),
                            "rsi_contribution": _dec(fc.rsi),
                            "volume_contribution": _dec(fc.volume),
                            "is_valid": output.is_valid,
                            "quality_flags": dict(output.quality_summary.quality_flags),
                            "calculated_at": now,
                        }
                    )
                    if output.is_valid:
                        valid_signals += 1
                    else:
                        invalid_signals += 1

                if signal_payload:
                    signal_rows += upsert_technical_signals(self.session, rows=signal_payload)

                self._heartbeat(
                    workflow,
                    processed_instruments=idx + 1,
                    total_instruments=total,
                    current_instrument=instrument.symbol,
                    technical_feature_rows=feature_rows,
                    signal_rows=signal_rows,
                    elapsed=round(time.perf_counter() - started, 2),
                )

            tech_run.technical_feature_rows = feature_rows
            tech_run.signal_rows = signal_rows
            tech_run.valid_signals = valid_signals
            tech_run.invalid_signals = invalid_signals
            self._mark(workflow, "Calculate technical features", "SUCCESS")
            self._mark(workflow, "Persist technical features", "SUCCESS")
            self._mark(workflow, "Build frozen model inputs", "SUCCESS")
            self._mark(workflow, "Evaluate rules model", "SUCCESS")
            self._mark(workflow, "Persist technical signals", "SUCCESS")
            self._mark(workflow, "Run quality summary", "SUCCESS")

            tech_run.status = "SUCCESS"
            tech_run.finished_at = datetime.now(UTC)
            self._mark(workflow, "Finish", "SUCCESS")
            finish_workflow(self.session, workflow, "SUCCESS")

            write_event(
                self.session,
                level="INFO",
                component="technical",
                event_type="technical.backfill_completed"
                if run_type == "BACKFILL"
                else "technical.update_completed",
                message=f"Technical {run_type.lower()} completed",
                workflow_id=workflow.id,
                details={
                    "technical_feature_rows": feature_rows,
                    "signal_rows": signal_rows,
                    "valid_signals": valid_signals,
                    "invalid_signals": invalid_signals,
                    "duration_sec": round(time.perf_counter() - started, 2),
                },
                trace_id=(workflow.meta or {}).get("trace_id"),
            )
            self.session.commit()
            return {
                "workflow_id": workflow.id,
                "technical_run_id": tech_run.id,
                "technical_feature_rows": feature_rows,
                "signal_rows": signal_rows,
                "valid_signals": valid_signals,
                "invalid_signals": invalid_signals,
                "duration_sec": round(time.perf_counter() - started, 2),
            }
        except Exception as exc:
            logger.exception("technical_compute_failed")
            write_event(
                self.session,
                level="ERROR",
                component="technical",
                event_type="technical.calculation_failed",
                message=str(exc)[:500],
                workflow_id=workflow.id if workflow else None,
            )
            if "tech_run" in locals() and tech_run is not None:
                tech_run.status = "ERROR"
                tech_run.error_message = str(exc)[:2000]
                tech_run.finished_at = datetime.now(UTC)
            try:
                finish_workflow(self.session, workflow, "ERROR", error=str(exc)[:2000])
            except Exception:
                pass
            self.session.commit()
            raise

    def _resolve_workflow(self, workflow_id: int | None, run_type: str) -> Workflow:
        if workflow_id is not None:
            workflow = self.session.get(Workflow, workflow_id)
            if workflow is None:
                raise ValueError(f"Workflow {workflow_id} not found")
            return workflow
        wf_type = "TechnicalBackfill" if run_type == "BACKFILL" else "TechnicalUpdate"
        return create_workflow(self.session, wf_type, wf_type, TECHNICAL_BACKFILL_STEPS)
