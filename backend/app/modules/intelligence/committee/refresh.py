"""Committee refresh hook — recomputes advisory combination on demand."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def refresh_committee(session: Session, ctx: dict[str, Any]) -> dict[str, Any]:
    instrument_ids = list(ctx.get("instrument_ids") or [])
    if ctx.get("dry_run") or not ctx.get("live_fetch"):
        return {
            "status": "SUCCESS",
            "changed": False,
            "reason": "COMMITTEE_COMPUTED_ON_READ",
            "instrument_ids": instrument_ids,
        }
    from app.modules.intelligence.prospective.capture import capture_live_refresh

    captures = capture_live_refresh(session, ctx)
    return {
        "status": "SUCCESS" if captures else "NO_CHANGES",
        "changed": bool(captures),
        "reason": "PROSPECTIVE_CAPTURE_APPENDED",
        "instrument_ids": instrument_ids,
        "captures": captures,
    }
