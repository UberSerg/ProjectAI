"""Classify disclosure payloads. Anti-bot HTML is not a filing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    HistoricalArtifact,
    ParsedObservation,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)

PARSER_VERSION = "disclosure_access_v1"

# Gateway page served by e-disclosure.ru on direct HTTP (no challenge solving).
_ANTIBOT_ID_MARKERS = (
    b'id="request-id"',
    b'id="request-ip"',
    b'id="request-date"',
    b"id='request-id'",
    b"id='request-ip'",
    b"id='request-date'",
)


@dataclass(frozen=True, slots=True)
class AccessVerdict:
    source_id: str
    adapter_status: AdapterStatus
    fetch_status: FetchStatus
    readable: bool
    is_filing: bool
    limitations: tuple[str, ...]


def is_antibot_shell(body: bytes) -> bool:
    """True when the body is the e-disclosure Forbidden gateway, not a document."""
    lowered = body.lower()
    if b"forbidden" not in lowered:
        return False
    return any(marker in lowered for marker in _ANTIBOT_ID_MARKERS)


def sniff_payload(body: bytes) -> str:
    sample = body.lstrip().lstrip(b"\xef\xbb\xbf")
    head = sample[:800].lower()
    if is_antibot_shell(body):
        return "antibot_html"
    if head.startswith(b"{") or head.startswith(b"["):
        return "json"
    if head.startswith((b"<?xml", b"<rss", b"<feed", b"<document")):
        return "xml"
    if b"<html" in head or head.startswith(b"<!doctype"):
        return "html"
    if not sample:
        return "empty"
    return "other"


def classify_disclosure_payload(
    source_id: str,
    body: bytes,
    *,
    http_status: int | None = None,
    content_type: str | None = None,
) -> AccessVerdict:
    """Map a direct HTTP body to an access verdict. Does not read article text."""
    kind = sniff_payload(body)
    if content_type and kind == "other" and "html" in content_type.lower():
        kind = "html"
    if is_antibot_shell(body):
        return AccessVerdict(
            source_id=source_id,
            adapter_status=AdapterStatus.BLOCKED,
            fetch_status=FetchStatus.UNSUPPORTED,
            readable=False,
            is_filing=False,
            limitations=("antibot_shell", "full_text_not_read", "not_a_filing"),
        )
    if kind == "html" or kind == "empty" or kind == "other":
        forbidden = http_status == 403
        if forbidden:
            limitations = ("http_forbidden", "not_a_filing")
            fetch_status = FetchStatus.FORBIDDEN
        else:
            limitations = ("not_a_machine_readable_feed", "not_a_filing")
            fetch_status = FetchStatus.UNSUPPORTED
        return AccessVerdict(
            source_id=source_id,
            adapter_status=AdapterStatus.BLOCKED,
            fetch_status=fetch_status,
            readable=False,
            is_filing=False,
            limitations=limitations,
        )
    return AccessVerdict(
        source_id=source_id,
        adapter_status=AdapterStatus.PARTIAL,
        fetch_status=FetchStatus.OK,
        readable=True,
        is_filing=False,
        limitations=("machine_readable_metadata_only", "not_a_corporate_filing"),
    )


def parse_filings(body: bytes) -> tuple[ParsedObservation, ...]:
    """No corporate filing is produced from portal HTML, including the anti-bot shell."""
    if is_antibot_shell(body):
        return ()
    return ()


def blocked_shell_artifact(
    *,
    source_id: str,
    source_url: str,
    body: bytes,
    first_observed_at: datetime,
) -> HistoricalArtifact:
    """Record the shell as blocked. Publication time stays empty (never backdated)."""
    verdict = classify_disclosure_payload(source_id, body, http_status=403)
    return HistoricalArtifact(
        source_id=source_id,
        source_url=source_url,
        external_document_id="antibot-shell",
        document_type="antibot_shell",
        content_hash=hashlib.sha256(body).hexdigest(),
        parser_version=PARSER_VERSION,
        fetch_status=verdict.fetch_status,
        first_observed_at=first_observed_at,
        published_at=None,
        published_at_precision=PublishedAtPrecision.UNKNOWN,
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
        quality_status=RecordQuality.UNRESOLVED,
        limitations=verdict.limitations,
    )
