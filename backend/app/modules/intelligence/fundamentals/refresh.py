"""Fundamentals refresh: snapshots are computed PIT from stored FNS facts."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def refresh_fundamentals(session: Session, ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "changed": False,
        "reason": "FNS_SNAPSHOTS_ON_READ",
        "instrument_ids": list(ctx.get("instrument_ids") or []),
    }
