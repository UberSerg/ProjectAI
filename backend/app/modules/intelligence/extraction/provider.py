"""IntelligenceExtractor provider port — LLM is optional at runtime."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import replace
from typing import Any, Protocol

from app.core.config import get_settings
from app.domain.ports.llm import LLMMessage, LLMProvider
from app.modules.intelligence.contracts.snapshots_domain import SourceDocumentV1
from app.modules.intelligence.extraction.prompts import build_extraction_messages
from app.modules.intelligence.extraction.sanitize import interpret_llm_output
from app.modules.intelligence.extraction.schema import (
    EXTRACTOR_VERSION,
    LLM_EXTRACTOR_VERSION,
    LLM_TIMEOUT_SECONDS,
    MAX_LLM_INPUT_CHARS,
    MAX_LLM_OUTPUT_CHARS,
    ExtractionResultV1,
    unavailable_result,
)

logger = logging.getLogger(__name__)


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


class ConfiguredLLMExtractor:
    """Adapter over the existing LLMProvider port.

    Inactive unless the caller passes both a non-empty credential sentinel and a
    provider instance. The API key is not stored, logged, or placed in the prompt.
    This class does not fetch URLs and does not construct an HTTP client.
    """

    name = "configured_llm"
    version = LLM_EXTRACTOR_VERSION

    def __init__(
        self,
        llm: LLMProvider | None = None,
        *,
        credential: str = "",
        reason: str | None = None,
        timeout_seconds: float = LLM_TIMEOUT_SECONDS,
        max_input_chars: int = MAX_LLM_INPUT_CHARS,
        max_output_chars: int = MAX_LLM_OUTPUT_CHARS,
    ) -> None:
        self._llm = llm
        self._has_credential = bool(credential.strip())
        self._timeout_seconds = timeout_seconds
        self._max_input_chars = max_input_chars
        self._max_output_chars = max_output_chars
        if not self._has_credential:
            self._reason = reason or "no_llm_provider_configured"
        elif self._llm is None:
            self._reason = reason or "llm_provider_not_live"
        else:
            self._reason = ""

    def available(self) -> bool:
        return self._has_credential and self._llm is not None

    def readiness(self) -> dict[str, Any]:
        if not self.available():
            return {
                "status": "LLM_UNAVAILABLE",
                "provider": self.name,
                "extractor_version": self.version,
                "available": False,
                "reason": self._reason,
                "fabricates_facts": False,
            }
        return {
            "status": "OK",
            "provider": self.name,
            "extractor_version": self.version,
            "available": True,
            "fabricates_facts": False,
            "fetches_urls": False,
            "timeout_seconds": self._timeout_seconds,
            "max_input_chars": self._max_input_chars,
            "max_output_chars": self._max_output_chars,
        }

    def extract(self, document: SourceDocumentV1) -> ExtractionResultV1:
        if not self.available() or self._llm is None:
            return unavailable_result(
                source_document_id=document.id,
                provider_name=self.name,
                reason=self._reason or "no_llm_provider_configured",
            )
        source = document.raw_text or ""
        bounded = source[: self._max_input_chars]
        bounded_document = document if bounded == source else replace(document, raw_text=bounded)
        messages = [
            LLMMessage(role=item["role"], content=item["content"])
            for item in build_extraction_messages(
                bounded_document, extractor_version=self.version
            )
        ]
        try:
            response = _complete_with_timeout(self._llm, messages, self._timeout_seconds)
        except TimeoutError:
            logger.warning("llm_extraction_timeout", extra={"provider": self.name})
            return _call_rejected(document, self.name, "llm_timeout")
        except (OSError, RuntimeError, ValueError, TypeError):
            logger.warning("llm_extraction_provider_error", extra={"provider": self.name})
            return _call_rejected(document, self.name, "llm_provider_error")
        raw = response.content or ""
        if len(raw) > self._max_output_chars:
            return _call_rejected(document, self.name, "output_bound_exceeded")
        return interpret_llm_output(
            document=bounded_document,
            raw_output=raw,
            provider_name=self.name,
            source_text=bounded,
            extractor_version=self.version,
        )


def configured_extractor_from_settings() -> ConfiguredLLMExtractor:
    """Default runtime adapter.

    A POLZA_API_KEY does not enable a call. Polza live completion is not wired,
    the key is not copied onto the adapter, and no HTTP client is constructed.
    """
    has_credential = bool(get_settings().polza_api_key.strip())
    if has_credential:
        return ConfiguredLLMExtractor(llm=None, credential="", reason="llm_provider_not_live")
    return ConfiguredLLMExtractor(llm=None, credential="")


def _complete_with_timeout(
    llm: LLMProvider, messages: list[LLMMessage], timeout_seconds: float
) -> Any:
    if timeout_seconds <= 0:
        raise TimeoutError("llm_timeout")
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm-extract")
    future = executor.submit(llm.complete, messages)
    try:
        return future.result(timeout=timeout_seconds)
    except FuturesTimeoutError as exc:
        future.cancel()
        raise TimeoutError("llm_timeout") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _call_rejected(
    document: SourceDocumentV1, provider_name: str, reason: str
) -> ExtractionResultV1:
    return ExtractionResultV1(
        status="REJECTED",
        source_document_id=document.id,
        extractor_version=LLM_EXTRACTOR_VERSION,
        provider_name=provider_name,
        events=(),
        limitations=(reason, "do_not_fabricate_facts"),
        summary="Provider payload rejected",
        metadata={"fabricated": False},
    )
