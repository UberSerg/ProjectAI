"""Extraction refresh.

Live fetch still runs the deterministic extractor when the LLM provider is
unavailable. The default configured adapter has no live provider, so runtime
stays LLM_UNAVAILABLE, provider_invoked false, and events_fabricated false.
An explicit available extractor may insert llm_extractor_v1 rows after the
deterministic pass. It never updates deterministic_extractor_v1 rows.
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
    return _enrich_if_configured(session, ctx, summary)


def _enrich_if_configured(
    session: Session, ctx: dict[str, Any], summary: dict[str, Any]
) -> dict[str, Any]:
    """Optional second pass. No-op when the configured adapter is inactive."""
    extractor = ctx.get("llm_extractor")
    if extractor is None:
        from app.modules.intelligence.extraction.provider import configured_extractor_from_settings

        extractor = configured_extractor_from_settings()
    if not extractor.available():
        return summary

    from app.modules.intelligence.extraction.persist import run_llm_enrichment_pass

    enrichment = run_llm_enrichment_pass(session, ctx, extractor)
    summary["llm"] = {
        "status": enrichment["status"],
        "available": True,
        "provider_invoked": bool(enrichment["provider_invoked"]),
        "events_fabricated": False,
    }
    summary["llm_facts_inserted"] = enrichment["facts_inserted"]
    summary["llm_events_inserted"] = enrichment["events_inserted"]
    if enrichment["facts_inserted"] or enrichment["events_inserted"]:
        summary["changed"] = True
        summary["status"] = "SUCCESS"
        summary["reason"] = "DETERMINISTIC_PASS_LLM_ENRICHED"
    elif enrichment["provider_invoked"]:
        summary["reason"] = "DETERMINISTIC_PASS_LLM_REJECTED"
    return summary


def _llm_report(ready: dict[str, Any]) -> dict[str, Any]:
    """Readiness is reported. The LLM provider is not called from this path."""
    return {
        "status": ready.get("status"),
        "available": bool(ready.get("available")),
        "provider_invoked": False,
        "events_fabricated": False,
    }
