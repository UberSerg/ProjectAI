"""Dividend ingestion adapter.

Both MOEX ISS dividend endpoints were rejected by the live audit, so the default path
records a DEFERRED run and writes nothing. Dividends are never credited to a portfolio
here, and raw dividend gaps in market.candles are never repaired.

When a provider is injected, each disclosure is appended as a new version of its payout
series instead of overwriting the previous one; a row without ``known_at`` is rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fundamentals.application.runs import finish_run, start_run
from app.modules.fundamentals.config import PROVIDER_DIVIDENDS
from app.modules.fundamentals.domain.types import (
    DeferralReason,
    DividendEventRef,
    IngestionStatus,
)
from app.modules.fundamentals.infrastructure.models import (
    DividendEvent,
    fundamentals_schema_ready,
)
from app.modules.fundamentals.ports import DividendProvider


@dataclass
class DividendIngestResult:
    status: str = IngestionStatus.DEFERRED.value
    reason: str | None = None
    events_received: int = 0
    events_inserted: int = 0
    events_skipped: int = 0
    rejections: list[str] = field(default_factory=list)
    run_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "run_id": self.run_id,
            "events_received": self.events_received,
            "events_inserted": self.events_inserted,
            "events_skipped": self.events_skipped,
            "rejections": self.rejections[:20],
        }


def _existing_version(session: Session, event: DividendEventRef) -> DividendEvent | None:
    return session.scalar(
        select(DividendEvent).where(
            DividendEvent.issuer_id == event.issuer_id,
            DividendEvent.instrument_id == event.instrument_id,
            DividendEvent.source == event.source,
            DividendEvent.record_date == event.record_date,
            DividendEvent.ex_date == event.ex_date,
            DividendEvent.version == event.version,
        )
    )


def run_dividend_ingestion(
    session: Session,
    *,
    provider: DividendProvider | None = None,
    issuer_ids: list[int] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> DividendIngestResult:
    """Idempotent. Records DEFERRED and writes nothing when no provider is configured."""
    result = DividendIngestResult()
    if not fundamentals_schema_ready(session):
        result.status = IngestionStatus.FAILED.value
        result.reason = "fundamentals schema missing; apply alembic 20260905_0018"
        return result

    requested_range = f"{date_from or '-'}..{date_to or '-'}"
    run = start_run(session, PROVIDER_DIVIDENDS, requested_range=requested_range)
    result.run_id = run.id

    if provider is None:
        result.status = IngestionStatus.DEFERRED.value
        result.reason = DeferralReason.SOURCE_REJECTED_BY_AUDIT.value
        finish_run(
            session,
            run,
            status=IngestionStatus.DEFERRED,
            summary={
                **result.to_dict(),
                "note": (
                    "MOEX ISS /iss/securities/{SECID}/dividends.json returns the security "
                    "description, not dividends; the history variant returns candles. "
                    "Nothing was written and no portfolio was credited."
                ),
            },
        )
        return result

    for issuer_id in issuer_ids or []:
        for event in provider.fetch_dividends(issuer_id, date_from=date_from, date_to=date_to):
            result.events_received += 1
            if getattr(event, "known_at", None) is None:
                result.events_skipped += 1
                result.rejections.append(
                    f"{DeferralReason.MISSING_KNOWN_AT.value}: issuer {issuer_id}"
                )
                continue
            if _existing_version(session, event) is not None:
                result.events_skipped += 1
                continue
            session.add(
                DividendEvent(
                    issuer_id=event.issuer_id,
                    instrument_id=event.instrument_id,
                    announcement_date=event.announcement_date,
                    known_at=event.known_at,
                    board_recommendation_date=event.board_recommendation_date,
                    shareholder_approval_date=event.shareholder_approval_date,
                    record_date=event.record_date,
                    ex_date=event.ex_date,
                    payment_date=event.payment_date,
                    amount_per_share=event.amount_per_share,
                    currency=event.currency,
                    status=event.status.value,
                    source=event.source,
                    version=event.version,
                    supersedes_id=event.supersedes_id,
                )
            )
            session.flush()
            result.events_inserted += 1

    if result.events_inserted:
        status = IngestionStatus.PARTIAL if result.rejections else IngestionStatus.SUCCESS
    else:
        status = IngestionStatus.NO_CHANGES
    result.status = status.value
    finish_run(session, run, status=status, summary=result.to_dict())
    return result
