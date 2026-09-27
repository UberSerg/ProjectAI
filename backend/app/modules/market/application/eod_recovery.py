"""Multi-day EOD market recovery after downtime.

One recovery run must download the full missing trading-session range
(last local complete/raw → expected completed session), not one day per launch.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.market.application.eod_gap import (
    MARKET_CURRENT,
    MARKET_STALE,
    detect_market_eod_gap,
    instruments_with_moex_history,
)
from app.modules.market.application.ingest import MarketIngestionService
from app.modules.prediction.application.forward_readiness import select_latest_complete_as_of

MARKET_BACKFILL_NOOP = "NO_OP"
MARKET_BACKFILL_SUCCESS = "SUCCESS"
MARKET_BACKFILL_PARTIAL = "PARTIAL"
MARKET_BACKFILL_FAILED = "FAILED"


def run_eod_market_recovery(
    session: Session,
    *,
    now: datetime | None = None,
    commit_progress: bool = True,
) -> dict[str, Any]:
    """Backfill all missing EOD candles for MOEX-mapped instruments in one run."""
    before = detect_market_eod_gap(session, now=now)
    if before.status == MARKET_CURRENT:
        return {
            "status": MARKET_BACKFILL_NOOP,
            "gap_before": before.to_dict(),
            "gap_after": before.to_dict(),
            "ingest": None,
            "symbols": [],
            "reason": "market_already_current",
        }

    instruments = instruments_with_moex_history(session)
    symbols = [i.symbol for i in instruments]
    expected = before.expected_completed_session or datetime.now(UTC).date()
    # Anchor on COMPLETE EOD, not raw max. A single instrument ahead (partial probe)
    # must not skip multi-day backfill for the rest of the universe.
    date_from = before.local_complete_eod or before.local_raw_max
    if date_from is None:
        # Cold start: let default backfill_from handle range via run_update symbols filter
        ingest = MarketIngestionService(session, commit_progress=commit_progress).run_update()
    else:
        # Inclusive multi-day backfill from day after local complete through expected.
        start = date.fromordinal(date_from.toordinal() + 1)
        if start > expected:
            # Completeness may still lag expected while raw max looks current — force update.
            ingest = MarketIngestionService(
                session, commit_progress=commit_progress
            ).run_backfill(
                symbols=symbols or None,
                date_from=expected,
                date_to=expected,
            )
        else:
            ingest = MarketIngestionService(
                session, commit_progress=commit_progress
            ).run_backfill(
                symbols=symbols or None,
                date_from=start,
                date_to=expected,
            )

    after = detect_market_eod_gap(session, now=now)
    complete = select_latest_complete_as_of(session)
    stats = (ingest or {}).get("stats") or {}
    inserted = int(stats.get("inserted") or 0)
    received = int(stats.get("received") or 0)

    if after.status == MARKET_CURRENT and complete.complete:
        status = MARKET_BACKFILL_SUCCESS
    elif inserted > 0 or received > 0 or after.local_raw_max != before.local_raw_max:
        status = MARKET_BACKFILL_PARTIAL if after.status == MARKET_STALE else MARKET_BACKFILL_SUCCESS
    elif ingest and ingest.get("status") == "ERROR":
        status = MARKET_BACKFILL_FAILED
    else:
        status = MARKET_BACKFILL_PARTIAL if after.status != MARKET_CURRENT else MARKET_BACKFILL_SUCCESS

    return {
        "status": status,
        "gap_before": before.to_dict(),
        "gap_after": after.to_dict(),
        "ingest": {
            "workflow_id": ingest.get("workflow_id") if ingest else None,
            "status": ingest.get("status") if ingest else None,
            "received": received,
            "inserted": inserted,
            "updated": int(stats.get("updated") or 0),
        },
        "symbols": symbols,
        "completeness_after": complete.to_dict(),
        "downloaded_sessions": _downloaded_sessions(before, after),
    }


def _downloaded_sessions(before, after) -> list[str]:
    """Sessions advanced for completeness (prefer complete EOD, fallback raw max)."""
    from app.modules.market.application.eod_gap import trading_sessions_between

    before_anchor = before.local_complete_eod or before.local_raw_max
    after_anchor = after.local_complete_eod or after.local_raw_max
    if after_anchor is None:
        return []
    if before_anchor is None:
        return [after_anchor.isoformat()]
    if after_anchor <= before_anchor:
        return []
    return [d.isoformat() for d in trading_sessions_between(before_anchor, after_anchor)]


__all__ = [
    "MARKET_BACKFILL_FAILED",
    "MARKET_BACKFILL_NOOP",
    "MARKET_BACKFILL_PARTIAL",
    "MARKET_BACKFILL_SUCCESS",
    "run_eod_market_recovery",
]
