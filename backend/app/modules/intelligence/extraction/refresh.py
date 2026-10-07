"""LLM extraction refresh. Live LLM only when ctx['live_fetch'] is true."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def refresh_extract_events(session: Session, ctx: dict[str, Any]) -> dict[str, Any]:
    from app.modules.intelligence.extraction import extraction_readiness

    ready = extraction_readiness()
    if ctx.get("dry_run") or not ctx.get("live_fetch"):
        return {
            "status": "SKIPPED",
            "reason": "LIVE_FETCH_DISABLED",
            "changed": False,
            "extraction_readiness": ready,
        }
    if not ready.get("available"):
        return {
            "status": "SKIPPED",
            "reason": "LLM_UNAVAILABLE",
            "changed": False,
            "extraction_readiness": ready,
        }
    return {
        "status": "SKIPPED",
        "reason": "NO_PENDING_DOCUMENTS_BOUND",
        "changed": False,
        "extraction_readiness": ready,
    }
