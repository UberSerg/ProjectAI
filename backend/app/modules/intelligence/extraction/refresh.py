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
        # Map issuers that are already known at as_of before facts become events.
        # Clocks stay on the document. AMBIGUOUS and UNMAPPED do not gain an instrument.
        _resolve_unmapped_source_documents(session, ctx)
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


def _resolve_unmapped_source_documents(session: Session, ctx: dict[str, Any]) -> None:
    """Resolve source documents that still have no instrument and are known at as_of.

    ``resolve_source_document`` writes ``instrument_id`` only for MAPPED.
    AMBIGUOUS and UNMAPPED stay unmapped. ``known_at`` is not rewritten.
    """
    from sqlalchemy import select

    from app.modules.intelligence.extraction.persist import parse_cutoff
    from app.modules.intelligence.news.models import IntelligenceSourceDocument
    from app.modules.intelligence.resolution.session import resolve_source_document

    cutoff = parse_cutoff(ctx.get("as_of"))
    raw_ids = ctx.get("document_ids")
    document_ids = None if raw_ids is None else [int(item) for item in raw_ids]
    stmt = select(IntelligenceSourceDocument).where(
        IntelligenceSourceDocument.known_at <= cutoff,
        IntelligenceSourceDocument.instrument_id.is_(None),
    )
    if document_ids is not None:
        if not document_ids:
            return
        stmt = stmt.where(IntelligenceSourceDocument.id.in_(document_ids))
    documents = list(session.scalars(stmt.order_by(IntelligenceSourceDocument.id)).all())
    for document in documents:
        resolve_source_document(session, document)
    if documents:
        session.flush()


def _llm_report(ready: dict[str, Any]) -> dict[str, Any]:
    """Readiness is reported. The LLM provider is not called from this path."""
    return {
        "status": ready.get("status"),
        "available": bool(ready.get("available")),
        "provider_invoked": False,
        "events_fabricated": False,
    }
