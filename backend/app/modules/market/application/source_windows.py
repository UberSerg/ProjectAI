"""Populate trusted MOEX source validity windows for the current universe only."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.application.system.event_log import write_event
from app.core.logging import get_logger
from app.infrastructure.market.models import IngestionBatch, Instrument, Workflow
from app.infrastructure.market.moex_iss import MoexBoardWindow, MoexIssProvider
from app.infrastructure.market.raw_store import RawStore
from app.modules.market.application.identity import (
    SOURCE_MOEX,
    apply_source_window,
    resolve_current_source,
)
from app.modules.market.application.workflows import (
    create_workflow,
    finish_workflow,
    get_step,
    update_step,
)

logger = get_logger(__name__, component="market-source-windows")

WINDOW_SYNC_STEPS = [
    "Load instruments",
    "Fetch MOEX boards",
    "Normalize / Persist",
    "Finish",
]

# Main-mode predecessor of TQBR after the 2013 T+ board migration. Not a SBER-only rule.
TQBR_PREDECESSOR = "EQBR"
CURRENT_BOARD_MARKET = {"TQBR": "shares", "SNDX": "index", "RTSI": "index"}


@dataclass(frozen=True, slots=True)
class WindowDraft:
    external_id: str
    board: str
    valid_from: date | None
    valid_to: date | None
    role: str
    metadata: dict[str, Any]


class BoardFeed(Protocol):
    def fetch_security_boards(self, secid: str) -> tuple[list[MoexBoardWindow], bytes]: ...


def normalize_source_windows(
    *,
    current_secid: str,
    current_board: str,
    boards: list[MoexBoardWindow],
) -> tuple[list[WindowDraft], list[str]]:
    """Trusted drafts for one current mapping. Does not guess other SECIDs."""
    notes: list[str] = []
    current_board = (current_board or "").upper()
    current_secid = current_secid.strip()
    expected_market = CURRENT_BOARD_MARKET.get(current_board)
    matched = [
        row
        for row in boards
        if row.board.upper() == current_board
        and row.secid == current_secid
        and (expected_market is None or row.market == expected_market)
    ]
    if not matched:
        notes.append("current_board_missing")
        return [], notes
    current_row = next((row for row in matched if row.is_primary), matched[0])
    if current_row.history_from is None:
        notes.append("history_from_absent")
        return [], notes
    drafts = [
        WindowDraft(
            external_id=current_secid,
            board=current_board,
            valid_from=current_row.history_from,
            valid_to=None,
            role="current",
            metadata={
                "source_feed": "iss/securities",
                "history_from": current_row.history_from.isoformat(),
                "listed_from": None if current_row.listed_from is None else current_row.listed_from.isoformat(),
                "window_field": "history_from",
            },
        )
    ]
    predecessor = _predecessor_draft(current_secid, current_board, current_row.history_from, boards)
    if predecessor is not None:
        drafts.append(predecessor)
    return drafts, notes


def _predecessor_draft(
    current_secid: str,
    current_board: str,
    current_from: date,
    boards: list[MoexBoardWindow],
) -> WindowDraft | None:
    if current_board != "TQBR":
        return None
    predecessors = [
        row
        for row in boards
        if row.board.upper() == TQBR_PREDECESSOR
        and row.secid == current_secid
        and row.market == "shares"
        and row.history_from is not None
        and row.history_from < current_from
    ]
    if not predecessors:
        return None
    row = min(predecessors, key=lambda item: item.history_from or date.max)
    return WindowDraft(
        external_id=current_secid,
        board=TQBR_PREDECESSOR,
        valid_from=row.history_from,
        valid_to=current_from,
        role="historical",
        metadata={
            "source_feed": "iss/securities",
            "history_from": None if row.history_from is None else row.history_from.isoformat(),
            "history_till": None if row.history_till is None else row.history_till.isoformat(),
            "clipped_to": current_from.isoformat(),
            "clip_reason": "primary_board_history_from",
        },
    )


class SourceWindowSyncService:
    def __init__(
        self,
        session: Session,
        *,
        provider: BoardFeed | None = None,
        raw_store: RawStore | None = None,
        pause_seconds: float = 0.1,
    ) -> None:
        self.session = session
        self.provider = provider or MoexIssProvider()
        self.raw_store = raw_store or RawStore()
        self.pause_seconds = pause_seconds

    def run(self, *, workflow_id: int | None = None, symbols: list[str] | None = None) -> dict[str, Any]:
        workflow = self._resolve_workflow(workflow_id)
        batch = IngestionBatch(
            source=SOURCE_MOEX,
            data_type="source_windows",
            status="running",
            workflow_id=workflow.id,
            meta={},
        )
        self.session.add(batch)
        self.session.flush()
        write_event(
            self.session,
            level="INFO",
            component="market-source-windows",
            event_type="source_windows_sync_started",
            message="MOEX source-window sync started",
            details={"workflow_id": workflow.id, "batch_id": batch.id},
            workflow_id=workflow.id,
            batch_id=str(batch.id),
        )
        try:
            update_step(self.session, get_step(workflow, "Load instruments"), "RUNNING")
            instruments = self._load_instruments(symbols)
            update_step(self.session, get_step(workflow, "Load instruments"), "SUCCESS")

            update_step(self.session, get_step(workflow, "Fetch MOEX boards"), "RUNNING")
            fetched, raw_paths = self._fetch(instruments, batch.id)
            batch.raw_location = ";".join(raw_paths[:20]) or None
            update_step(self.session, get_step(workflow, "Fetch MOEX boards"), "SUCCESS")

            update_step(self.session, get_step(workflow, "Normalize / Persist"), "RUNNING")
            summary = self._persist(instruments, fetched)
            update_step(self.session, get_step(workflow, "Normalize / Persist"), "SUCCESS")

            batch.records_received = summary["received"]
            batch.records_inserted = summary["inserted"]
            batch.records_updated = summary["updated"]
            batch.records_rejected = summary["unknown"] + summary["ambiguous"] + summary["failed"]
            batch.meta = {k: v for k, v in summary.items() if k != "identity_change_candidates"}
            batch.status = "success"
            batch.finished_at = datetime.now(UTC)
            workflow.meta = {**(workflow.meta or {}), "source_windows": summary}
            update_step(self.session, get_step(workflow, "Finish"), "SUCCESS")
            finish_workflow(self.session, workflow, "SUCCESS")
            write_event(
                self.session,
                level="INFO",
                component="market-source-windows",
                event_type="source_windows_sync_succeeded",
                message=(
                    "MOEX source-window sync finished: "
                    f"received={summary['received']} inserted={summary['inserted']} "
                    f"updated={summary['updated']} unchanged={summary['unchanged']} "
                    f"unknown={summary['unknown']} ambiguous={summary['ambiguous']} "
                    f"failed={summary['failed']}"
                ),
                details={k: v for k, v in summary.items() if k != "identity_change_candidates"},
                workflow_id=workflow.id,
                batch_id=str(batch.id),
            )
            return {"workflow_id": workflow.id, "batch_id": batch.id, **summary}
        except Exception as exc:
            batch.status = "error"
            batch.error_message = str(exc)[:2000]
            batch.finished_at = datetime.now(UTC)
            try:
                finish_workflow(self.session, workflow, "ERROR", error=str(exc)[:2000])
            except Exception:
                logger.exception("source_windows_workflow_finish_failed")
            write_event(
                self.session,
                level="ERROR",
                component="market-source-windows",
                event_type="source_windows_sync_failed",
                message="MOEX source-window sync failed",
                details={"error": str(exc)[:500]},
                workflow_id=workflow.id,
                batch_id=str(batch.id),
            )
            raise

    def _resolve_workflow(self, workflow_id: int | None) -> Workflow:
        if workflow_id is not None:
            workflow = self.session.get(Workflow, workflow_id)
            if workflow is None:
                raise ValueError(f"Workflow {workflow_id} not found")
            return workflow
        return create_workflow(
            self.session,
            "MarketSourceWindowsSync",
            "MOEX source validity windows",
            WINDOW_SYNC_STEPS,
        )

    def _load_instruments(self, symbols: list[str] | None = None) -> list[Instrument]:
        stmt = (
            select(Instrument)
            .options(selectinload(Instrument.sources))
            .where(Instrument.is_active.is_(True), Instrument.exchange == "MOEX")
            .order_by(Instrument.symbol)
        )
        if symbols:
            stmt = stmt.where(Instrument.symbol.in_(symbols))
        return list(self.session.scalars(stmt).unique().all())

    def _fetch(
        self, instruments: list[Instrument], batch_id: int
    ) -> tuple[dict[int, list[MoexBoardWindow]], list[str]]:
        fetched: dict[int, list[MoexBoardWindow]] = {}
        paths: list[str] = []
        for instrument in instruments:
            current = resolve_current_source(self.session, instrument.id, SOURCE_MOEX)
            if current is None:
                continue
            if self.pause_seconds:
                time.sleep(self.pause_seconds)
            boards, raw = self.provider.fetch_security_boards(current.external_id)
            fetched[instrument.id] = boards
            paths.append(
                self.raw_store.save(
                    source="moex",
                    data_type="source_windows",
                    batch_id=batch_id,
                    name=f"{current.external_id}_boards",
                    payload=raw,
                    content_type="application/json",
                )
            )
        return fetched, paths

    def _persist(
        self,
        instruments: list[Instrument],
        fetched: dict[int, list[MoexBoardWindow]],
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "received": len(instruments),
            "resolved": 0,
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "unknown": 0,
            "ambiguous": 0,
            "failed": 0,
            "identity_change_candidates": [],
        }
        for instrument in instruments:
            current = resolve_current_source(self.session, instrument.id, SOURCE_MOEX)
            if current is None:
                summary["unknown"] += 1
                continue
            boards = fetched.get(instrument.id)
            if boards is None:
                summary["failed"] += 1
                continue
            foreign = sorted({row.secid for row in boards if row.secid and row.secid != current.external_id})
            if foreign:
                summary["identity_change_candidates"].append(
                    {
                        "symbol": instrument.symbol,
                        "external_id": current.external_id,
                        "foreign_secids": foreign[:5],
                        "reason": "iss_board_secid_mismatch_not_merged",
                    }
                )
            drafts, notes = normalize_source_windows(
                current_secid=current.external_id,
                current_board=current.board or "",
                boards=boards,
            )
            if not drafts:
                if "current_board_missing" in notes or "history_from_absent" in notes:
                    summary["unknown"] += 1
                else:
                    summary["failed"] += 1
                continue
            summary["resolved"] += 1
            for draft in drafts:
                action = apply_source_window(
                    self.session,
                    instrument_id=instrument.id,
                    source=SOURCE_MOEX,
                    external_id=draft.external_id,
                    board=draft.board,
                    valid_from=draft.valid_from,
                    valid_to=draft.valid_to,
                    source_metadata=draft.metadata,
                )
                if action == "inserted":
                    summary["inserted"] += 1
                elif action == "updated":
                    summary["updated"] += 1
                elif action == "unchanged":
                    summary["unchanged"] += 1
                else:
                    summary["ambiguous"] += 1
        self.session.flush()
        return summary


def coverage_snapshot(session: Session, checkpoints: tuple[date, ...]) -> dict[str, Any]:
    from app.modules.market.application.identity import resolve_source_as_of

    instruments = list(
        session.scalars(
            select(Instrument)
            .options(selectinload(Instrument.sources))
            .where(Instrument.is_active.is_(True), Instrument.exchange == "MOEX")
        )
        .unique()
        .all()
    )
    proven = 0
    unknown = 0
    earliest: dict[str, str | None] = {}
    by_checkpoint = {point.isoformat(): 0 for point in checkpoints}
    for instrument in instruments:
        current = resolve_current_source(session, instrument.id, SOURCE_MOEX)
        windows = [
            src.valid_from
            for src in instrument.sources
            if src.source == SOURCE_MOEX and src.valid_from is not None
        ]
        earliest[instrument.symbol] = None if not windows else min(windows).isoformat()
        if current is None or current.valid_from is None:
            unknown += 1
            continue
        proven += 1
        for point in checkpoints:
            if resolve_source_as_of(session, instrument.id, point, SOURCE_MOEX) is not None:
                by_checkpoint[point.isoformat()] += 1
    return {
        "total": len(instruments),
        "proven_current": proven,
        "unknown_current": unknown,
        "earliest_proven": earliest,
        "available_by": by_checkpoint,
    }
