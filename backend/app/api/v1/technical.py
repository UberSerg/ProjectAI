"""Technical Agent API — overview, models, runs, signals, backfill/update."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from app.infrastructure.analytics.models import FeatureSet, InstrumentFeatureDaily
from app.infrastructure.db.session import core_session
from app.infrastructure.market.models import Instrument
from app.infrastructure.technical.models import InstrumentTechnicalFeatureDaily, TechnicalRun, TechnicalSignalDaily
from app.modules.analytics.application.seed import seed_feature_sets
from app.modules.market.application.workflows import create_workflow
from app.modules.technical.technical_config import (
    RULES_V1_CODE,
    RULES_V1_CONFIG,
    RULES_V1_CONFIG_HASH,
    RULES_V1_VERSION,
    TECHNICAL_BACKFILL_STEPS,
)
from app.worker import tasks as worker_tasks

router = APIRouter()


def _f(value: Decimal | float | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()


class TechnicalModelInfo(BaseModel):
    model_code: str
    model_version: int
    config: dict[str, Any]
    config_hash: str
    is_active: bool = True


class TechnicalRunResponse(BaseModel):
    id: str
    run_type: str
    model_code: str
    model_version: int
    model_config_hash: str
    date_from: date | None
    date_to: date | None
    started_at: str | None
    finished_at: str | None
    status: str
    instruments_total: int
    technical_feature_rows: int
    signal_rows: int
    valid_signals: int
    invalid_signals: int
    source_watermark: dict[str, Any] | None
    error_message: str | None
    workflow_id: str | None


class FactorContributionsResponse(BaseModel):
    trend: float | None = None
    momentum: float | None = None
    rsi: float | None = None
    volume: float | None = None


class TechnicalSignalResponse(BaseModel):
    id: str
    instrument_id: str
    ticker: str | None = None
    as_of_date: date
    score: float
    confidence: float
    direction: str
    model_code: str
    model_version: int
    model_config_hash: str
    factor_contributions: FactorContributionsResponse
    is_valid: bool
    quality_flags: dict[str, Any] = Field(default_factory=dict)
    # Feature context for table / instrument page
    rsi14: float | None = None
    sma20_distance: float | None = None
    ema20_distance: float | None = None
    atr14_pct: float | None = None
    volume_zscore_20d: float | None = None
    return_5d: float | None = None
    return_20d: float | None = None
    calculated_at: str | None = None


class TechnicalOverviewResponse(BaseModel):
    active_model: str
    technical_feature_set: str
    as_of: date | None
    instruments_analyzed: int
    bullish: int
    neutral: int
    bearish: int
    invalid: int
    warnings: int
    last_run: TechnicalRunResponse | None


class BackfillRequest(BaseModel):
    date_from: date
    date_to: date | None = None
    instrument_ids: list[int] | None = None
    model_code: str = RULES_V1_CODE
    model_version: int = RULES_V1_VERSION


class UpdateRequest(BaseModel):
    model_code: str = RULES_V1_CODE
    model_version: int = RULES_V1_VERSION


class WorkflowStartResponse(BaseModel):
    workflow_id: str
    status: str


def _run_to_response(row: TechnicalRun) -> TechnicalRunResponse:
    return TechnicalRunResponse(
        id=str(row.id),
        run_type=row.run_type,
        model_code=row.model_code,
        model_version=row.model_version,
        model_config_hash=row.model_config_hash,
        date_from=row.date_from,
        date_to=row.date_to,
        started_at=_dt(row.started_at),
        finished_at=_dt(row.finished_at),
        status=row.status,
        instruments_total=row.instruments_total,
        technical_feature_rows=row.technical_feature_rows,
        signal_rows=row.signal_rows,
        valid_signals=row.valid_signals,
        invalid_signals=row.invalid_signals,
        source_watermark=row.source_watermark,
        error_message=row.error_message,
        workflow_id=str(row.workflow_id) if row.workflow_id is not None else None,
    )


def _enrich_signal(
    session: Any,
    signal: TechnicalSignalDaily,
    ticker: str | None,
    tech_feat: InstrumentTechnicalFeatureDaily | None,
    basic_feat: InstrumentFeatureDaily | None,
) -> TechnicalSignalResponse:
    return TechnicalSignalResponse(
        id=str(signal.id),
        instrument_id=str(signal.instrument_id),
        ticker=ticker,
        as_of_date=signal.as_of_date,
        score=float(signal.score),
        confidence=float(signal.confidence),
        direction=signal.direction,
        model_code=signal.model_code,
        model_version=signal.model_version,
        model_config_hash=signal.model_config_hash,
        factor_contributions=FactorContributionsResponse(
            trend=_f(signal.trend_contribution),
            momentum=_f(signal.momentum_contribution),
            rsi=_f(signal.rsi_contribution),
            volume=_f(signal.volume_contribution),
        ),
        is_valid=signal.is_valid,
        quality_flags=signal.quality_flags or {},
        rsi14=_f(tech_feat.rsi14) if tech_feat else None,
        sma20_distance=_f(tech_feat.sma20_distance) if tech_feat else None,
        ema20_distance=_f(tech_feat.ema20_distance) if tech_feat else None,
        atr14_pct=_f(tech_feat.atr14_pct) if tech_feat else None,
        volume_zscore_20d=_f(basic_feat.volume_zscore_20d) if basic_feat else None,
        return_5d=_f(basic_feat.return_5d) if basic_feat else None,
        return_20d=_f(basic_feat.return_20d) if basic_feat else None,
        calculated_at=_dt(signal.calculated_at),
    )


@router.get("/overview", response_model=TechnicalOverviewResponse)
def technical_overview() -> TechnicalOverviewResponse:
    with core_session() as session:
        seed_feature_sets(session)
        tech_fs = session.scalar(
            select(FeatureSet).where(FeatureSet.code == "technical_daily", FeatureSet.is_active.is_(True))
        )
        last_run = session.scalar(
            select(TechnicalRun)
            .where(TechnicalRun.status.in_(["SUCCESS", "WARNING"]))
            .order_by(desc(TechnicalRun.finished_at))
            .limit(1)
        )
        latest_as_of = session.scalar(select(func.max(TechnicalSignalDaily.as_of_date)))
        # Counts on latest as_of
        bullish = neutral = bearish = invalid = warnings = instruments = 0
        if latest_as_of is not None:
            rows = list(
                session.scalars(
                    select(TechnicalSignalDaily).where(
                        TechnicalSignalDaily.as_of_date == latest_as_of,
                        TechnicalSignalDaily.model_code == RULES_V1_CODE,
                        TechnicalSignalDaily.model_version == RULES_V1_VERSION,
                    )
                )
            )
            instruments = len(rows)
            for r in rows:
                if not r.is_valid:
                    invalid += 1
                elif r.quality_flags:
                    warnings += 1
                if r.direction == "bullish":
                    bullish += 1
                elif r.direction == "bearish":
                    bearish += 1
                else:
                    neutral += 1
        return TechnicalOverviewResponse(
            active_model=f"{RULES_V1_CODE}_v{RULES_V1_VERSION}",
            technical_feature_set=(
                f"{tech_fs.code} v{tech_fs.version}" if tech_fs else "technical_daily v1"
            ),
            as_of=latest_as_of,
            instruments_analyzed=instruments,
            bullish=bullish,
            neutral=neutral,
            bearish=bearish,
            invalid=invalid,
            warnings=warnings,
            last_run=_run_to_response(last_run) if last_run else None,
        )


@router.get("/models", response_model=list[TechnicalModelInfo])
def list_models() -> list[TechnicalModelInfo]:
    return [
        TechnicalModelInfo(
            model_code=RULES_V1_CODE,
            model_version=RULES_V1_VERSION,
            config=RULES_V1_CONFIG,
            config_hash=RULES_V1_CONFIG_HASH,
            is_active=True,
        )
    ]


@router.get("/runs", response_model=list[TechnicalRunResponse])
def list_runs(limit: int = Query(50, ge=1, le=200)) -> list[TechnicalRunResponse]:
    with core_session() as session:
        rows = list(session.scalars(select(TechnicalRun).order_by(desc(TechnicalRun.id)).limit(limit)))
        return [_run_to_response(r) for r in rows]


@router.get("/runs/{run_id}", response_model=TechnicalRunResponse)
def get_run(run_id: int) -> TechnicalRunResponse:
    with core_session() as session:
        row = session.get(TechnicalRun, run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Technical run not found")
        return _run_to_response(row)


@router.get("/signals", response_model=list[TechnicalSignalResponse])
def list_signals(
    as_of: Annotated[date | None, Query(alias="date")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    direction: str | None = None,
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    valid_only: bool = False,
    instrument: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[TechnicalSignalResponse]:
    with core_session() as session:
        q = select(TechnicalSignalDaily, Instrument.symbol).join(
            Instrument, Instrument.id == TechnicalSignalDaily.instrument_id
        )
        if as_of is not None:
            q = q.where(TechnicalSignalDaily.as_of_date == as_of)
        if date_from is not None:
            q = q.where(TechnicalSignalDaily.as_of_date >= date_from)
        if date_to is not None:
            q = q.where(TechnicalSignalDaily.as_of_date <= date_to)
        if direction is not None:
            q = q.where(TechnicalSignalDaily.direction == direction.lower())
        if min_confidence is not None:
            q = q.where(TechnicalSignalDaily.confidence >= min_confidence)
        if valid_only:
            q = q.where(TechnicalSignalDaily.is_valid.is_(True))
        if instrument:
            q = q.where(Instrument.symbol.ilike(f"%{instrument}%"))
        q = q.order_by(desc(TechnicalSignalDaily.as_of_date), Instrument.symbol).offset(offset).limit(limit)
        pairs = list(session.execute(q).all())
        out: list[TechnicalSignalResponse] = []
        for signal, ticker in pairs:
            tech = None
            basic = None
            if signal.source_technical_feature_id:
                tech = session.get(InstrumentTechnicalFeatureDaily, signal.source_technical_feature_id)
            if signal.source_basic_feature_id:
                basic = session.get(InstrumentFeatureDaily, signal.source_basic_feature_id)
            out.append(_enrich_signal(session, signal, ticker, tech, basic))
        return out


@router.get("/instruments/{instrument_id}/latest", response_model=TechnicalSignalResponse)
def instrument_latest(instrument_id: int) -> TechnicalSignalResponse:
    with core_session() as session:
        instrument = session.get(Instrument, instrument_id)
        if instrument is None:
            raise HTTPException(status_code=404, detail="Instrument not found")
        signal = session.scalar(
            select(TechnicalSignalDaily)
            .where(TechnicalSignalDaily.instrument_id == instrument_id)
            .order_by(desc(TechnicalSignalDaily.as_of_date))
            .limit(1)
        )
        if signal is None:
            raise HTTPException(status_code=404, detail="No technical signal for instrument")
        tech = (
            session.get(InstrumentTechnicalFeatureDaily, signal.source_technical_feature_id)
            if signal.source_technical_feature_id
            else None
        )
        basic = (
            session.get(InstrumentFeatureDaily, signal.source_basic_feature_id)
            if signal.source_basic_feature_id
            else None
        )
        return _enrich_signal(session, signal, instrument.symbol, tech, basic)


@router.get("/instruments/{instrument_id}/history", response_model=list[TechnicalSignalResponse])
def instrument_history(
    instrument_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[TechnicalSignalResponse]:
    with core_session() as session:
        instrument = session.get(Instrument, instrument_id)
        if instrument is None:
            raise HTTPException(status_code=404, detail="Instrument not found")
        q = select(TechnicalSignalDaily).where(TechnicalSignalDaily.instrument_id == instrument_id)
        if date_from is not None:
            q = q.where(TechnicalSignalDaily.as_of_date >= date_from)
        if date_to is not None:
            q = q.where(TechnicalSignalDaily.as_of_date <= date_to)
        q = q.order_by(desc(TechnicalSignalDaily.as_of_date)).offset(offset).limit(limit)
        rows = list(session.scalars(q))
        out: list[TechnicalSignalResponse] = []
        for signal in rows:
            tech = (
                session.get(InstrumentTechnicalFeatureDaily, signal.source_technical_feature_id)
                if signal.source_technical_feature_id
                else None
            )
            basic = (
                session.get(InstrumentFeatureDaily, signal.source_basic_feature_id)
                if signal.source_basic_feature_id
                else None
            )
            out.append(_enrich_signal(session, signal, instrument.symbol, tech, basic))
        return out


@router.post("/backfill", response_model=WorkflowStartResponse)
def start_backfill(body: BackfillRequest) -> WorkflowStartResponse:
    if body.date_to is not None and body.date_to < body.date_from:
        raise HTTPException(status_code=400, detail="date_to must be >= date_from")
    if body.model_code != RULES_V1_CODE or body.model_version != RULES_V1_VERSION:
        raise HTTPException(status_code=400, detail="Unknown model version")
    with core_session() as session:
        seed_feature_sets(session)
        workflow = create_workflow(
            session,
            "TechnicalBackfill",
            f"Technical backfill {body.date_from} → {body.date_to or 'latest'}",
            TECHNICAL_BACKFILL_STEPS,
        )
        session.commit()
        worker_tasks.technical_backfill.delay(
            workflow.id,
            body.date_from.isoformat(),
            body.date_to.isoformat() if body.date_to else None,
            body.instrument_ids,
            body.model_code,
            body.model_version,
        )
        return WorkflowStartResponse(workflow_id=str(workflow.id), status="RUNNING")


@router.post("/update", response_model=WorkflowStartResponse)
def start_update(body: UpdateRequest | None = None) -> WorkflowStartResponse:
    body = body or UpdateRequest()
    if body.model_code != RULES_V1_CODE or body.model_version != RULES_V1_VERSION:
        raise HTTPException(status_code=400, detail="Unknown model version")
    with core_session() as session:
        seed_feature_sets(session)
        workflow = create_workflow(
            session,
            "TechnicalUpdate",
            "Technical update",
            TECHNICAL_BACKFILL_STEPS,
        )
        session.commit()
        worker_tasks.technical_update.delay(workflow.id, body.model_code, body.model_version)
        return WorkflowStartResponse(workflow_id=str(workflow.id), status="RUNNING")
