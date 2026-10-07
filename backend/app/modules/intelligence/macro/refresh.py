"""Macro refresh: recompute snapshot from already-ingested CBR/MOEX series."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session


def refresh_macro(session: Session, ctx: dict[str, Any]) -> dict[str, Any]:
    from app.modules.intelligence.macro.service import build_macro_snapshot

    as_of_raw = ctx.get("as_of")
    try:
        as_of = date.fromisoformat(str(as_of_raw)[:10]) if as_of_raw else date.today()
    except ValueError:
        as_of = date.today()
    snap = build_macro_snapshot(session, as_of, persist=False)
    return {
        "status": "SUCCESS",
        "changed": False,
        "macro_status": snap.status,
        "sources": list(snap.sources),
        "regimes": dict(snap.regimes),
    }
