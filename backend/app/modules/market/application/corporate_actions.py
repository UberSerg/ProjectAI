"""SPLIT ingestion: MOEX provider → draft → resolve → upsert. Does not touch candles."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.system.event_log import write_event
from app.core.logging import get_logger
from app.infrastructure.market.models import CorporateAction, IngestionBatch, InstrumentSource, Workflow
from app.infrastructure.market.moex_iss import MoexIssProvider
from app.infrastructure.market.raw_store import RawStore
from app.modules.market.application.data_quality import annotate_jumps_explained_by_splits
from app.modules.market.application.split_events import (
    SOURCE_MOEX,
    SPLIT_FEED_EVENT_TYPES,
    SplitEventDraft,
    SplitParseResult,
    classify_split_factor,
    payload_for_split,
    validate_split_ratio,
)
from app.modules.market.application.workflows import (
    create_workflow,
    finish_workflow,
    get_step,
    update_step,
)

logger = get_logger(__name__, component="market-splits")

SPLIT_INGEST_STEPS = [
    "Fetch MOEX splits",
    "Save RAW",
    "Resolve / Persist",
    "Annotate DQ",
    "Finish",
]


class SplitFeed(Protocol):
    def fetch_stock_splits(self) -> tuple[SplitParseResult, tuple[bytes, ...]]: ...


def resolve_moex_secid(session: Session, secid: str) -> int | None:
    """Map official SECID via current instrument_sources. Does not create instruments."""
    rows = list(
        session.scalars(
            select(InstrumentSource).where(
                InstrumentSource.source == SOURCE_MOEX,
                InstrumentSource.external_id == secid,
            )
        )
    )
    if not rows:
        return None
    preferred = next((row for row in rows if (row.board or "").upper() == "TQBR"), None)
    return (preferred or rows[0]).instrument_id


def upsert_split_event(session: Session, instrument_id: int, draft: SplitEventDraft) -> str:
    validate_split_ratio(draft.split_before, draft.split_after)
    if classify_split_factor(draft.adjustment_factor) != draft.event_type:
        raise ValueError("draft event_type does not match split factor classification")
    existing = session.scalar(
        select(CorporateAction).where(
            CorporateAction.instrument_id == instrument_id,
            CorporateAction.event_date == draft.effective_date,
            CorporateAction.source == draft.source,
            CorporateAction.external_id == draft.secid,
            CorporateAction.event_type.in_(SPLIT_FEED_EVENT_TYPES),
        )
    )
    payload = payload_for_split(draft)
    if existing is not None:
        same_semantics = (
            existing.event_type == draft.event_type
            and existing.payload == payload
            and existing.known_at is None
        )
        if same_semantics:
            return "unchanged"
        existing.event_type = draft.event_type
        existing.payload = payload
        existing.known_at = None
        return "updated"
    session.add(
        CorporateAction(
            instrument_id=instrument_id,
            event_date=draft.effective_date,
            event_type=draft.event_type,
            payload=payload,
            source=draft.source,
            external_id=draft.secid,
            known_at=None,
        )
    )
    return "inserted"


class SplitIngestionService:
    def __init__(
        self,
        session: Session,
        *,
        provider: SplitFeed | None = None,
        raw_store: RawStore | None = None,
    ) -> None:
        self.session = session
        self.provider = provider or MoexIssProvider()
        self.raw_store = raw_store or RawStore()

    def run(self, *, workflow_id: int | None = None) -> dict[str, Any]:
        workflow = self._resolve_workflow(workflow_id)
        batch = IngestionBatch(
            source=SOURCE_MOEX,
            data_type="splits",
            status="running",
            workflow_id=workflow.id,
            meta={},
        )
        self.session.add(batch)
        self.session.flush()
        write_event(
            self.session,
            level="INFO",
            component="market-splits",
            event_type="splits_ingest_started",
            message="MOEX SPLIT ingestion started",
            details={"workflow_id": workflow.id, "batch_id": batch.id},
            workflow_id=workflow.id,
            batch_id=str(batch.id),
        )
        try:
            update_step(self.session, get_step(workflow, "Fetch MOEX splits"), "RUNNING")
            parsed, raw_payloads = self.provider.fetch_stock_splits()
            update_step(self.session, get_step(workflow, "Fetch MOEX splits"), "SUCCESS")

            update_step(self.session, get_step(workflow, "Save RAW"), "RUNNING")
            raw_paths = self._save_raw(batch.id, raw_payloads)
            batch.raw_location = ";".join(raw_paths[:20]) or None
            update_step(self.session, get_step(workflow, "Save RAW"), "SUCCESS")

            update_step(self.session, get_step(workflow, "Resolve / Persist"), "RUNNING")
            summary = self._persist(parsed)
            update_step(self.session, get_step(workflow, "Resolve / Persist"), "SUCCESS")

            update_step(self.session, get_step(workflow, "Annotate DQ"), "RUNNING")
            annotated = annotate_jumps_explained_by_splits(self.session)
            summary["dq_annotated"] = annotated
            update_step(self.session, get_step(workflow, "Annotate DQ"), "SUCCESS")

            batch.records_received = summary["received"]
            batch.records_inserted = summary["inserted"]
            batch.records_updated = summary["updated"]
            batch.records_rejected = summary["rejected"] + summary["unresolved"]
            batch.meta = {
                "resolved": summary["resolved"],
                "unresolved": summary["unresolved"],
                "unresolved_secids": summary["unresolved_secids"],
                "dq_annotated": annotated,
            }
            batch.status = "success"
            batch.finished_at = datetime.now(UTC)
            workflow.meta = {**(workflow.meta or {}), "splits": summary}
            update_step(self.session, get_step(workflow, "Finish"), "SUCCESS")
            finish_workflow(self.session, workflow, "SUCCESS")
            write_event(
                self.session,
                level="INFO",
                component="market-splits",
                event_type="splits_ingest_succeeded",
                message=(
                    "MOEX SPLIT ingestion finished: "
                    f"received={summary['received']} resolved={summary['resolved']} "
                    f"inserted={summary['inserted']} updated={summary['updated']} "
                    f"unresolved={summary['unresolved']} rejected={summary['rejected']}"
                ),
                details=summary,
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
                logger.exception("splits_workflow_finish_failed")
            write_event(
                self.session,
                level="ERROR",
                component="market-splits",
                event_type="splits_ingest_failed",
                message="MOEX SPLIT ingestion failed",
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
            "MarketSplitsIngest",
            "MOEX SPLIT corporate actions",
            SPLIT_INGEST_STEPS,
        )

    def _save_raw(self, batch_id: int, raw_payloads: tuple[bytes, ...]) -> list[str]:
        paths: list[str] = []
        for index, payload in enumerate(raw_payloads):
            paths.append(
                self.raw_store.save(
                    source="moex",
                    data_type="splits",
                    batch_id=batch_id,
                    name=f"splits_{index}",
                    payload=payload,
                    content_type="application/json",
                )
            )
        return paths

    def _persist(self, parsed: SplitParseResult) -> dict[str, Any]:
        inserted = 0
        updated = 0
        unchanged = 0
        rejected = parsed.rejected
        unresolved_secids: list[str] = []
        seen_unresolved: set[str] = set()
        resolved = 0
        for draft in parsed.accepted:
            try:
                validate_split_ratio(draft.split_before, draft.split_after)
            except ValueError:
                rejected += 1
                continue
            if classify_split_factor(draft.adjustment_factor) != draft.event_type:
                rejected += 1
                continue
            instrument_id = resolve_moex_secid(self.session, draft.secid)
            if instrument_id is None:
                if draft.secid not in seen_unresolved:
                    seen_unresolved.add(draft.secid)
                    unresolved_secids.append(draft.secid)
                continue
            resolved += 1
            action = upsert_split_event(self.session, instrument_id, draft)
            if action == "inserted":
                inserted += 1
            elif action == "updated":
                updated += 1
            else:
                unchanged += 1
        self.session.flush()
        return {
            "received": parsed.received,
            "resolved": resolved,
            "inserted": inserted,
            "updated": updated,
            "unchanged": unchanged,
            "unresolved": len(unresolved_secids),
            "rejected": rejected,
            "unresolved_secids": unresolved_secids[:20],
        }
