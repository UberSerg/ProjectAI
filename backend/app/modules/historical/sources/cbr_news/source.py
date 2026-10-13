"""CBR-10 press releases and CBR-11 regulatory acts: list metadata only.

The default sample is the saved access-check fixture. This module does not
open a socket, does not follow item links, and does not keep RSS descriptions.
"""

from __future__ import annotations

import email.utils
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

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
from app.modules.historical.sources.cbr_news.catalog import ITEM_CAP, PARSER_VERSION, SPECS, FeedSpec

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "access_check.json"
_ITEM_END = re.compile(rb"</item>", re.IGNORECASE)
_PUBLISHED_TAG = re.compile(rb"<(?:pubdate|published|dc:date)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class NewsAccess:
    source_id: str
    list_url: str
    http_status: int
    task_status: str
    adapter_status: AdapterStatus
    fetch_status: FetchStatus
    published_at_in_payload: bool
    item_count_in_feed: int
    artifacts: tuple[HistoricalArtifact, ...]
    limitations: tuple[str, ...]


def load_fixture(source_id: str, *, observed_at: datetime | None = None) -> NewsAccess:
    """Offline sample from the live access check. Does not read the network."""
    spec = _spec(source_id)
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    block = payload["sources"][source_id]
    clock = _clock(observed_at or datetime.fromisoformat(payload["probed_at"]))
    artifacts = tuple(
        _headline(
            spec=spec,
            title=_clean(item.get("title")),
            url=str(item["url"]),
            published_at=_parse_rfc822(item.get("published_at")),
            observed_at=clock,
            http_status=int(block["http_status"]),
            field_present=bool(item.get("published_at")),
        )
        for item in block["items"][:ITEM_CAP]
    )
    feed_count = int(block["item_count_in_feed"])
    field_present = bool(block["published_at_in_payload"])
    return _finish(
        spec=spec,
        http_status=int(block["http_status"]),
        artifacts=artifacts,
        feed_count=feed_count,
        field_present=field_present,
        fetch_status=FetchStatus.OK if artifacts else FetchStatus.EMPTY,
        adapter_status=_success_adapter(artifacts),
        extra_limitations=("fixture_access_check",),
    )


def access_from_response(
    source_id: str,
    body: bytes,
    *,
    http_status: int,
    content_type: str = "",
    observed_at: datetime,
) -> NewsAccess:
    """Classify one already-downloaded list response. Does not fetch item URLs."""
    spec = _spec(source_id)
    clock = _clock(observed_at)
    if http_status != 200:
        return _blocked(
            spec,
            http_status=http_status,
            observed_at=clock,
            reason=_http_block_reason(http_status),
            fetch_status=_http_fetch_status(http_status),
            adapter_status=_http_adapter_status(http_status),
        )
    payload = _without_bom(body)
    if not _is_rss(payload, content_type):
        return _blocked(
            spec,
            http_status=http_status,
            observed_at=clock,
            reason="not_a_machine_readable_list",
            fetch_status=FetchStatus.UNSUPPORTED,
            adapter_status=AdapterStatus.BLOCKED,
        )
    feed_count = len(_ITEM_END.findall(payload))
    clipped = _clip_items(payload, ITEM_CAP)
    field_present = _PUBLISHED_TAG.search(clipped) is not None
    try:
        root = ET.fromstring(clipped)
    except ET.ParseError:
        return _failed(spec, http_status=http_status, observed_at=clock, reason="malformed_xml")
    artifacts: list[HistoricalArtifact] = []
    for node in _rss_items(root):
        if len(artifacts) >= ITEM_CAP:
            break
        url = _child_text(node, "link")
        if not url:
            continue
        raw_published = _child_text(node, "pubDate") or _child_text(node, "date")
        artifacts.append(
            _headline(
                spec=spec,
                title=_clean(_child_text(node, "title")),
                url=url,
                published_at=_parse_rfc822(raw_published),
                observed_at=clock,
                http_status=http_status,
                field_present=bool(raw_published),
            )
        )
    return _finish(
        spec=spec,
        http_status=http_status,
        artifacts=tuple(artifacts),
        feed_count=feed_count,
        field_present=field_present,
        fetch_status=FetchStatus.OK if artifacts else FetchStatus.EMPTY,
        adapter_status=_success_adapter(tuple(artifacts)),
        extra_limitations=(),
    )


class CbrNewsSource:
    """Fixture-backed list sample. ``discover`` does not fetch."""

    def __init__(
        self,
        source_id: str,
        *,
        observed_at: datetime | None = None,
        access: NewsAccess | None = None,
    ) -> None:
        self.spec = _spec(source_id)
        self.source_id = source_id
        self.access = access if access is not None else load_fixture(source_id, observed_at=observed_at)

    @classmethod
    def from_response(
        cls,
        source_id: str,
        body: bytes,
        *,
        http_status: int,
        content_type: str = "",
        observed_at: datetime,
    ) -> CbrNewsSource:
        access = access_from_response(
            source_id,
            body,
            http_status=http_status,
            content_type=content_type,
            observed_at=observed_at,
        )
        return cls(source_id, observed_at=observed_at, access=access)

    def discover(self) -> CoverageReport:
        return CoverageReport(
            source_id=self.source_id,
            status=AdapterStatus.READY,
            earliest=None,
            latest=None,
            formats=("rss",),
            limitations=(
                f"list_url={self.spec.list_url}",
                f"discovered_from={self.spec.discovered_from}",
                "discover_does_not_fetch",
                "metadata_only",
                "not_a_historical_archive",
            ),
        )

    def inspect_coverage(self) -> CoverageReport:
        dates = [item.published_at.date() for item in self.access.artifacts if item.published_at is not None]
        return CoverageReport(
            source_id=self.source_id,
            status=self.access.adapter_status,
            earliest=min(dates) if dates else None,
            latest=max(dates) if dates else None,
            formats=("rss",) if self.access.fetch_status is FetchStatus.OK else (),
            limitations=self.access.limitations,
        )

    def fetch_sample(self, *, limit: int = ITEM_CAP) -> tuple[HistoricalArtifact, ...]:
        return self.access.artifacts[: _cap(limit)]

    def fetch_range(self, *, start: date, end: date, limit: int) -> tuple[HistoricalArtifact, ...]:
        if end < start:
            raise ValueError("end precedes start")
        kept = [
            item
            for item in self.access.artifacts
            if item.published_at is not None and start <= item.published_at.date() <= end
        ]
        return tuple(kept[: _cap(limit)])

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        del artifact, raw
        return ()

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
        return observations


def _spec(source_id: str) -> FeedSpec:
    try:
        return SPECS[source_id]
    except KeyError as exc:
        raise ValueError(f"unsupported CBR news source: {source_id}") from exc


def _clock(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    return value.astimezone(UTC)


def _cap(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, ITEM_CAP)


def _parse_rfc822(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.replace("\xa0", " ").split())
    return text or None


def _without_bom(body: bytes) -> bytes:
    if body.startswith(b"\xef\xbb\xbf"):
        return body[3:]
    return body.lstrip()


def _is_rss(body: bytes, content_type: str) -> bool:
    if "html" in content_type.lower():
        return False
    head = body.lstrip()[:1200].lower()
    if b"<html" in head or head.startswith(b"<!doctype"):
        return False
    if head.startswith(b"<?xml"):
        return b"<rss" in head or b"<rdf" in head or b"<feed" in head
    return head.startswith((b"<rss", b"<rdf", b"<feed"))


def _clip_items(payload: bytes, limit: int) -> bytes:
    end = -1
    found = 0
    pos = 0
    lowered = payload.lower()
    while found < limit:
        match = _ITEM_END.search(lowered, pos)
        if match is None:
            break
        found += 1
        end = match.end()
        pos = end
    if found == 0 or end < 0:
        return payload
    if found < limit and b"</channel>" in lowered:
        return payload
    chunk = payload[:end]
    if b"</channel>" not in chunk.lower():
        chunk += b"</channel></rss>"
    return chunk


def _rss_items(root: ET.Element) -> list[ET.Element]:
    channel = next((node for node in root.iter() if _local(node.tag).lower() == "channel"), None)
    if channel is None:
        return []
    return [node for node in list(channel) if _local(node.tag).lower() == "item"]


def _child_text(node: ET.Element, name: str) -> str | None:
    for child in list(node):
        if _local(child.tag).lower() != name.lower():
            continue
        if len(child) == 0:
            text = (child.text or "").strip()
            return text or None
        return _clean("".join(child.itertext()))
    return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _headline(
    *,
    spec: FeedSpec,
    title: str | None,
    url: str,
    published_at: datetime | None,
    observed_at: datetime,
    http_status: int,
    field_present: bool,
) -> HistoricalArtifact:
    if published_at is None:
        pit = PitQuality.RESEARCH_ONLY
        precision = PublishedAtPrecision.UNKNOWN
        evidence = None
        item_limits = ["metadata_only", "article_body_not_fetched", "missing_published_at_research_only"]
    else:
        pit = PitQuality.PIT_PROXY
        precision = PublishedAtPrecision.TIMESTAMP
        evidence = "cbr_rss_pubdate"
        item_limits = ["metadata_only", "article_body_not_fetched", "publisher_clock_is_not_backfilled"]
    if field_present and published_at is None:
        item_limits.append("published_at_unparsed")
    if spec.source_id == "CBR-11":
        item_limits.append("act_file_not_downloaded")
    stamp = published_at.isoformat() if published_at is not None else ""
    digest = hashlib.sha256(f"{title or ''}\n{url}\n{stamp}".encode()).hexdigest()
    return HistoricalArtifact(
        source_id=spec.source_id,
        source_url=url,
        external_document_id=url,
        document_type=spec.document_type,
        content_hash=digest,
        parser_version=PARSER_VERSION,
        fetch_status=FetchStatus.OK,
        first_observed_at=observed_at,
        title=title,
        published_at=published_at,
        published_at_precision=precision,
        historical_availability_evidence=evidence,
        historical_pit_quality=pit,
        quality_status=RecordQuality.UNRESOLVED,
        entity_identifiers={"http_status": str(http_status), "list_url": spec.list_url},
        limitations=tuple(item_limits),
    )


def _success_adapter(artifacts: tuple[HistoricalArtifact, ...]) -> AdapterStatus:
    if not artifacts:
        return AdapterStatus.PARTIAL
    if all(item.published_at is None for item in artifacts):
        return AdapterStatus.PARTIAL
    if any(item.published_at is None for item in artifacts):
        return AdapterStatus.PARTIAL
    return AdapterStatus.READY


def _task_status(adapter_status: AdapterStatus, artifacts: tuple[HistoricalArtifact, ...]) -> str:
    if adapter_status is AdapterStatus.BLOCKED:
        return "BLOCKED"
    if adapter_status is AdapterStatus.FAILED:
        return "FAILED"
    if not artifacts or all(item.published_at is None for item in artifacts):
        if artifacts and all(item.published_at is None for item in artifacts):
            return "RESEARCH_ONLY"
        return "PARTIAL"
    if any(item.published_at is None for item in artifacts):
        return "PARTIAL"
    return "READY"


def _finish(
    *,
    spec: FeedSpec,
    http_status: int,
    artifacts: tuple[HistoricalArtifact, ...],
    feed_count: int,
    field_present: bool,
    fetch_status: FetchStatus,
    adapter_status: AdapterStatus,
    extra_limitations: tuple[str, ...],
) -> NewsAccess:
    limitations = [
        "metadata_only",
        "article_body_not_fetched",
        "not_a_historical_archive",
        f"http_status={http_status}",
        f"capped_at_{ITEM_CAP}",
        f"feed_items={feed_count}",
        f"retained={len(artifacts)}",
        *extra_limitations,
    ]
    if spec.source_id == "CBR-11":
        limitations.append("act_file_not_downloaded")
    if artifacts and all(item.published_at is None for item in artifacts):
        limitations.append("dates_missing_research_only")
    return NewsAccess(
        source_id=spec.source_id,
        list_url=spec.list_url,
        http_status=http_status,
        task_status=_task_status(adapter_status, artifacts),
        adapter_status=adapter_status,
        fetch_status=fetch_status,
        published_at_in_payload=field_present,
        item_count_in_feed=feed_count,
        artifacts=artifacts,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def _blocked(
    spec: FeedSpec,
    *,
    http_status: int,
    observed_at: datetime,
    reason: str,
    fetch_status: FetchStatus,
    adapter_status: AdapterStatus,
) -> NewsAccess:
    digest = hashlib.sha256(f"{http_status}\n{spec.list_url}\n{reason}".encode()).hexdigest()
    artifact = HistoricalArtifact(
        source_id=spec.source_id,
        source_url=spec.list_url,
        external_document_id="access-check",
        document_type="access_check",
        content_hash=digest,
        parser_version=PARSER_VERSION,
        fetch_status=fetch_status,
        first_observed_at=observed_at,
        published_at=None,
        published_at_precision=PublishedAtPrecision.UNKNOWN,
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
        quality_status=RecordQuality.UNRESOLVED,
        entity_identifiers={"http_status": str(http_status), "list_url": spec.list_url},
        limitations=("metadata_only", reason, f"http_status={http_status}"),
    )
    limitations = (
        "metadata_only",
        "article_body_not_fetched",
        "not_a_historical_archive",
        reason,
        f"http_status={http_status}",
    )
    return NewsAccess(
        source_id=spec.source_id,
        list_url=spec.list_url,
        http_status=http_status,
        task_status=_task_status(adapter_status, ()),
        adapter_status=adapter_status,
        fetch_status=fetch_status,
        published_at_in_payload=False,
        item_count_in_feed=0,
        artifacts=(artifact,),
        limitations=limitations,
    )


def _failed(spec: FeedSpec, *, http_status: int, observed_at: datetime, reason: str) -> NewsAccess:
    return _blocked(
        spec,
        http_status=http_status,
        observed_at=observed_at,
        reason=reason,
        fetch_status=FetchStatus.FAILED,
        adapter_status=AdapterStatus.FAILED,
    )


def _http_block_reason(http_status: int) -> str:
    if http_status in {401, 403}:
        return "http_forbidden"
    if http_status == 429:
        return "http_rate_limited"
    if http_status >= 500 or http_status == 0:
        return "http_failed"
    return "not_a_machine_readable_list"


def _http_fetch_status(http_status: int) -> FetchStatus:
    if http_status in {401, 403}:
        return FetchStatus.FORBIDDEN
    if http_status == 429:
        return FetchStatus.RATE_LIMITED
    if http_status >= 500 or http_status == 0:
        return FetchStatus.FAILED
    return FetchStatus.UNSUPPORTED


def _http_adapter_status(http_status: int) -> AdapterStatus:
    if http_status >= 500 or http_status == 0:
        return AdapterStatus.FAILED
    return AdapterStatus.BLOCKED
