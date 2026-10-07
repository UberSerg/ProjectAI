"""News ingest refresh hook. Live fetch only when ctx['live_fetch'] is true."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def refresh_news(session: Session, ctx: dict[str, Any]) -> dict[str, Any]:
    if ctx.get("dry_run") or not ctx.get("live_fetch"):
        return {"status": "SKIPPED", "reason": "LIVE_FETCH_DISABLED", "changed": False}
    from app.modules.intelligence.news.ingest import ingest_allowlisted_sources

    results = ingest_allowlisted_sources(session)
    inserted = sum(r.inserted + r.revised for r in results)
    errors = [r.error for r in results if r.error]
    return {
        "status": "WARNING" if errors else "SUCCESS",
        "changed": inserted > 0,
        "inserted": inserted,
        "errors": errors[:8],
        "sources": [r.source_id for r in results],
    }
