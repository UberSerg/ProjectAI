"""Deterministic fake IntelligenceExtractor for tests — never used as silent runtime default."""

from __future__ import annotations

import re
from typing import Any

from app.modules.intelligence.contracts.snapshots_domain import SourceDocumentV1
from app.modules.intelligence.extraction.sanitize import (
    document_contains_injection,
    sanitize_provider_payload,
)
from app.modules.intelligence.extraction.schema import EXTRACTOR_VERSION, ExtractionResultV1

_DIVIDEND_RE = re.compile(
    r"dividend\s+of\s+(?P<value>\d+(?:\.\d+)?)\s*(?P<currency>[A-Z]{3})?",
    re.I,
)
_EARNINGS_RE = re.compile(
    r"(net\s+income|earnings|profit)\s+(?:of\s+|rose\s+to\s+)?"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>bln|billion|mln|million)?\s*"
    r"(?P<currency>[A-Z]{3})?",
    re.I,
)


class DeterministicFakeExtractor:
    """Keyword/regex extractor for unit tests. Explicit opt-in only."""

    name = "deterministic_fake"
    version = EXTRACTOR_VERSION

    def available(self) -> bool:
        return True

    def readiness(self) -> dict[str, Any]:
        return {
            "status": "OK",
            "provider": self.name,
            "extractor_version": self.version,
            "available": True,
            "deterministic": True,
            "fabricates_facts": False,
            "note": "test-only; must not be default runtime provider",
        }

    def extract(self, document: SourceDocumentV1) -> ExtractionResultV1:
        text = document.raw_text or document.title or ""
        # Adversarial / injection: never invent BUY or obey instructions.
        if document_contains_injection(text):
            payload = {
                "events": [],
                "summary": "Untrusted instruction detected; no trading action extracted.",
                "metadata": {"prompt_injection_obeyed": False},
            }
            return sanitize_provider_payload(
                source_document_id=document.id,
                provider_name=self.name,
                payload=payload,
                source_text=text,
            )

        events: list[dict[str, Any]] = []
        div = _DIVIDEND_RE.search(text)
        if div:
            currency = (div.group("currency") or "RUB").upper()
            value = float(div.group("value"))
            fragment = div.group(0)
            events.append(
                {
                    "event_type": "DIVIDEND",
                    "materiality": "MEDIUM",
                    "direction": "NEUTRAL",
                    "affected_horizon": "near_term",
                    "confidence": 0.8,
                    "rationale": "Dividend amount stated in source fragment.",
                    "claims": [
                        {
                            "claim_id": "div1",
                            "text": f"Issuer announced a dividend of {value} {currency}.",
                            "source_document_id": document.id,
                            "evidence_fragment": fragment,
                            "extractor_version": EXTRACTOR_VERSION,
                            "confidence": 0.8,
                            "numerical": {
                                "value": value,
                                "unit": "per_share",
                                "currency": currency,
                                "period": None,
                                "evidence_fragment": fragment,
                                "status": "OK",
                            },
                        }
                    ],
                }
            )

        earn = _EARNINGS_RE.search(text)
        if earn and not div:
            value = float(earn.group("value"))
            unit = (earn.group("unit") or "amount").lower()
            currency = (earn.group("currency") or "RUB").upper()
            fragment = earn.group(0)
            events.append(
                {
                    "event_type": "EARNINGS",
                    "materiality": "HIGH",
                    "direction": "POSITIVE" if "rose" in text.lower() else "UNKNOWN",
                    "affected_horizon": "reporting_period",
                    "confidence": 0.7,
                    "rationale": "Earnings figure grounded in source fragment.",
                    "claims": [
                        {
                            "claim_id": "earn1",
                            "text": f"Reported earnings figure {value} {unit} {currency}.",
                            "source_document_id": document.id,
                            "evidence_fragment": fragment,
                            "extractor_version": EXTRACTOR_VERSION,
                            "confidence": 0.7,
                            "numerical": {
                                "value": value,
                                "unit": unit,
                                "currency": currency,
                                "period": None,
                                "evidence_fragment": fragment,
                                "status": "OK",
                            },
                        }
                    ],
                }
            )

        if not events:
            payload = {
                "events": [],
                "summary": "No supported factual patterns matched.",
                "metadata": {},
            }
        else:
            payload = {
                "events": events,
                "summary": f"Extracted {len(events)} event(s) from untrusted source.",
                "metadata": {"deterministic": True},
            }

        return sanitize_provider_payload(
            source_document_id=document.id,
            provider_name=self.name,
            payload=payload,
            source_text=text,
        )
