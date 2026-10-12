"""Extraction refresh.

Live fetch still runs the deterministic extractor when the LLM provider is
unavailable. LLM output is never fabricated: the provider is not invoked and
no row is written with extractor_version intelligence_extractor_v1.
Dry-run and live_fetch disabled stay SKIPPED.
"""

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

    from app.modules.intelligence.extraction.persist import run_deterministic_pass

    try:
        summary = run_deterministic_pass(session, ctx)
    except ValueError as exc:
        return {
            "status": "FAILED",
            "reason": "INVALID_AS_OF",
            "changed": False,
            "error": str(exc),
            "extraction_readiness": ready,
            "llm": _llm_report(ready),
        }

    llm_available = bool(ready.get("available"))
    changed = summary["facts_inserted"] > 0 or summary["events_inserted"] > 0
    summary["status"] = "SUCCESS" if changed else "NO_CHANGES"
    summary["reason"] = (
        "DETERMINISTIC_PASS_LLM_UNAVAILABLE"
        if not llm_available
        else "DETERMINISTIC_PASS_LLM_NOT_INVOKED"
    )
    summary["changed"] = changed
    summary["extraction_readiness"] = ready
    summary["llm"] = _llm_report(ready)
    return summary


def _llm_report(ready: dict[str, Any]) -> dict[str, Any]:
    """Readiness is reported. The LLM provider is not called from this path."""
    return {
        "status": ready.get("status"),
        "available": bool(ready.get("available")),
        "provider_invoked": False,
        "events_fabricated": False,
    }
