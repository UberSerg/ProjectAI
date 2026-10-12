"""Persist deterministic facts and optional LLM enrichment rows.

The deterministic pass does not call an LLM or the network. LLM enrichment is a
separate insert path: it writes llm_extractor_v1 rows only and never updates
deterministic_extractor_v1 rows or facts that belong to another document id.

Repeated refresh of the same source document id + extractor version + event type
+ claim hash inserts nothing. A later revision is a different source_documents
row and is inserted beside the previous facts; this module never updates or
deletes facts belonging to another document id.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.intelligence.contracts.snapshots_domain import SourceDocumentV1
from app.modules.intelligence.extraction.deterministic import (
    DETERMINISTIC_EXTRACTOR_VERSION,
    MATERIALITY_WEIGHT,
    DeterministicFact,
    build_idempotency_key,
    scan_document_text,
)
from app.modules.intelligence.extraction.schema import (
    FORBIDDEN_PERSISTENCE_KEYS,
    LLM_EXTRACTOR_VERSION,
    ExtractionResultV1,
)
from app.modules.intelligence.news.models import (
    ExtractedFact,
    IntelligenceEvent,
    IntelligenceSourceDocument,
)

logger = logging.getLogger(__name__)

FactKey = tuple[int, str, str, str]
EventKey = tuple[int, str]


def parse_cutoff(raw: Any) -> datetime:
    """Point-in-time cutoff. Date-only values include that UTC calendar day."""
    if raw is None:
        return datetime.now(UTC)
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day, 23, 59, 59, 999999, tzinfo=UTC)
    text = str(raw).strip()
    if not text:
        return datetime.now(UTC)
    if len(text) == 10:
        day = date.fromisoformat(text)
        return datetime(day.year, day.month, day.day, 23, 59, 59, 999999, tzinfo=UTC)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def run_deterministic_pass(session: Session, ctx: dict[str, Any]) -> dict[str, Any]:
    """Select known_at <= as_of and insert accepted facts. No shell, no fetch."""
    cutoff = parse_cutoff(ctx.get("as_of"))
    document_ids = _document_ids(ctx.get("document_ids"))
    documents = _select_documents(session, cutoff, document_ids)
    doc_ids = [row.id for row in documents]
    fact_keys = _existing_fact_keys(session, doc_ids)
    event_keys = _existing_event_keys(session, doc_ids)

    facts_inserted = 0
    facts_duplicate = 0
    events_inserted = 0
    events_duplicate = 0
    events_skipped_no_instrument = 0
    injection_sentences_rejected = 0
    documents_with_injection = 0

    for document in documents:
        scan = scan_document_text(document.raw_text)
        injection_sentences_rejected += scan.injection_sentences_rejected
        if scan.document_has_injection:
            documents_with_injection += 1
        for fact in scan.facts:
            inserted_fact, duplicate_fact = _persist_fact(
                session,
                document,
                fact,
                fact_keys,
                truncated=scan.truncated,
            )
            facts_inserted += inserted_fact
            facts_duplicate += duplicate_fact
            if document.instrument_id is None:
                events_skipped_no_instrument += 1
                continue
            inserted_event, duplicate_event = _persist_event(session, document, fact, event_keys)
            events_inserted += inserted_event
            events_duplicate += duplicate_event

    if facts_inserted or events_inserted:
        session.flush()

    return {
        "extractor_version": DETERMINISTIC_EXTRACTOR_VERSION,
        "as_of": cutoff.isoformat(),
        "documents_selected": len(documents),
        "facts_inserted": facts_inserted,
        "facts_duplicate": facts_duplicate,
        "events_inserted": events_inserted,
        "events_duplicate": events_duplicate,
        "events_skipped_no_instrument": events_skipped_no_instrument,
        "injection_sentences_rejected": injection_sentences_rejected,
        "documents_with_injection": documents_with_injection,
        "urls_fetched": 0,
    }


def _persist_fact(
    session: Session,
    document: IntelligenceSourceDocument,
    fact: DeterministicFact,
    fact_keys: set[FactKey],
    *,
    truncated: bool,
) -> tuple[int, int]:
    key: FactKey = (
        document.id,
        DETERMINISTIC_EXTRACTOR_VERSION,
        fact.event_type,
        fact.claim_hash,
    )
    if key in fact_keys:
        return 0, 1
    idempotency_key = build_idempotency_key(document.id, fact.event_type, fact.claim_hash)
    session.add(
        ExtractedFact(
            source_document_id=document.id,
            extractor_version=DETERMINISTIC_EXTRACTOR_VERSION,
            event_type=fact.event_type,
            materiality=fact.materiality,
            direction=fact.direction,
            affected_horizon=fact.affected_horizon,
            evidence_fragment=fact.evidence_fragment,
            confidence=fact.confidence,
            status="ACCEPTED",
            claim={
                "schema": "DeterministicClaimV1",
                "extractor_version": DETERMINISTIC_EXTRACTOR_VERSION,
                "source_document_id": document.id,
                "rule_id": fact.rule_id,
                "event_type": fact.event_type,
                "claim_hash": fact.claim_hash,
                "idempotency_key": idempotency_key,
                "provenance": {
                    "evidence_fragment": fact.evidence_fragment,
                    "scan_bound_chars": 20000,
                    "char_start": fact.char_start,
                    "char_end": fact.char_end,
                    "truncated": truncated,
                    "numbers_only_from_evidence": True,
                    "llm": False,
                },
                "fields": dict(fact.fields),
            },
        )
    )
    fact_keys.add(key)
    return 1, 0


def _persist_event(
    session: Session,
    document: IntelligenceSourceDocument,
    fact: DeterministicFact,
    event_keys: set[EventKey],
) -> tuple[int, int]:
    idempotency_key = build_idempotency_key(document.id, fact.event_type, fact.claim_hash)
    key: EventKey = (document.id, idempotency_key)
    if key in event_keys:
        return 0, 1
    company = fact.fields.get("company")
    title = fact.event_type if not isinstance(company, str) else f"{fact.event_type}: {company}"
    session.add(
        IntelligenceEvent(
            instrument_id=document.instrument_id,
            event_type=fact.event_type,
            materiality=fact.materiality,
            direction=fact.direction,
            title=title[:180],
            known_at=document.known_at,
            published_at=document.published_at,
            observed_at=document.observed_at,
            source_document_id=document.id,
            payload={
                "schema": "DeterministicEventPayloadV1",
                "extractor_version": DETERMINISTIC_EXTRACTOR_VERSION,
                "idempotency_key": idempotency_key,
                "claim_hash": fact.claim_hash,
                "rule_id": fact.rule_id,
                "materiality_weight": MATERIALITY_WEIGHT[fact.materiality],
                "materiality_meaning": "event_class_importance_not_predicted_return",
                "confidence": fact.confidence,
                "confidence_meaning": "rule_strength_not_profit_probability",
                "direction_basis": "lexical_polarity_table",
                "affected_horizon": fact.affected_horizon,
                "evidence_fragment": fact.evidence_fragment,
                "fields": dict(fact.fields),
                "llm": False,
            },
        )
    )
    event_keys.add(key)
    return 1, 0


def _select_documents(
    session: Session,
    cutoff: datetime,
    document_ids: list[int] | None,
) -> list[IntelligenceSourceDocument]:
    stmt = select(IntelligenceSourceDocument).where(IntelligenceSourceDocument.known_at <= cutoff)
    if document_ids is not None:
        if not document_ids:
            return []
        stmt = stmt.where(IntelligenceSourceDocument.id.in_(document_ids))
    stmt = stmt.order_by(IntelligenceSourceDocument.id)
    return list(session.scalars(stmt).all())


def _document_ids(raw: Any) -> list[int] | None:
    if raw is None:
        return None
    return [int(item) for item in raw]


def _existing_fact_keys(session: Session, document_ids: list[int]) -> set[FactKey]:
    keys: set[FactKey] = set()
    if not document_ids:
        return keys
    rows = session.scalars(
        select(ExtractedFact).where(
            ExtractedFact.source_document_id.in_(document_ids),
            ExtractedFact.extractor_version == DETERMINISTIC_EXTRACTOR_VERSION,
        )
    ).all()
    for row in rows:
        claim_hash = str((row.claim or {}).get("claim_hash") or "")
        keys.add((row.source_document_id, row.extractor_version, row.event_type, claim_hash))
    return keys


def run_llm_enrichment_pass(
    session: Session,
    ctx: dict[str, Any],
    extractor: Any,
) -> dict[str, Any]:
    """Insert llm_extractor_v1 rows for an available extractor. Never updates.

    Rejected, empty, and malformed results write nothing. Evidence that is not an
    exact substring of the stored source text is not inserted.
    """
    if not extractor.available():
        return {
            "status": "LLM_UNAVAILABLE",
            "provider_invoked": False,
            "events_fabricated": False,
            "facts_inserted": 0,
            "events_inserted": 0,
            "extractor_version": LLM_EXTRACTOR_VERSION,
        }
    cutoff = parse_cutoff(ctx.get("as_of"))
    documents = _select_documents(session, cutoff, _document_ids(ctx.get("document_ids")))
    facts_inserted = 0
    events_inserted = 0
    rejected = False
    invoked = 0
    for document in documents:
        source = _source_document(document)
        try:
            result = extractor.extract(source)
        except (OSError, RuntimeError, ValueError, TypeError):
            logger.warning("llm_enrichment_extractor_error")
            invoked += 1
            rejected = True
            continue
        invoked += 1
        if (
            result.status != "OK"
            or result.extractor_version == DETERMINISTIC_EXTRACTOR_VERSION
            or result.extractor_version != LLM_EXTRACTOR_VERSION
        ):
            if result.status == "REJECTED":
                rejected = True
            continue
        inserted = _insert_llm_result(session, document, result)
        facts_inserted += inserted["facts_inserted"]
        events_inserted += inserted["events_inserted"]
    if facts_inserted or events_inserted:
        session.flush()
    if facts_inserted or events_inserted:
        status = "OK"
    elif rejected:
        status = "REJECTED"
    elif invoked:
        status = "EMPTY"
    else:
        status = "LLM_UNAVAILABLE"
    return {
        "status": status,
        "provider_invoked": invoked > 0,
        "events_fabricated": False,
        "facts_inserted": facts_inserted,
        "events_inserted": events_inserted,
        "extractor_version": LLM_EXTRACTOR_VERSION,
    }


def _source_document(row: IntelligenceSourceDocument) -> SourceDocumentV1:
    return SourceDocumentV1(
        id=str(row.id),
        provider=row.provider,
        source_type=row.source_type,
        canonical_url=row.canonical_url,
        title=row.title,
        published_at=row.published_at,
        observed_at=row.observed_at,
        known_at=row.known_at,
        content_hash=row.content_hash,
        language=row.language,
        issuer_id=row.issuer_id,
        instrument_id=row.instrument_id,
        mapping_basis=row.mapping_basis,
        parse_status=row.parse_status,
        raw_text=row.raw_text,
        metadata=dict(row.metadata_ or {}),
    )


def _insert_llm_result(
    session: Session,
    document: IntelligenceSourceDocument,
    result: ExtractionResultV1,
) -> dict[str, int]:
    """INSERT accepted LLM claims. Does not load deterministic rows for update."""
    if result.extractor_version != LLM_EXTRACTOR_VERSION:
        return {"facts_inserted": 0, "events_inserted": 0}
    source_text = document.raw_text or ""
    fact_keys = _existing_llm_fact_keys(session, document.id)
    event_keys = _existing_llm_event_keys(session, document.id)
    facts_inserted = 0
    events_inserted = 0
    for event in result.events:
        if event.direction in {"BUY", "SELL", "HOLD", "LONG", "SHORT"}:
            continue
        for claim in event.claims:
            evidence = claim.evidence_fragment
            if not evidence or evidence not in source_text:
                continue
            if claim.numerical is not None and claim.numerical.evidence_fragment:
                if claim.numerical.evidence_fragment not in source_text:
                    continue
            claim_hash = _llm_claim_hash(event.event_type, evidence, claim.text)
            fact_key: FactKey = (document.id, LLM_EXTRACTOR_VERSION, event.event_type, claim_hash)
            if fact_key in fact_keys:
                continue
            idempotency_key = (
                f"{document.id}|{LLM_EXTRACTOR_VERSION}|{event.event_type}|{claim_hash}"
            )
            claim_payload = {
                "schema": "LlmClaimV1",
                "extractor_version": LLM_EXTRACTOR_VERSION,
                "source_document_id": document.id,
                "event_type": event.event_type,
                "claim_hash": claim_hash,
                "idempotency_key": idempotency_key,
                "text": claim.text,
                "entities": [item for item in event.entities if item in source_text],
                "confidence": claim.confidence,
                "confidence_meaning": "llm_extraction_confidence_not_profit_probability",
                "provenance": {
                    "evidence_fragment": evidence,
                    "exact_substring": True,
                    "llm": True,
                    "numbers_only_from_evidence": True,
                },
                "fields": claim.numerical.to_dict() if claim.numerical is not None else {},
            }
            if FORBIDDEN_PERSISTENCE_KEYS.intersection(claim_payload):
                continue
            session.add(
                ExtractedFact(
                    source_document_id=document.id,
                    extractor_version=LLM_EXTRACTOR_VERSION,
                    event_type=event.event_type,
                    materiality=event.materiality,
                    direction=event.direction,
                    affected_horizon=event.affected_horizon,
                    evidence_fragment=evidence,
                    confidence=claim.confidence,
                    status="ACCEPTED",
                    claim=claim_payload,
                )
            )
            fact_keys.add(fact_key)
            facts_inserted += 1
            if document.instrument_id is None:
                continue
            event_key: EventKey = (document.id, idempotency_key)
            if event_key in event_keys:
                continue
            company = event.entities[0] if event.entities else None
            title = event.event_type if company is None else f"{event.event_type}: {company}"
            session.add(
                IntelligenceEvent(
                    instrument_id=document.instrument_id,
                    event_type=event.event_type,
                    materiality=event.materiality,
                    direction=event.direction,
                    title=title[:180],
                    known_at=document.known_at,
                    published_at=document.published_at,
                    observed_at=document.observed_at,
                    source_document_id=document.id,
                    payload={
                        "schema": "LlmEventPayloadV1",
                        "extractor_version": LLM_EXTRACTOR_VERSION,
                        "idempotency_key": idempotency_key,
                        "claim_hash": claim_hash,
                        "confidence": claim.confidence,
                        "confidence_meaning": "llm_extraction_confidence_not_profit_probability",
                        "materiality_meaning": "event_class_importance_not_predicted_return",
                        "affected_horizon": event.affected_horizon,
                        "evidence_fragment": evidence,
                        "entities": [item for item in event.entities if item in source_text],
                        "llm": True,
                    },
                )
            )
            event_keys.add(event_key)
            events_inserted += 1
    return {"facts_inserted": facts_inserted, "events_inserted": events_inserted}


def _llm_claim_hash(event_type: str, evidence_fragment: str, claim_text: str) -> str:
    blob = f"{event_type}\n{evidence_fragment}\n{claim_text}".encode()
    return hashlib.sha256(blob).hexdigest()


def _existing_llm_fact_keys(session: Session, document_id: int) -> set[FactKey]:
    keys: set[FactKey] = set()
    rows = session.scalars(
        select(ExtractedFact).where(
            ExtractedFact.source_document_id == document_id,
            ExtractedFact.extractor_version == LLM_EXTRACTOR_VERSION,
        )
    ).all()
    for row in rows:
        claim_hash = str((row.claim or {}).get("claim_hash") or "")
        keys.add((row.source_document_id, row.extractor_version, row.event_type, claim_hash))
    return keys


def _existing_llm_event_keys(session: Session, document_id: int) -> set[EventKey]:
    keys: set[EventKey] = set()
    rows = session.scalars(
        select(IntelligenceEvent).where(IntelligenceEvent.source_document_id == document_id)
    ).all()
    for row in rows:
        payload = row.payload or {}
        if payload.get("extractor_version") != LLM_EXTRACTOR_VERSION:
            continue
        idempotency_key = str(payload.get("idempotency_key") or "")
        if row.source_document_id is not None and idempotency_key:
            keys.add((row.source_document_id, idempotency_key))
    return keys


def _existing_event_keys(session: Session, document_ids: list[int]) -> set[EventKey]:
    keys: set[EventKey] = set()
    if not document_ids:
        return keys
    rows = session.scalars(
        select(IntelligenceEvent).where(IntelligenceEvent.source_document_id.in_(document_ids))
    ).all()
    for row in rows:
        idempotency_key = str((row.payload or {}).get("idempotency_key") or "")
        if row.source_document_id is not None and idempotency_key:
            keys.add((row.source_document_id, idempotency_key))
    return keys
