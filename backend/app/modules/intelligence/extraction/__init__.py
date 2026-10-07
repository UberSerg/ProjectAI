"""LLM structured information extraction — optional provider, evidence-grounded facts."""

from app.modules.intelligence.extraction.fake import DeterministicFakeExtractor
from app.modules.intelligence.extraction.provider import (
    IntelligenceExtractor,
    UnavailableIntelligenceExtractor,
    resolve_extractor,
)
from app.modules.intelligence.extraction.schema import (
    DIRECTION_VALUES,
    EVENT_TYPES,
    EXTRACTOR_VERSION,
    MATERIALITY_VALUES,
    ExtractedClaimV1,
    ExtractedEventV1,
    ExtractionResultV1,
    NumericalFactV1,
    unavailable_result,
)
from app.modules.intelligence.extraction.service import (
    extract_document,
    extraction_readiness,
    preview_untrusted_prompt,
)

__all__ = [
    "EXTRACTOR_VERSION",
    "DIRECTION_VALUES",
    "EVENT_TYPES",
    "MATERIALITY_VALUES",
    "DeterministicFakeExtractor",
    "ExtractedClaimV1",
    "ExtractedEventV1",
    "ExtractionResultV1",
    "IntelligenceExtractor",
    "NumericalFactV1",
    "UnavailableIntelligenceExtractor",
    "extract_document",
    "extraction_readiness",
    "preview_untrusted_prompt",
    "resolve_extractor",
    "unavailable_result",
]
