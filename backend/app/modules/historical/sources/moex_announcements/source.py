"""MOEX-07 access check for official corporate announcements.

ISS ``sitenews`` and the listing RSS export share one news-id archive. That
archive is already the NEWS-02 headline sample, so this package does not ingest
it and does not treat it as a new source.

The distinct public feed is the CCI IR calendar. Rows carry a short label, a
link, and ``secid`` when present. ``event_date`` is a schedule and ``update_time``
is a warehouse refresh. Neither is ``published_at``. CCI corp-action collections
return the subscriber gate. No bypass is attempted.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from app.modules.historical.application.adapter import CoverageReport
from app.modules.historical.domain.evidence import (
    AdapterStatus,
    FetchStatus,
    HistoricalArtifact,
    ParsedObservation,
    PitQuality,
    PublishedAtPrecision,
    RecordQuality,
)

SOURCE_ID = "MOEX-07"
PARSER_VERSION = "moex_announcements_v1"
SAMPLE_CAP = 20
IR_CALENDAR_URL = "https://iss.moex.com/iss/cci/calendars/ir-calendar.json"
_MSK = timezone(timedelta(hours=3), name="Europe/Moscow")
_TITLE_LABEL_LIMIT = 120
_SITENEWS_LINK = re.compile(r"https?://(?:www\.)?moex\.com/n(\d+)", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_PUBLICATION_KEYS = ("published_at", "publication_timestamp", "announcement_timestamp")


class Transport(Protocol):
    def get(self, url: str, params: Mapping[str, str]) -> FetchResponse: ...


@dataclass(frozen=True, slots=True)
class FetchResponse:
    status_code: int
    content_type: str
    content: bytes


@dataclass(frozen=True, slots=True)
class AnnouncementBatch:
    source_id: str
    artifacts: tuple[HistoricalArtifact, ...]
    adapter_status: AdapterStatus
    fetch_status: FetchStatus
    same_as_sitenews: bool
    overlap_with_sitenews: int
    limitations: tuple[str, ...]


def fixture_bytes(name: str) -> bytes:
    return (Path(__file__).resolve().parent / "fixtures" / name).read_bytes()


def assess_announcements(
    payload: bytes,
    *,
    first_observed_at: datetime,
    http_status: int | None = None,
    content_type: str = "",
    limit: int = SAMPLE_CAP,
) -> AnnouncementBatch:
    """Metadata from one response. Article bodies and sitenews rows are dropped."""
    observed = _aware(first_observed_at)
    if http_status in {401, 403} or _is_antibot(payload):
        limitations = ("antibot_shell",) if _is_antibot(payload) else ("http_forbidden",)
        fetch_status = FetchStatus.UNSUPPORTED if _is_antibot(payload) else FetchStatus.FORBIDDEN
        return _empty(AdapterStatus.BLOCKED, fetch_status, limitations)
    if _is_subscriber_gate(payload):
        return _empty(AdapterStatus.BLOCKED, FetchStatus.FORBIDDEN, ("subscriber_only",))
    if _looks_like_json(payload):
        return _from_json(payload, observed=observed, limit=limit)
    if _looks_like_rss(payload):
        return _from_rss(payload, limit=limit)
    if content_type and "html" in content_type.lower():
        return _empty(AdapterStatus.BLOCKED, FetchStatus.UNSUPPORTED, ("html_not_an_announcement_feed",))
    return _empty(AdapterStatus.FAILED, FetchStatus.UNSUPPORTED, ("not_an_announcement_feed",))


class MoexAnnouncementsSource:
    """Fetches the IR calendar only. Sitenews is not requested."""

    source_id = SOURCE_ID

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport or HttpTransport()
        self._clock = clock or (lambda: datetime.now(UTC))

    def discover(self) -> CoverageReport:
        return self.inspect_coverage()

    def inspect_coverage(self) -> CoverageReport:
        batch = self._load(SAMPLE_CAP)
        return CoverageReport(
            source_id=self.source_id,
            status=batch.adapter_status,
            earliest=None,
            latest=None,
            formats=("json", "html"),
            limitations=batch.limitations,
        )

    def fetch_sample(self, *, limit: int = SAMPLE_CAP) -> tuple[HistoricalArtifact, ...]:
        return self._load(limit).artifacts

    def fetch_range(self, *, start: date, end: date, limit: int) -> tuple[HistoricalArtifact, ...]:
        """Window by ``published_at`` only. Schedule dates do not qualify."""
        budget = _cap(limit)
        selected: list[HistoricalArtifact] = []
        for artifact in self.fetch_sample(limit=SAMPLE_CAP):
            if artifact.published_at is None:
                continue
            published_day = artifact.published_at.date()
            if start <= published_day <= end:
                selected.append(artifact)
            if len(selected) >= budget:
                break
        return tuple(selected)

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        del artifact, raw
        return ()

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
        return observations

    def _load(self, limit: int) -> AnnouncementBatch:
        cap = _cap(limit)
        response = self._transport.get(
            IR_CALENDAR_URL,
            {"limit": str(cap), "iss.meta": "off"},
        )
        return assess_announcements(
            response.content,
            first_observed_at=self._clock(),
            http_status=response.status_code,
            content_type=response.content_type,
            limit=cap,
        )


class HttpTransport:
    def get(self, url: str, params: Mapping[str, str]) -> FetchResponse:
        import httpx

        with httpx.Client(timeout=40.0, follow_redirects=True, trust_env=False) as client:
            response = client.get(url, params=dict(params))
        return FetchResponse(
            status_code=response.status_code,
            content_type=response.headers.get("content-type", ""),
            content=response.content,
        )


def _from_json(payload: bytes, *, observed: datetime, limit: int) -> AnnouncementBatch:
    try:
        data = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _empty(AdapterStatus.FAILED, FetchStatus.FAILED, ("malformed_json",))
    if not isinstance(data, dict):
        return _empty(AdapterStatus.FAILED, FetchStatus.FAILED, ("malformed_json",))
    if "sitenews" in data:
        overlap = _sitenews_row_count(data.get("sitenews"), limit)
        return AnnouncementBatch(
            source_id=SOURCE_ID,
            artifacts=(),
            adapter_status=AdapterStatus.PARTIAL,
            fetch_status=FetchStatus.UNSUPPORTED,
            same_as_sitenews=True,
            overlap_with_sitenews=overlap,
            limitations=("same_as_sitenews", "not_a_new_archive"),
        )
    block = data.get("cci_ir_calendar")
    if not isinstance(block, dict):
        return _empty(AdapterStatus.FAILED, FetchStatus.UNSUPPORTED, ("not_an_announcement_feed",))
    columns = block.get("columns")
    rows = block.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return _empty(AdapterStatus.FAILED, FetchStatus.FAILED, ("malformed_ir_calendar",))
    cap = _cap(limit)
    artifacts: list[HistoricalArtifact] = []
    overlap = 0
    for row in rows:
        if len(artifacts) >= cap:
            break
        if not isinstance(row, list):
            continue
        record = {str(columns[index]): row[index] for index in range(min(len(columns), len(row)))}
        artifact = _calendar_row(record, observed=observed)
        if artifact is None:
            continue
        if _sitenews_id(artifact.source_url) is not None:
            overlap += 1
        artifacts.append(artifact)
    if not artifacts:
        return _empty(AdapterStatus.BLOCKED, FetchStatus.EMPTY, ("empty_calendar",))
    limitations = ["metadata_only", f"capped_at_{SAMPLE_CAP}"]
    if overlap == 0:
        limitations.append("not_sitenews")
    else:
        limitations.append("some_links_overlap_sitenews")
    if any(item.published_at is None for item in artifacts):
        limitations.append("no_published_at")
    return AnnouncementBatch(
        source_id=SOURCE_ID,
        artifacts=tuple(artifacts),
        adapter_status=AdapterStatus.PARTIAL,
        fetch_status=FetchStatus.OK,
        same_as_sitenews=False,
        overlap_with_sitenews=overlap,
        limitations=tuple(limitations),
    )


def _from_rss(payload: bytes, *, limit: int) -> AnnouncementBatch:
    cap = _cap(limit)
    ids: list[str] = []
    for match in _SITENEWS_LINK.finditer(payload.decode("utf-8-sig", errors="replace")):
        news_id = match.group(1)
        if news_id not in ids:
            ids.append(news_id)
        if len(ids) >= cap:
            break
    if ids:
        return AnnouncementBatch(
            source_id=SOURCE_ID,
            artifacts=(),
            adapter_status=AdapterStatus.PARTIAL,
            fetch_status=FetchStatus.UNSUPPORTED,
            same_as_sitenews=True,
            overlap_with_sitenews=len(ids),
            limitations=("same_as_sitenews", "not_a_new_archive"),
        )
    return _empty(AdapterStatus.FAILED, FetchStatus.UNSUPPORTED, ("rss_not_sitenews_and_not_calendar",))


def _calendar_row(record: Mapping[str, Any], *, observed: datetime) -> HistoricalArtifact | None:
    event_id = record.get("event_id")
    if event_id is None or str(event_id).strip() == "":
        return None
    url = _clean(record.get("event_link"))
    if url is None or not url.startswith(("http://", "https://")):
        return None
    title = _title(record)
    if title is None:
        return None
    published = _publication(record)
    secid = _clean(record.get("secid"))
    identity = {"secid": secid} if secid else {}
    limitations = ["metadata_only"]
    if _sitenews_id(url) is None:
        limitations.append("not_sitenews")
    else:
        limitations.append("link_overlaps_sitenews")
    if published is None:
        pit = PitQuality.RESEARCH_ONLY
        precision = PublishedAtPrecision.UNKNOWN
        evidence = None
        limitations.append("no_published_at")
        if "event_date" in record:
            limitations.append("event_date_is_not_publication")
        if "update_time" in record:
            limitations.append("update_time_is_not_published_at")
    else:
        pit = PitQuality.PIT_PROXY
        precision = PublishedAtPrecision.TIMESTAMP
        evidence = "moex_cci_ir_calendar_published_at"
        limitations.append("publisher_clock_is_not_backfilled")
    stamp = published.isoformat() if published is not None else ""
    digest = hashlib.sha256(f"{title}\n{url}\n{secid or ''}\n{event_id}\n{stamp}".encode()).hexdigest()
    return HistoricalArtifact(
        source_id=SOURCE_ID,
        source_url=url,
        external_document_id=str(event_id).strip(),
        document_type="ir_calendar_event",
        content_hash=digest,
        parser_version=PARSER_VERSION,
        fetch_status=FetchStatus.OK,
        first_observed_at=observed,
        title=title,
        entity_identifiers=identity,
        published_at=published,
        published_at_precision=precision,
        historical_availability_evidence=evidence,
        historical_pit_quality=pit,
        quality_status=RecordQuality.UNRESOLVED,
        limitations=tuple(limitations),
    )


def _publication(record: Mapping[str, Any]) -> datetime | None:
    for key in _PUBLICATION_KEYS:
        if key not in record:
            continue
        parsed = _parse_moex_naive(record.get(key))
        if parsed is not None:
            return parsed
    return None


def _title(record: Mapping[str, Any]) -> str | None:
    kind = _clean(record.get("event_type_name")) or _clean(record.get("title"))
    description = record.get("event_description")
    label = None
    if description is not None:
        text = str(description).strip()
        if text and len(text) <= _TITLE_LABEL_LIMIT:
            label = text
    if kind and label:
        return f"{kind}: {label}"
    return kind or label


def _sitenews_row_count(block: Any, limit: int) -> int:
    if not isinstance(block, dict):
        return 0
    columns = block.get("columns")
    rows = block.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list) or "id" not in columns:
        return 0
    id_index = columns.index("id")
    count = 0
    cap = _cap(limit)
    for row in rows:
        if count >= cap:
            break
        if isinstance(row, list) and id_index < len(row) and row[id_index] is not None:
            count += 1
    return count


def _sitenews_id(url: str) -> str | None:
    match = _SITENEWS_LINK.search(url)
    if match is None:
        return None
    return match.group(1)


def _empty(
    adapter_status: AdapterStatus,
    fetch_status: FetchStatus,
    limitations: tuple[str, ...],
) -> AnnouncementBatch:
    return AnnouncementBatch(
        source_id=SOURCE_ID,
        artifacts=(),
        adapter_status=adapter_status,
        fetch_status=fetch_status,
        same_as_sitenews=False,
        overlap_with_sitenews=0,
        limitations=limitations,
    )


def _is_antibot(body: bytes) -> bool:
    lowered = body.lower()
    if b"forbidden" not in lowered:
        return False
    return b"request-id" in lowered or b"request-ip" in lowered


def _is_subscriber_gate(body: bytes) -> bool:
    visible = _TAG.sub(" ", body.decode("utf-8", errors="replace").lower())
    visible = " ".join(visible.split())
    russian = "информация доступна только подписчикам" in visible
    english = "available only to subscribers" in visible
    return russian or english


def _looks_like_json(payload: bytes) -> bool:
    head = payload.lstrip().lstrip(b"\xef\xbb\xbf")[:1]
    return head in {b"{", b"["}


def _looks_like_rss(payload: bytes) -> bool:
    head = payload.lstrip().lstrip(b"\xef\xbb\xbf")[:600].lower()
    if head.startswith(b"<?xml"):
        return b"<rss" in head or b"<feed" in head
    return head.startswith((b"<rss", b"<feed"))


def _parse_moex_naive(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        naive = datetime.fromisoformat(text)
    except ValueError:
        return None
    if naive.tzinfo is None:
        return naive.replace(tzinfo=_MSK).astimezone(UTC)
    return naive.astimezone(UTC)


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _cap(limit: int) -> int:
    return max(0, min(int(limit), SAMPLE_CAP))
