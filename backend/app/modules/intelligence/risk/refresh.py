"""Risk refresh hook — assessment is computed on snapshot read."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def refresh_risk(session: Session, ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "changed": False,
        "reason": "RISK_COMPUTED_ON_READ",
        "instrument_ids": list(ctx.get("instrument_ids") or []),
    }
