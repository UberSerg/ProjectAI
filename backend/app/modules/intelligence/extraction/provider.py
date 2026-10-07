"""IntelligenceExtractor provider port — LLM is optional at runtime."""

from __future__ import annotations

from typing import Any, Protocol

from app.modules.intelligence.contracts.snapshots_domain import SourceDocumentV1
from app.modules.intelligence.extraction.schema import (
    EXTRACTOR_VERSION,
    ExtractionResultV1,
    unavailable_result,
)


class IntelligenceExtractor(Protocol):
    """Extract structured events/claims from an untrusted source document."""

    name: str
    version: str

    def extract(self, document: SourceDocumentV1) -> ExtractionResultV1:
        """Return structured extraction or LLM_UNAVAILABLE — never fabricate DB facts."""
        ...

    def available(self) -> bool:
        ...

    def readiness(self) -> dict[str, Any]:
        ...


class UnavailableIntelligenceExtractor:
    """Default runtime provider when no LLM credentials/adapter are configured."""

    name = "unavailable"
    version = EXTRACTOR_VERSION

    def __init__(self, *, reason: str = "no_llm_provider_configured") -> None:
        self._reason = reason

    def available(self) -> bool:
        return False

    def readiness(self) -> dict[str, Any]:
        return {
            "status": "LLM_UNAVAILABLE",
            "provider": self.name,
            "extractor_version": self.version,
            "available": False,
            "reason": self._reason,
            "fabricates_facts": False,
        }

    def extract(self, document: SourceDocumentV1) -> ExtractionResultV1:
        return unavailable_result(
            source_document_id=document.id,
            provider_name=self.name,
            reason=self._reason,
        )


def resolve_extractor(
    provider: IntelligenceExtractor | None = None,
) -> IntelligenceExtractor:
    """Return configured provider, or Unavailable — never a silent fake in runtime."""
    if provider is None:
        return UnavailableIntelligenceExtractor()
    return provider
