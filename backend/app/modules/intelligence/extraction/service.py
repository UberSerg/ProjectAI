"""Extraction orchestration — optional LLM, never silent fake facts into DB."""

from __future__ import annotations

from typing import Any

from app.modules.intelligence.contracts.snapshots_domain import SourceDocumentV1
from app.modules.intelligence.extraction.prompts import build_extraction_messages
from app.modules.intelligence.extraction.provider import (
    IntelligenceExtractor,
    UnavailableIntelligenceExtractor,
    resolve_extractor,
)
from app.modules.intelligence.extraction.schema import ExtractionResultV1


def extract_document(
    document: SourceDocumentV1,
    *,
    provider: IntelligenceExtractor | None = None,
) -> ExtractionResultV1:
    """Run structured extraction. Default runtime provider is LLM_UNAVAILABLE."""
    extractor = resolve_extractor(provider)
    result = extractor.extract(document)
    # Defense in depth: never allow chain-of-thought keys through.
    return ExtractionResultV1(
        status=result.status,
        source_document_id=result.source_document_id,
        extractor_version=result.extractor_version,
        provider_name=result.provider_name,
        events=result.events,
        limitations=result.limitations,
        content_trust="UNTRUSTED",
        summary=result.summary,
        metadata=result.persistable_dict()["metadata"],
    )


def extraction_readiness(
    provider: IntelligenceExtractor | None = None,
) -> dict[str, Any]:
    extractor = resolve_extractor(provider)
    base = extractor.readiness()
    base["default_is_unavailable"] = isinstance(
        resolve_extractor(None), UnavailableIntelligenceExtractor
    )
    base["prompt_frames_untrusted"] = True
    base["persists_chain_of_thought"] = False
    return base


def preview_untrusted_prompt(document: SourceDocumentV1) -> list[dict[str, str]]:
    """Expose framing for tests/audit — does not call any LLM."""
    return build_extraction_messages(document)
