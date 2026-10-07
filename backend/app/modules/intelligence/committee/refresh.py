"""Committee refresh hook — recomputes advisory combination on demand."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def refresh_committee(session: Session, ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "changed": False,
        "reason": "COMMITTEE_COMPUTED_ON_READ",
        "instrument_ids": list(ctx.get("instrument_ids") or []),
    }
