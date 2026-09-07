"""MoexInstrumentMasterSync — catalog upsert without research/dataset mutation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.core.logging import get_logger
from app.infrastructure.market.models import (
    Instrument,
    InstrumentMasterSyncRun,
    InstrumentSource,
)
from app.modules.investment.application.equity_lot_size import LOTSIZE_META_KEY, LOTSIZE_PROVENANCE_KEY
from app.modules.market.application.instrument_classification import (
    INACTIVE,
    classify_moex_row,
    pick_primary_board,
)
from app.modules.market.application.moex_board_securities import (
    DEFAULT_BOARDS,
    BoardSecuritiesPort,
    MoexBoardSecuritiesClient,
    MoexSecurityRow,
)
from app.modules.market.application.research_universe import seed_research_equity_membership
from app.modules.market.application.seed import seed_market_universe

logger = get_logger(__name__, component="instrument_master")

LOCK_KEY = "projectai:lock:moex_instrument_master_sync"
LOCK_TTL_SECONDS = 1800
SOURCE_MOEX = "MOEX"
SOURCE_MOEX_ISS = "MOEX_ISS"


@dataclass
class SyncReport:
    status: str
    started_at: str
    finished_at: str | None = None
    boards: dict[str, Any] = field(default_factory=dict)
    created: int = 0
    updated: int = 0
    deactivated: int = 0
    unchanged: int = 0
    lotsize_updated: int = 0
    errors: list[str] = field(default_factory=list)
    mass_deactivate_blocked: bool = False
    research_seed: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "boards": self.boards,
            "created": self.created,
            "updated": self.updated,
            "deactivated": self.deactivated,
            "unchanged": self.unchanged,
            "lotsize_updated": self.lotsize_updated,
            "errors": self.errors,
            "mass_deactivate_blocked": self.mass_deactivate_blocked,
            "research_seed": self.research_seed,
            "notes": self.notes,
        }


class MoexInstrumentMasterSync:
    """Fetch MOEX boards → upsert instruments/sources. Never touches research Dataset."""

    def __init__(
        self,
        session: Session,
        *,
        client: BoardSecuritiesPort | None = None,
        boards: tuple[tuple[str, str], ...] | None = None,
        deactivate_missing: bool = True,
    ) -> None:
        self.session = session
        self.client = client or MoexBoardSecuritiesClient()
        self.boards = boards or DEFAULT_BOARDS
        self.deactivate_missing = deactivate_missing

    def run(self) -> dict[str, Any]:
        started = datetime.now(UTC)
        report = SyncReport(status="RUNNING", started_at=started.isoformat())
        run_row = InstrumentMasterSyncRun(
            started_at=started,
            status="RUNNING",
            report={},
        )
        self.session.add(run_row)
        self.session.flush()

        # Keep curated research seed present; membership is seeded separately.
        try:
            seed_market_universe(self.session)
            report.research_seed = seed_research_equity_membership(self.session)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"research_seed_failed:{type(exc).__name__}:{exc}")

        seen_keys: set[tuple[str, str]] = set()  # (source, secid) for successful boards
        successful_boards = 0
        failed_or_empty_boards = 0
        board_rows: dict[str, list[MoexSecurityRow]] = {}

        for market, board in self.boards:
            key = f"{market}:{board}"
            try:
                rows = self.client.fetch_board_securities(market, board)
            except Exception as exc:  # noqa: BLE001
                failed_or_empty_boards += 1
                report.boards[key] = {
                    "status": "ERROR",
                    "count": 0,
                    "error": f"{type(exc).__name__}:{exc}",
                }
                report.errors.append(f"board_fetch_failed:{key}:{type(exc).__name__}")
                continue

            if not rows:
                # CRITICAL §29-30: empty/failed must NOT mass-deactivate.
                failed_or_empty_boards += 1
                report.boards[key] = {"status": "EMPTY", "count": 0}
                report.notes.append(f"empty_board_skipped_deactivate:{key}")
                continue

            successful_boards += 1
            board_rows[key] = rows
            report.boards[key] = {"status": "OK", "count": len(rows)}
            source = SOURCE_MOEX if market == "shares" else SOURCE_MOEX_ISS
            for row in rows:
                seen_keys.add((source, row.secid))

        if successful_boards == 0:
            report.mass_deactivate_blocked = True
            report.status = "FAILED_EMPTY"
            report.notes.append("all_boards_failed_or_empty_no_deactivate")
            report.finished_at = datetime.now(UTC).isoformat()
            run_row.status = report.status
            run_row.finished_at = datetime.now(UTC)
            run_row.report = report.to_dict()
            self.session.flush()
            return report.to_dict()

        # Upsert instruments from successful boards only.
        for key, rows in board_rows.items():
            market, board = key.split(":", 1)
            for row in rows:
                self._upsert_row(row, report)

        # Deactivate only when we have successful coverage and symbol absent.
        if self.deactivate_missing and failed_or_empty_boards == 0:
            deactivated = self._deactivate_missing(seen_keys, report)
            report.deactivated = deactivated
        elif self.deactivate_missing and failed_or_empty_boards > 0:
            report.mass_deactivate_blocked = True
            report.notes.append(
                "partial_board_failure_skip_deactivate:"
                f"ok={successful_boards},failed_or_empty={failed_or_empty_boards}"
            )

        report.status = "SUCCESS" if not report.errors else "SUCCESS_WITH_ERRORS"
        finished = datetime.now(UTC)
        report.finished_at = finished.isoformat()
        run_row.status = report.status
        run_row.finished_at = finished
        run_row.report = report.to_dict()
        self.session.flush()
        logger.info("instrument_master_sync_complete", extra=report.to_dict())
        return report.to_dict()

    def _upsert_row(self, row: MoexSecurityRow, report: SyncReport) -> None:
        classification = classify_moex_row(
            secid=row.secid,
            board=row.board,
            name=row.name,
            sec_type=row.sec_type,
            isin=row.isin,
            market=row.market,
            is_traded=row.is_traded,
            extra=row.raw,
        )
        source = SOURCE_MOEX if row.market == "shares" else SOURCE_MOEX_ISS
        now = datetime.now(UTC)

        existing = self.session.scalar(
            select(Instrument).where(
                Instrument.symbol == row.secid,
                Instrument.exchange == "MOEX",
            )
        )
        if existing is None:
            existing = Instrument(
                symbol=row.secid,
                name=row.name or row.secid,
                asset_class=classification.asset_class,
                exchange="MOEX",
                currency=row.currency or "RUB",
                isin=row.isin,
                is_active=classification.support_level != INACTIVE,
                instrument_subtype=classification.instrument_subtype,
                support_level=classification.support_level,
                primary_board=row.board,
                first_seen_at=now,
                last_seen_at=now,
            )
            self.session.add(existing)
            self.session.flush()
            report.created += 1
        else:
            changed = False
            if row.name and existing.name != row.name:
                existing.name = row.name
                changed = True
            if row.isin and existing.isin != row.isin:
                existing.isin = row.isin
                changed = True
            if existing.instrument_subtype != classification.instrument_subtype:
                existing.instrument_subtype = classification.instrument_subtype
                changed = True
            if existing.support_level != classification.support_level:
                existing.support_level = classification.support_level
                changed = True
            if existing.asset_class != classification.asset_class and existing.asset_class != "index":
                # Do not overwrite curated index rows with wrong class.
                if classification.asset_class != "other":
                    existing.asset_class = classification.asset_class
                    changed = True
            boards = [row.board]
            if existing.primary_board:
                boards.append(existing.primary_board)
            primary = pick_primary_board(boards)
            if primary and existing.primary_board != primary:
                existing.primary_board = primary
                changed = True
            if classification.support_level == INACTIVE:
                if existing.is_active:
                    existing.is_active = False
                    changed = True
            elif not existing.is_active and classification.support_level != INACTIVE:
                # Re-activate only if previously catalog-inactive from MOEX.
                existing.is_active = True
                changed = True
            existing.last_seen_at = now
            if existing.first_seen_at is None:
                existing.first_seen_at = now
                changed = True
            existing.updated_at = now
            if changed:
                report.updated += 1
            else:
                report.unchanged += 1

        # Upsert source mapping (current open-ended).
        meta: dict[str, Any] = {}
        if row.lotsize is not None:
            meta[LOTSIZE_META_KEY] = row.lotsize
            meta[LOTSIZE_PROVENANCE_KEY] = {
                "field": "LOTSIZE",
                "source": "MOEX_ISS_BOARD_LIST",
                "board": row.board,
                "external_id": row.secid,
                "fetched_at": now.isoformat(),
                "value": row.lotsize,
            }
            report.lotsize_updated += 1
        if row.sec_type:
            meta["SECTYPE"] = row.sec_type
        if row.isin:
            meta["ISIN"] = row.isin

        stmt = insert(InstrumentSource).values(
            instrument_id=int(existing.id),
            source=source,
            external_id=row.secid,
            board=row.board,
            source_metadata=meta or {},
        )
        session_result = self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    InstrumentSource.source,
                    InstrumentSource.external_id,
                    InstrumentSource.board,
                ],
                set_={"instrument_id": int(existing.id)},
            )
        )
        _ = session_result
        # Merge LOTSIZE into existing metadata if source already present.
        src = self.session.scalar(
            select(InstrumentSource).where(
                InstrumentSource.source == source,
                InstrumentSource.external_id == row.secid,
                InstrumentSource.board == row.board,
            )
        )
        if src is not None and meta:
            merged = dict(src.source_metadata or {})
            merged.update(meta)
            src.source_metadata = merged
            flag_modified(src, "source_metadata")
            src.instrument_id = int(existing.id)

        # Async FI enrichment for bonds — never auto-grows research_fi_v1.
        if (existing.asset_class or "").lower() == "bond":
            try:
                from app.modules.investment.application.enrichment_service import (
                    enqueue_new_bond_from_master,
                )

                enqueue_new_bond_from_master(self.session, existing)
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"fi_enqueue_failed:{existing.symbol}:{type(exc).__name__}")

    def _deactivate_missing(
        self, seen_keys: set[tuple[str, str]], report: SyncReport
    ) -> int:
        """Mark MOEX-sourced instruments inactive when absent from successful board lists.

        Never removes research membership. Skips curated indexes.
        """
        sources = list(
            self.session.scalars(
                select(InstrumentSource).where(
                    InstrumentSource.source.in_([SOURCE_MOEX, SOURCE_MOEX_ISS]),
                    InstrumentSource.valid_to.is_(None),
                )
            )
        )
        by_instrument: dict[int, list[InstrumentSource]] = {}
        for src in sources:
            by_instrument.setdefault(int(src.instrument_id), []).append(src)

        deactivated = 0
        for instrument_id, srcs in by_instrument.items():
            instrument = self.session.get(Instrument, instrument_id)
            if instrument is None:
                continue
            if instrument.asset_class == "index":
                continue
            # Present if any current mapping's (source, external_id) was seen.
            present = any((s.source, str(s.external_id).upper()) in seen_keys for s in srcs)
            if present:
                continue
            if not instrument.is_active and instrument.support_level == INACTIVE:
                continue
            instrument.is_active = False
            instrument.support_level = INACTIVE
            instrument.updated_at = datetime.now(UTC)
            deactivated += 1
            report.notes.append(f"deactivated:{instrument.symbol}")
        return deactivated


def try_acquire_master_sync_lock(token: str, *, ttl: int = LOCK_TTL_SECONDS) -> bool:
    try:
        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=False)
        return bool(client.set(LOCK_KEY, token, nx=True, ex=ttl))
    except Exception as exc:  # noqa: BLE001
        logger.warning("instrument_master_lock_unavailable", extra={"error": str(exc)})
        return False


def release_master_sync_lock(token: str) -> None:
    try:
        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=False)
        current = client.get(LOCK_KEY)
        if current is not None and current.decode() == token:
            client.delete(LOCK_KEY)
    except Exception as exc:  # noqa: BLE001
        logger.warning("instrument_master_lock_release_failed", extra={"error": str(exc)})


def run_instrument_master_sync(
    session: Session,
    *,
    client: BoardSecuritiesPort | None = None,
    acquire_lock: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    if not getattr(settings, "moex_instrument_master_sync_enabled", False) and acquire_lock:
        # Manual API may call with acquire_lock=False / explicit allow; scheduled respects flag.
        pass

    token = uuid4().hex
    if acquire_lock and not try_acquire_master_sync_lock(token):
        return {"status": "SKIPPED_LOCK", "errors": ["lock_held"]}

    try:
        return MoexInstrumentMasterSync(session, client=client).run()
    finally:
        if acquire_lock:
            release_master_sync_lock(token)


def latest_sync_status(session: Session) -> dict[str, Any] | None:
    row = session.scalar(
        select(InstrumentMasterSyncRun).order_by(InstrumentMasterSyncRun.started_at.desc())
    )
    if row is None:
        return None
    return {
        "id": row.id,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "status": row.status,
        "report": row.report or {},
    }


def maybe_startup_instrument_master_catchup(session: Session) -> dict[str, Any]:
    """Non-blocking stale schedule: enqueue/run only when enabled and last SUCCESS is stale."""
    settings = get_settings()
    if not settings.moex_instrument_master_sync_enabled:
        return {"status": "DISABLED", "reason": "MOEX_INSTRUMENT_MASTER_SYNC_ENABLED=false"}

    latest = latest_sync_status(session)
    stale_hours = int(settings.moex_instrument_master_stale_hours)
    if latest and latest.get("status") in {"SUCCESS", "SUCCESS_WITH_ERRORS"}:
        finished = latest.get("finished_at") or latest.get("started_at")
        if finished:
            try:
                ts = datetime.fromisoformat(str(finished))
                age_h = (datetime.now(UTC) - ts).total_seconds() / 3600.0
                if age_h < stale_hours:
                    return {"status": "FRESH", "age_hours": age_h, "latest": latest}
            except ValueError:
                pass

    # Schedule async via Celery if available; never block boot on full sync.
    try:
        from app.worker import tasks as worker_tasks

        async_result = worker_tasks.sync_moex_instrument_master.delay()
        return {
            "status": "SCHEDULED",
            "task_id": getattr(async_result, "id", None),
            "latest": latest,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("instrument_master_startup_schedule_failed", extra={"error": str(exc)})
        return {"status": "SCHEDULE_FAILED", "error": str(exc), "latest": latest}
