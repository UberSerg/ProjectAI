"""Market backfill/update orchestration and idempotent persistence."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.ports.market_data import CandleBar, SeriesPoint
from app.infrastructure.market.cbr import CbrProvider
from app.infrastructure.market.models import (
    Candle,
    IngestionBatch,
    Instrument,
    Series,
    SeriesValue,
    Workflow,
)
from app.infrastructure.market.moex_iss import MoexIssProvider
from app.infrastructure.market.raw_store import RawStore
from app.modules.market.application.data_quality import (
    DataQualityContext,
    run_data_quality_checks,
)
from app.modules.market.application.history_ranges import (
    PlannedSourceRange,
    missing_coverage_ranges,
    plan_source_ranges,
)
from app.modules.market.application.identity import mappings_for_instrument
from app.modules.market.application.incremental import compute_incremental_range
from app.modules.market.application.seed import seed_market_universe
from app.modules.market.application.workflows import (
    create_workflow,
    finish_workflow,
    get_step,
    update_step,
)
from app.modules.market.universe import SERIES as SERIES_DEFS

logger = get_logger(__name__, component="market-ingest")

BACKFILL_STEPS = [
    "Resolve instruments",
    "Download MOEX",
    "Download CBR",
    "Save RAW",
    "Normalize / Persist",
    "Run Data Quality",
    "Finish",
]


def deduplicate_records(records: list[CandleBar] | list[SeriesPoint]):
    by_ts = {record.timestamp: record for record in records}
    return [by_ts[key] for key in sorted(by_ts)]


def _as_decimal(value: Decimal | float | int | None, fallback: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return fallback
    return Decimal(str(value))


def upsert_candles(
    session: Session, instrument_id: int, records: list[CandleBar], source: str
) -> dict[str, int]:
    rows = []
    for bar in deduplicate_records(records):
        close = _as_decimal(bar.close)
        rows.append(
            {
                "instrument_id": instrument_id,
                "timeframe": "1d",
                "timestamp": bar.timestamp,
                "open": _as_decimal(bar.open, close),
                "high": _as_decimal(bar.high, close),
                "low": _as_decimal(bar.low, close),
                "close": close,
                "volume": None if bar.volume is None else _as_decimal(bar.volume),
                "source": source,
            }
        )
    if not rows:
        return {"received": 0, "inserted": 0, "updated": 0}
    timestamps = [row["timestamp"] for row in rows]
    existing = (
        session.scalar(
            select(func.count())
            .select_from(Candle)
            .where(
                Candle.instrument_id == instrument_id,
                Candle.timeframe == "1d",
                Candle.source == source,
                Candle.timestamp.in_(timestamps),
            )
        )
        or 0
    )
    stmt = insert(Candle).values(rows)
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_market_candles",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "ingested_at": func.now(),
            },
        )
    )
    return {
        "received": len(rows),
        "inserted": len(rows) - int(existing),
        "updated": int(existing),
    }


def upsert_series_values(
    session: Session, series_id: int, records: list[SeriesPoint], source: str
) -> dict[str, int]:
    rows = [
        {
            "series_id": series_id,
            "timestamp": point.timestamp,
            "value": _as_decimal(point.value),
            "source": source,
        }
        for point in deduplicate_records(records)
    ]
    if not rows:
        return {"received": 0, "inserted": 0, "updated": 0}
    timestamps = [row["timestamp"] for row in rows]
    existing = (
        session.scalar(
            select(func.count())
            .select_from(SeriesValue)
            .where(
                SeriesValue.series_id == series_id,
                SeriesValue.source == source,
                SeriesValue.timestamp.in_(timestamps),
            )
        )
        or 0
    )
    stmt = insert(SeriesValue).values(rows)
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_market_series_values",
            set_={
                "value": stmt.excluded.value,
                "ingested_at": func.now(),
            },
        )
    )
    return {
        "received": len(rows),
        "inserted": len(rows) - int(existing),
        "updated": int(existing),
    }


def _series_external_id(code: str) -> str:
    for item in SERIES_DEFS:
        if item.code == code:
            return item.external_id
    return code


class MarketIngestionService:
    def __init__(
        self,
        session: Session,
        *,
        moex: MoexIssProvider | None = None,
        cbr: CbrProvider | None = None,
        raw_store: RawStore | None = None,
        pause_seconds: float | None = None,
        commit_progress: bool = True,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self.raw_store = raw_store or RawStore()
        self.moex = moex or MoexIssProvider()
        self.cbr = cbr or CbrProvider()
        self.pause_seconds = 0.15 if pause_seconds is None else pause_seconds
        self.commit_progress = commit_progress

    def run_backfill(
        self,
        *,
        symbols: list[str] | None,
        date_from: date | None,
        date_to: date | None,
        workflow_id: int | None = None,
    ) -> dict[str, Any]:
        start = date_from or self.settings.market_default_backfill_from
        end = date_to or datetime.now(UTC).date()
        return self._run(mode="backfill", symbols=symbols, date_from=start, date_to=end, workflow_id=workflow_id)

    def run_update(self, *, workflow_id: int | None = None) -> dict[str, Any]:
        return self._run(mode="update", symbols=None, date_from=None, date_to=None, workflow_id=workflow_id)

    def _run(
        self,
        *,
        mode: str,
        symbols: list[str] | None,
        date_from: date | None,
        date_to: date | None,
        workflow_id: int | None,
    ) -> dict[str, Any]:
        workflow_pk: int | None = None
        seed_market_universe(self.session)
        workflow = self._resolve_workflow(workflow_id, mode)
        workflow_pk = workflow.id
        stats = {
            "received": 0,
            "inserted": 0,
            "updated": 0,
            "rejected": 0,
            "batches": [],
            "warnings": 0,
        }
        try:
            update_step(self.session, get_step(workflow, "Resolve instruments"), "SUCCESS")
            instruments = self._load_instruments(symbols)
            series_rows = list(self.session.scalars(select(Series).where(Series.is_active.is_(True))))

            update_step(self.session, get_step(workflow, "Download MOEX"), "RUNNING")
            moex_batch = self._new_batch("MOEX", "candles", workflow.id)
            raw_paths = self._download_moex(
                workflow, moex_batch, instruments, stats, mode, date_from, date_to
            )
            moex_batch.raw_location = ";".join(raw_paths[:20])
            moex_batch.status = "success"
            moex_batch.finished_at = datetime.now(UTC)
            update_step(self.session, get_step(workflow, "Download MOEX"), "SUCCESS")
            update_step(self.session, get_step(workflow, "Save RAW"), "SUCCESS")

            update_step(self.session, get_step(workflow, "Download CBR"), "RUNNING")
            cbr_batch = self._new_batch("CBR", "series", workflow.id)
            cbr_paths = self._download_cbr(workflow, cbr_batch, series_rows, stats, mode, date_from, date_to)
            cbr_batch.raw_location = ";".join(cbr_paths[:20])
            cbr_batch.status = "success" if cbr_batch.records_rejected == 0 else "warning"
            cbr_batch.finished_at = datetime.now(UTC)
            update_step(self.session, get_step(workflow, "Download CBR"), "SUCCESS")
            update_step(self.session, get_step(workflow, "Normalize / Persist"), "SUCCESS")

            update_step(self.session, get_step(workflow, "Run Data Quality"), "RUNNING")
            if mode == "backfill":
                assert date_from and date_to
                dq_context = DataQualityContext(
                    mode="historical",
                    date_from=date_from,
                    date_to=date_to,
                    batch_id=moex_batch.id,
                )
            else:
                dq_context = DataQualityContext(
                    mode="operational",
                    batch_id=moex_batch.id,
                )
            dq = run_data_quality_checks(self.session, dq_context)
            stats["warnings"] = dq.get("warnings", 0)
            stats["dq"] = dq
            dq_status = "WARNING" if stats["warnings"] or dq.get("errors", 0) else "SUCCESS"
            update_step(self.session, get_step(workflow, "Run Data Quality"), dq_status)
            update_step(self.session, get_step(workflow, "Finish"), "SUCCESS")
            final = "WARNING" if dq_status == "WARNING" else "SUCCESS"
            finish_workflow(self.session, workflow, final)
            if self.commit_progress:
                self.session.commit()
            return {"workflow_id": workflow.id, "status": final, "stats": stats}
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            try:
                failed = self.session.get(Workflow, workflow_pk) if workflow_pk is not None else None
                if failed is not None:
                    finish_workflow(self.session, failed, "ERROR", error=str(exc)[:2000])
                    if self.commit_progress:
                        self.session.commit()
            except Exception:
                logger.exception("market_ingest_workflow_finish_failed")
                self.session.rollback()
            raise

    def _resolve_workflow(self, workflow_id: int | None, mode: str) -> Workflow:
        if workflow_id is not None:
            workflow = self.session.get(Workflow, workflow_id)
            if workflow is None:
                raise ValueError(f"Workflow {workflow_id} not found")
            return workflow
        return create_workflow(
            self.session,
            "MarketDataBackfill" if mode == "backfill" else "MarketDataUpdate",
            f"Market data {mode}",
            BACKFILL_STEPS,
        )

    def _load_instruments(self, symbols: list[str] | None) -> list[Instrument]:
        stmt = select(Instrument).options(selectinload(Instrument.sources)).where(Instrument.is_active.is_(True))
        if symbols:
            stmt = stmt.where(Instrument.symbol.in_(symbols))
        return list(self.session.scalars(stmt).unique().all())

    def _requested_range(
        self,
        mode: str,
        instrument_id: int,
        date_from: date | None,
        date_to: date | None,
    ) -> tuple[date, date] | None:
        today = datetime.now(UTC).date()
        if mode == "backfill":
            assert date_from and date_to
            return date_from, date_to
        last = self.session.scalar(
            select(func.max(Candle.timestamp)).where(
                Candle.instrument_id == instrument_id, Candle.timeframe == "1d"
            )
        )
        return compute_incremental_range(
            last_timestamp_date=last.date() if last else None,
            default_from=self.settings.market_default_backfill_from,
            today=today,
        )

    def _download_moex(
        self,
        workflow: Workflow,
        moex_batch: IngestionBatch,
        instruments: list[Instrument],
        stats: dict[str, Any],
        mode: str,
        date_from: date | None,
        date_to: date | None,
    ) -> list[str]:
        raw_paths: list[str] = []
        fetches: list[dict[str, Any]] = []
        total = len(instruments)
        for index, instrument in enumerate(instruments, start=1):
            requested = self._requested_range(mode, instrument.id, date_from, date_to)
            if requested is None:
                self._heartbeat(
                    workflow,
                    processed_instruments=index,
                    total_instruments=total,
                    current_instrument=instrument.symbol,
                    current_window="skipped",
                    received=stats["received"],
                    inserted=stats["inserted"],
                )
                continue
            plans = plan_source_ranges(
                mappings_for_instrument(self.session, instrument.id, "MOEX"),
                requested[0],
                requested[1],
                instrument_id=instrument.id,
            )
            if not plans:
                self._heartbeat(
                    workflow,
                    processed_instruments=index,
                    total_instruments=total,
                    current_instrument=instrument.symbol,
                    current_window="NO_PROVEN_MAPPING",
                    received=stats["received"],
                    inserted=stats["inserted"],
                )
                continue
            for plan in plans:
                self._heartbeat(
                    workflow,
                    processed_instruments=index,
                    total_instruments=total,
                    current_instrument=instrument.symbol,
                    current_window=(
                        f"{plan.external_id}/{plan.board} "
                        f"{plan.effective_from.isoformat()}..{plan.effective_to.isoformat()}"
                    ),
                    received=stats["received"],
                    inserted=stats["inserted"],
                )
                written, paths = self._fetch_planned_candles(moex_batch, instrument, plan)
                raw_paths.extend(paths)
                stats["received"] += written["received"]
                stats["inserted"] += written["inserted"]
                stats["updated"] += written["updated"]
                moex_batch.records_received += written["received"]
                moex_batch.records_inserted += written["inserted"]
                moex_batch.records_updated += written["updated"]
                fetches.append(
                    {
                        "symbol": instrument.symbol,
                        "external_id": plan.external_id,
                        "board": plan.board,
                        "from": plan.effective_from.isoformat(),
                        "to": plan.effective_to.isoformat(),
                        "received": written["received"],
                        "inserted": written["inserted"],
                        "updated": written["updated"],
                    }
                )
            if self.commit_progress:
                self.session.commit()
        moex_batch.meta = {
            "endpoint_template": (
                "{base}/iss/history/engines/stock/markets/{market}"
                "/boards/{board}/securities/{secid}.json"
            ),
            "fetches": fetches,
        }
        flag_modified(moex_batch, "meta")
        return raw_paths

    def _fetch_planned_candles(
        self,
        moex_batch: IngestionBatch,
        instrument: Instrument,
        plan: PlannedSourceRange,
    ) -> tuple[dict[str, int], list[str]]:
        if self.pause_seconds:
            time.sleep(self.pause_seconds)
        result = self.moex.fetch_daily_candles(
            plan.external_id,
            plan.effective_from,
            plan.effective_to,
            board=plan.board,
        )
        paths: list[str] = []
        for idx, payload in enumerate(result.raw_payloads):
            paths.append(
                self.raw_store.save(
                    source="moex",
                    data_type="candles",
                    batch_id=moex_batch.id,
                    name=(
                        f"{plan.external_id}_{plan.board}_"
                        f"{plan.effective_from}_{plan.effective_to}_{idx}"
                    ),
                    payload=payload,
                    content_type="application/json",
                )
            )
        written = upsert_candles(self.session, instrument.id, list(result.records), "MOEX")
        return written, paths

    def _download_cbr(
        self,
        workflow: Workflow,
        cbr_batch: IngestionBatch,
        series_rows: list[Series],
        stats: dict[str, Any],
        mode: str,
        date_from: date | None,
        date_to: date | None,
    ) -> list[str]:
        raw_paths: list[str] = []
        today = datetime.now(UTC).date()
        for series in series_rows:
            external_id = _series_external_id(series.code)
            if mode == "update":
                last = self.session.scalar(
                    select(func.max(SeriesValue.timestamp)).where(SeriesValue.series_id == series.id)
                )
                ranges = []
                incremental = compute_incremental_range(
                    last_timestamp_date=last.date() if last else None,
                    default_from=self.settings.market_default_backfill_from,
                    today=today,
                )
                if incremental is not None:
                    ranges.append(incremental)
            else:
                assert date_from and date_to
                have_min = self.session.scalar(
                    select(func.min(SeriesValue.timestamp)).where(SeriesValue.series_id == series.id)
                )
                have_max = self.session.scalar(
                    select(func.max(SeriesValue.timestamp)).where(SeriesValue.series_id == series.id)
                )
                ranges = missing_coverage_ranges(
                    have_min.date() if have_min else None,
                    have_max.date() if have_max else None,
                    date_from,
                    date_to,
                )
            for start, end in ranges:
                self._heartbeat(
                    workflow,
                    current_instrument=series.code,
                    current_window=f"CBR {start.isoformat()}..{end.isoformat()}",
                    received=stats["received"],
                    inserted=stats["inserted"],
                )
                if self.pause_seconds:
                    time.sleep(self.pause_seconds)
                try:
                    result = self.cbr.fetch_series(external_id, start, end)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("cbr_fetch_failed", extra={"series": series.code, "error": str(exc)})
                    cbr_batch.records_rejected += 1
                    stats["rejected"] += 1
                    continue
                for idx, payload in enumerate(result.raw_payloads):
                    raw_paths.append(
                        self.raw_store.save(
                            source="cbr",
                            data_type="series",
                            batch_id=cbr_batch.id,
                            name=f"{series.code}_{start}_{end}_{idx}",
                            payload=payload,
                            content_type="application/xml",
                        )
                    )
                written = upsert_series_values(self.session, series.id, list(result.records), "CBR")
                stats["received"] += written["received"]
                stats["inserted"] += written["inserted"]
                stats["updated"] += written["updated"]
                cbr_batch.records_received += written["received"]
                cbr_batch.records_inserted += written["inserted"]
                cbr_batch.records_updated += written["updated"]
        return raw_paths

    def _heartbeat(self, workflow: Workflow, **fields: Any) -> None:
        workflow.meta = {
            **(workflow.meta or {}),
            "heartbeat_at": datetime.now(UTC).isoformat(),
            **fields,
        }
        flag_modified(workflow, "meta")
        self.session.flush()

    def _new_batch(self, source: str, data_type: str, workflow_id: int) -> IngestionBatch:
        batch = IngestionBatch(
            source=source,
            data_type=data_type,
            status="running",
            workflow_id=workflow_id,
        )
        self.session.add(batch)
        self.session.flush()
        return batch
