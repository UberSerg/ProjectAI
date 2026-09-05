"""Copy structured SPLIT / REVERSE_SPLIT events into fundamentals.corporate_events.

market.corporate_actions stays the source of truth for splits; this is a projection
into the event store so PIT event features have one place to read from.

``known_at`` is mandatory here but nullable there. When the market row has no
availability timestamp we fall back to the effective date, which is the date the split
becomes observable on the board. That is later than the real announcement, so it is
conservative — it can only hide information, never leak it. The basis is recorded in
``payload.known_at_basis`` so a future announcement feed can tighten it deliberately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import CorporateAction
from app.modules.fundamentals.application.pit import resolve_issuer_for_instrument
from app.modules.fundamentals.application.runs import finish_run, start_run
from app.modules.fundamentals.config import PROVIDER_CORPORATE_EVENTS
from app.modules.fundamentals.domain.types import (
    SOURCE_MARKET_CORPORATE_ACTIONS,
    CorporateEventType,
    IngestionStatus,
)
from app.modules.fundamentals.infrastructure.models import (
    CorporateEvent,
    fundamentals_schema_ready,
)

BASIS_SOURCE_KNOWN_AT = "SOURCE_KNOWN_AT"
BASIS_EFFECTIVE_DATE_OBSERVABLE = "EFFECTIVE_DATE_OBSERVABLE"

SYNCED_EVENT_TYPES: tuple[str, ...] = (
    CorporateEventType.SPLIT.value,
    CorporateEventType.REVERSE_SPLIT.value,
)


@dataclass
class CorporateEventsSyncResult:
    status: str = IngestionStatus.NO_CHANGES.value
    source_rows: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    without_issuer: int = 0
    errors: list[str] = field(default_factory=list)
    run_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "source_rows": self.source_rows,
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "without_issuer": self.without_issuer,
            "errors": self.errors[:20],
            "error_count": len(self.errors),
        }


def sync_corporate_events(session: Session) -> CorporateEventsSyncResult:
    """Idempotent projection of the SPLIT feed. Never writes market.* tables."""
    result = CorporateEventsSyncResult()
    if not fundamentals_schema_ready(session):
        result.status = IngestionStatus.FAILED.value
        result.errors.append("fundamentals schema missing; apply alembic 20260905_0018")
        return result

    run = start_run(session, PROVIDER_CORPORATE_EVENTS, requested_range="all")
    result.run_id = run.id

    actions = list(
        session.scalars(
            select(CorporateAction)
            .where(CorporateAction.event_type.in_(SYNCED_EVENT_TYPES))
            .order_by(CorporateAction.event_date, CorporateAction.id)
        )
    )
    result.source_rows = len(actions)

    for action in actions:
        if action.known_at is not None:
            known_at = action.known_at.date()
            basis = BASIS_SOURCE_KNOWN_AT
        else:
            known_at = action.event_date
            basis = BASIS_EFFECTIVE_DATE_OBSERVABLE

        resolution = resolve_issuer_for_instrument(session, action.instrument_id, action.event_date)
        if resolution.issuer_id is None:
            result.without_issuer += 1

        payload: dict[str, Any] = {
            **(action.payload or {}),
            "known_at_basis": basis,
            "issuer_mapping_basis": resolution.basis,
            "market_corporate_action_id": action.id,
            "market_source": action.source,
        }

        existing = session.scalar(
            select(CorporateEvent).where(
                CorporateEvent.event_type == action.event_type,
                CorporateEvent.instrument_id == action.instrument_id,
                CorporateEvent.event_date == action.event_date,
                CorporateEvent.source == SOURCE_MARKET_CORPORATE_ACTIONS,
            )
        )
        if existing is None:
            session.add(
                CorporateEvent(
                    issuer_id=resolution.issuer_id,
                    instrument_id=action.instrument_id,
                    event_type=action.event_type,
                    event_date=action.event_date,
                    known_at=known_at,
                    effective_date=action.event_date,
                    source=SOURCE_MARKET_CORPORATE_ACTIONS,
                    external_id=action.external_id,
                    payload=payload,
                )
            )
            session.flush()
            result.inserted += 1
            continue

        changed = False
        # known_at is only tightened when the market feed itself starts declaring one.
        if basis == BASIS_SOURCE_KNOWN_AT and existing.known_at != known_at:
            existing.known_at = known_at
            changed = True
        if resolution.issuer_id is not None and existing.issuer_id != resolution.issuer_id:
            existing.issuer_id = resolution.issuer_id
            changed = True
        if existing.payload != payload:
            existing.payload = payload
            changed = True
        if changed:
            session.flush()
            result.updated += 1
        else:
            result.unchanged += 1

    if result.inserted or result.updated:
        status = IngestionStatus.SUCCESS
    else:
        status = IngestionStatus.NO_CHANGES
    result.status = status.value
    finish_run(session, run, status=status, summary=result.to_dict())
    return result
