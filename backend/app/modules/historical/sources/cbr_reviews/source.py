"""CBR-05 discover and access-check for banking-sector reviews.

The single live GET on 2026-10-13 asked the long-standing catalog
``https://www.cbr.ru/analytics/bank_sector/review/`` and received HTTP 404.
No second URL is requested here. SOAP forms 101/102/123/135 are not called.

HTML and PDF are not tables: they become one access artifact and zero
observations. A CSV, JSON, or XML table yields at most 100 row artifacts.
Publication time is taken only from a publication column. ``first_observed_at``
is the fetch clock and is never copied into ``published_at``.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Protocol

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

SOURCE_ID = "CBR-05"
SOURCE_URL = "https://www.cbr.ru/analytics/bank_sector/review/"
PARSER_VERSION = "cbr_reviews_access_v1"
NORMALIZATION_VERSION = PARSER_VERSION
USER_AGENT = "ProjectAI-historical-cbr-reviews/1.0"
MAX_ROWS = 100
MAX_BODY_BYTES = 65_536
# Recorded result of the one live catalog GET. Not a permanent status contract.
PROBED_ON = "2026-10-13"
PROBED_HTTP_STATUS = 404

ACCESS_DOCUMENT = "cbr_review_access"
ROW_DOCUMENT = "cbr_review_row"
_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_PERIOD_COLUMNS = frozenset({"period_end", "period", "reporting_period", "ondate", "on_date", "dt", "date"})
_PUBLISHED_COLUMNS = frozenset(
    {
        "published_at",
        "publication_date",
        "publication_timestamp",
        "pubdate",
        "pub_date",
        "dateupdate",
        "date_update",
    }
)
_VALUE_COLUMNS = frozenset({"value", "metric_value"})
_METRIC_COLUMNS = frozenset({"metric_id", "metric", "indicator"})
_IDENTITY_COLUMNS = frozenset({"id", "code"})
_RECOGNIZED = _PERIOD_COLUMNS | _PUBLISHED_COLUMNS | _VALUE_COLUMNS | _METRIC_COLUMNS | _IDENTITY_COLUMNS
_LIST_KEYS = ("data", "rows", "items", "records", "Data", "Row")


@dataclass(frozen=True, slots=True)
class HttpResult:
    url: str
    status: int
    body: bytes
    content_type: str | None = None
    truncated: bool = False


class Transport(Protocol):
    def request(self, url: str) -> HttpResult: ...


@dataclass(frozen=True, slots=True)
class _Row:
    index: int
    fields: dict[str, str]


@dataclass(frozen=True, slots=True)
class _Verdict:
    adapter_status: AdapterStatus
    fetch_status: FetchStatus
    kind: str
    rows: tuple[_Row, ...]
    limitations: tuple[str, ...]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalize(name: str) -> str:
    return "_".join(name.strip().lower().replace("-", " ").split())


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _cap(limit: int) -> int:
    if limit < 0:
        raise ValueError("limit must be non-negative")
    return min(limit, MAX_ROWS)


def _media_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


def _charset(content_type: str | None) -> str | None:
    if not content_type or "charset=" not in content_type.lower():
        return None
    raw = content_type.lower().split("charset=", 1)[1].split(";", 1)[0].strip().strip('"')
    return raw or None


def _decode_text(body: bytes, content_type: str | None) -> str | None:
    charset = _charset(content_type) or "utf-8"
    if charset in {"utf-8", "utf8"}:
        encoding = "utf-8-sig"
    elif charset in {"windows-1251", "cp1251"}:
        encoding = "cp1251"
    else:
        return None
    try:
        return body.decode(encoding)
    except UnicodeDecodeError:
        return None


def _read_bounded(stream: object, max_bytes: int) -> tuple[bytes, bool]:
    read = getattr(stream, "read", None)
    if read is None:
        return b"", False
    body = read(max_bytes + 1)
    if not isinstance(body, bytes):
        return b"", False
    if len(body) > max_bytes:
        return body[:max_bytes], True
    return body, False


def _sniff(body: bytes, content_type: str | None) -> str:
    media = _media_type(content_type)
    sample = body.lstrip().lstrip(b"\xef\xbb\xbf")
    head = sample[:800].lower()
    if media == "application/pdf" or sample.startswith(b"%PDF"):
        return "pdf"
    if media in {"text/html", "application/xhtml+xml"} or b"<html" in head or head.startswith(b"<!doctype"):
        return "html"
    if media in {"application/json", "text/json"} or head.startswith((b"{", b"[")):
        return "json"
    if media in {"application/xml", "text/xml", "application/rss+xml"} or head.startswith(b"<?xml"):
        return "xml"
    if head.startswith(b"<") and b"<html" not in head:
        return "xml"
    if media in {"text/csv", "application/csv"}:
        return "csv"
    if media == "text/plain" and sample.splitlines():
        header = sample.splitlines()[0]
        if b"," in header or b";" in header:
            return "csv"
    if not sample:
        return "empty"
    return "other"


def _parse_number(text: str) -> float | None:
    cleaned = text.replace("\xa0", "").replace(" ", "")
    if not cleaned or ("," in cleaned and "." in cleaned):
        return None
    if "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    if _NUMBER.fullmatch(cleaned) is None:
        return None
    value = float(cleaned)
    if not math.isfinite(value):
        return None
    return value


def _parse_date(text: str) -> date | None:
    raw = text.strip()
    if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    if len(raw) >= 10 and raw[2:3] == "." and raw[5:6] == ".":
        try:
            return datetime.strptime(raw[:10], "%d.%m.%Y").date()
        except ValueError:
            return None
    return None


def _parse_timestamp(text: str) -> datetime | None:
    raw = text.strip().replace("Z", "+00:00")
    if "T" not in raw and " " not in raw:
        return None
    candidate = raw.replace(" ", "T", 1) if "T" not in raw else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return parsed


def _clock_time(value: datetime) -> bool:
    return any((value.hour, value.minute, value.second, value.microsecond))


def _field(fields: dict[str, str], names: frozenset[str]) -> tuple[str, str] | None:
    for key, value in fields.items():
        if _normalize(key) in names and value.strip():
            return _normalize(key), value.strip()
    return None


def _recognized(fields: dict[str, str]) -> bool:
    return any(_normalize(key) in _RECOGNIZED for key in fields)


def _json_dicts(items: object) -> list[dict[str, str]] | None:
    if not isinstance(items, list) or not items:
        return None
    rows: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            return None
        row: dict[str, str] = {}
        for key, value in item.items():
            if isinstance(value, dict | list | bool) or value is None:
                continue
            row[str(key)] = str(value).strip()
        rows.append(row)
    return rows


def _json_rows(body: bytes, content_type: str | None) -> list[dict[str, str]] | None:
    text = _decode_text(body, content_type)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    found = _json_dicts(payload)
    if found is not None:
        return found
    if isinstance(payload, dict):
        for key in _LIST_KEYS:
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return _json_dicts(candidate)
        if payload and all(not isinstance(value, dict | list | bool) for value in payload.values()):
            return _json_dicts([payload])
    return None


def _csv_rows(body: bytes, content_type: str | None, *, truncated: bool) -> list[dict[str, str]] | None:
    text = _decode_text(body, content_type)
    if text is None or not text.strip():
        return None
    if truncated and not text.endswith(("\n", "\r")):
        lines = text.splitlines()
        if len(lines) < 2:
            return None
        text = "\n".join(lines[:-1]) + "\n"
    header = text.splitlines()[0]
    delimiter = ";" if header.count(";") > header.count(",") else ","
    try:
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    except csv.Error:
        return None
    if not reader.fieldnames:
        return None
    rows: list[dict[str, str]] = []
    try:
        for raw in reader:
            row = {str(key).strip(): (value or "").strip() for key, value in raw.items() if key}
            rows.append(row)
    except csv.Error:
        return None
    return rows


def _leaf_fields(element: ET.Element) -> dict[str, str]:
    fields: dict[str, str] = {}
    for child in list(element):
        if list(child):
            continue
        text = " ".join((child.text or "").split())
        if text:
            fields[_local(child.tag)] = text
    return fields


def _xml_groups(root: ET.Element) -> list[list[ET.Element]]:
    groups: list[list[ET.Element]] = []

    def walk(node: ET.Element, depth: int) -> None:
        if depth > 4:
            return
        buckets: dict[str, list[ET.Element]] = {}
        for child in list(node):
            buckets.setdefault(_local(child.tag), []).append(child)
        for bucket in buckets.values():
            if bucket and all(_recognized(_leaf_fields(item)) for item in bucket):
                groups.append(bucket)
            for child in bucket:
                walk(child, depth + 1)

    walk(root, 0)
    return groups


def _xml_rows(body: bytes) -> list[dict[str, str]] | None:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    if _local(root.tag).lower() == "html":
        return None
    groups = _xml_groups(root)
    if not groups:
        return None
    chosen = max(groups, key=len)
    return [_leaf_fields(item) for item in chosen]


def _table_rows(kind: str, body: bytes, content_type: str | None, *, truncated: bool) -> list[dict[str, str]] | None:
    if kind == "json":
        return _json_rows(body, content_type)
    if kind == "csv":
        return _csv_rows(body, content_type, truncated=truncated)
    if kind == "xml":
        return _xml_rows(body)
    return None


def _select_rows(raw_rows: list[dict[str, str]] | None) -> tuple[tuple[_Row, ...], tuple[str, ...]]:
    if raw_rows is None:
        return (), ("table_not_recognized", "zero_metrics")
    kept = [row for row in raw_rows if _recognized(row)]
    limitations: list[str] = []
    if len(kept) > MAX_ROWS:
        limitations.append("row_cap_100")
        kept = kept[:MAX_ROWS]
    if not kept:
        limitations.append("table_without_recognized_columns")
        limitations.append("zero_metrics")
    return tuple(_Row(index=index, fields=fields) for index, fields in enumerate(kept, start=1)), tuple(limitations)


def _status_kind(
    status: int, body: bytes, content_type: str | None
) -> tuple[str, AdapterStatus, FetchStatus, tuple[str, ...]]:
    if status in {401, 403}:
        return "forbidden", AdapterStatus.BLOCKED, FetchStatus.FORBIDDEN, ("zero_metrics",)
    if status == 404:
        return "not_found", AdapterStatus.BLOCKED, FetchStatus.FAILED, ("catalog_url_not_found", "zero_metrics")
    if status == 429:
        return "rate_limited", AdapterStatus.BLOCKED, FetchStatus.RATE_LIMITED, ("zero_metrics",)
    if status == 0 or status >= 500:
        return "transport_error", AdapterStatus.FAILED, FetchStatus.FAILED, ("zero_metrics",)
    kind = _sniff(body, content_type)
    if kind in {"html", "pdf"}:
        label = "html_without_machine_readable_table" if kind == "html" else "pdf_not_a_table"
        return kind, AdapterStatus.PARTIAL, FetchStatus.UNSUPPORTED, (label, "zero_metrics")
    if kind == "empty":
        return kind, AdapterStatus.PARTIAL, FetchStatus.EMPTY, ("zero_metrics",)
    if kind in {"json", "csv", "xml"}:
        return kind, AdapterStatus.PARTIAL, FetchStatus.OK, ()
    return kind, AdapterStatus.PARTIAL, FetchStatus.UNSUPPORTED, ("unrecognized_publication_format", "zero_metrics")


def classify_publication(
    body: bytes,
    *,
    http_status: int,
    content_type: str | None = None,
    truncated: bool = False,
) -> _Verdict:
    """Map one response to an access verdict. Does not invent metric values."""
    kind, adapter_status, fetch_status, base = _status_kind(http_status, body, content_type)
    limitations = [f"http_status={http_status}", f"content_class={kind}", "not_soap_forms_101_102_123_135"]
    limitations.extend(base)
    rows: tuple[_Row, ...] = ()
    if kind in {"json", "csv", "xml"} and 200 <= http_status < 300:
        parsed, extra = _select_rows(_table_rows(kind, body, content_type, truncated=truncated))
        limitations.extend(extra)
        rows = parsed
        if rows:
            fetch_status = FetchStatus.OK
            limitations.append("metrics_only_from_value_column")
            limitations.append("access_check_sample_not_archive")
            limitations.append(f"row_count={len(rows)}")
        elif "table_without_recognized_columns" in extra:
            fetch_status = FetchStatus.EMPTY
        else:
            fetch_status = FetchStatus.UNSUPPORTED
    if truncated:
        limitations.append(f"body_truncated_at_{MAX_BODY_BYTES}")
    return _Verdict(
        adapter_status=adapter_status,
        fetch_status=fetch_status,
        kind=kind,
        rows=rows,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def _publication(
    fields: dict[str, str],
) -> tuple[PitQuality, datetime | None, PublishedAtPrecision, str | None, tuple[str, ...]]:
    found = _field(fields, _PUBLISHED_COLUMNS)
    if found is None:
        return PitQuality.RESEARCH_ONLY, None, PublishedAtPrecision.UNKNOWN, None, ()
    column, raw = found
    evidence = f"cbr_reviews_{column}"
    stamped = _parse_timestamp(raw)
    if stamped is not None:
        naive = stamped.tzinfo is None
        aware = stamped.replace(tzinfo=UTC) if naive else stamped.astimezone(UTC)
        notes = ("naive_timestamp_assumed_utc",) if naive else ()
        if not _clock_time(aware):
            return PitQuality.PIT_PROXY, aware, PublishedAtPrecision.DATE_ONLY, evidence, notes
        if naive:
            return PitQuality.PIT_PROXY, aware, PublishedAtPrecision.TIMESTAMP, evidence, notes
        return PitQuality.PIT_VERIFIED, aware, PublishedAtPrecision.TIMESTAMP, evidence, notes
    parsed_date = _parse_date(raw)
    if parsed_date is None:
        return PitQuality.RESEARCH_ONLY, None, PublishedAtPrecision.UNKNOWN, None, ("publication_column_unparsed",)
    return (
        PitQuality.PIT_PROXY,
        datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC),
        PublishedAtPrecision.DATE_ONLY,
        evidence,
        (),
    )


def _period(fields: dict[str, str]) -> tuple[date | None, str | None, tuple[str, ...]]:
    found = _field(fields, _PERIOD_COLUMNS)
    if found is None:
        return None, None, ()
    column, raw = found
    parsed = _parse_date(raw) or (_parse_timestamp(raw).date() if _parse_timestamp(raw) else None)
    notes = ("date_column_is_period_not_publication",) if column == "date" else ()
    if parsed is None:
        return None, raw, notes + ("period_not_a_date",)
    return parsed, parsed.isoformat(), notes


def _metric_token(fields: dict[str, str]) -> str | None:
    found = _field(fields, _METRIC_COLUMNS)
    if found is None:
        return None
    token = found[1].strip()
    if _TOKEN.fullmatch(token) is None:
        return None
    return token


def _identity(fields: dict[str, str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for key, value in fields.items():
        column = _normalize(key)
        if column in _IDENTITY_COLUMNS and _TOKEN.fullmatch(value.strip()):
            found[column] = value.strip()
    return found


def _observation(row: _Row, digest: str) -> ParsedObservation | None:
    found = _field(row.fields, _VALUE_COLUMNS)
    if found is None:
        return None
    column, raw = found
    if len(raw) > 40:
        return None
    value = _parse_number(raw)
    if value is None:
        return None
    limitations: list[str] = []
    if value == 0:
        limitations.append("explicit_zero")
    metric_id = _metric_token(row.fields) or column
    period_end, period, _notes = _period(row.fields)
    return ParsedObservation(
        metric_id=metric_id,
        source_id=SOURCE_ID,
        content_hash=digest,
        normalization_version=NORMALIZATION_VERSION,
        quality_status=RecordQuality.ACCEPTED,
        value=value,
        period=period,
        period_end=period_end,
        evidence=f"{column}={raw}",
        limitations=tuple(limitations),
        extra={"raw_value": raw, "value_column": column},
    )


def _row_artifact(
    row: _Row,
    *,
    url: str,
    digest: str,
    observed_at: datetime,
    fetch_status: FetchStatus,
    shared: tuple[str, ...],
    content_type: str | None,
    http_status: int,
) -> HistoricalArtifact:
    period_end, reporting_period, period_notes = _period(row.fields)
    pit, published_at, precision, evidence, pit_notes = _publication(row.fields)
    value_found = _field(row.fields, _VALUE_COLUMNS)
    value = _parse_number(value_found[1]) if value_found is not None and len(value_found[1]) <= 40 else None
    columns = ",".join(sorted({_normalize(key) for key in row.fields}))
    identifiers = {
        "content_class": "table_row",
        "content_type": (content_type or "unspecified")[:120],
        "http_status": str(http_status),
        "row_index": str(row.index),
        "columns": columns,
    }
    identifiers.update(_identity(row.fields))
    token = _metric_token(row.fields)
    if token is not None:
        identifiers["metric_id"] = token
    limitations = shared + period_notes + pit_notes
    metric_label = _field(row.fields, _METRIC_COLUMNS)
    if metric_label is not None and token is None:
        limitations = limitations + ("metric_label_not_used_as_metric_id",)
    if value_found is None or value is None:
        limitations = limitations + ("row_without_plain_value",)
        quality = RecordQuality.UNRESOLVED
    else:
        quality = RecordQuality.ACCEPTED
    return HistoricalArtifact(
        source_id=SOURCE_ID,
        source_url=url,
        external_document_id=f"row:{row.index:03d}",
        document_type=ROW_DOCUMENT,
        content_hash=digest,
        parser_version=PARSER_VERSION,
        fetch_status=fetch_status,
        first_observed_at=observed_at,
        title=f"CBR banking-sector review row {row.index}",
        entity_identifiers=identifiers,
        reporting_period=reporting_period,
        period_end=period_end,
        published_at=published_at,
        published_at_precision=precision,
        historical_availability_evidence=evidence,
        historical_pit_quality=pit,
        quality_status=quality,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def _access_artifact(
    verdict: _Verdict,
    *,
    url: str,
    digest: str,
    observed_at: datetime,
    content_type: str | None,
    http_status: int,
) -> HistoricalArtifact:
    return HistoricalArtifact(
        source_id=SOURCE_ID,
        source_url=url,
        external_document_id=f"access:{http_status}:{verdict.kind}",
        document_type=ACCESS_DOCUMENT,
        content_hash=digest,
        parser_version=PARSER_VERSION,
        fetch_status=verdict.fetch_status,
        first_observed_at=observed_at,
        title="CBR banking-sector review access check",
        entity_identifiers={
            "content_class": verdict.kind,
            "content_type": (content_type or "unspecified")[:120],
            "http_status": str(http_status),
        },
        published_at=None,
        published_at_precision=PublishedAtPrecision.UNKNOWN,
        historical_pit_quality=PitQuality.RESEARCH_ONLY,
        quality_status=RecordQuality.UNRESOLVED,
        limitations=verdict.limitations,
    )


class UrllibTransport:
    """One GET with a hard body cap. No retries and no second URL."""

    def __init__(self, *, timeout_seconds: float = 20.0, max_bytes: int = MAX_BODY_BYTES) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes

    def request(self, url: str) -> HttpResult:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/xml, text/xml, text/csv, application/json, text/html;q=0.5, */*;q=0.1",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                body, truncated = _read_bounded(response, self._max_bytes)
                content_type = response.headers.get("Content-Type")
                return HttpResult(response.geturl(), int(response.status), body, content_type, truncated)
        except urllib.error.HTTPError as exc:
            try:
                body, truncated = _read_bounded(exc, self._max_bytes)
                content_type = exc.headers.get("Content-Type") if exc.headers is not None else None
                return HttpResult(exc.geturl() or url, int(exc.code), body, content_type, truncated)
            finally:
                exc.close()
        except urllib.error.URLError as exc:
            reason = str(exc.reason).encode("utf-8", errors="replace")
            return HttpResult(url, 0, reason, None, False)


class CbrReviewsSource:
    source_id = SOURCE_ID

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        now: datetime | Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport if transport is not None else UrllibTransport()
        self._now = now if now is not None else _utcnow
        self._cached: tuple[HistoricalArtifact, ...] | None = None
        self._verdict: _Verdict | None = None
        self.last_http_status: int | None = None
        self.last_raw: bytes = b""

    def discover(self) -> CoverageReport:
        artifacts = self.fetch_sample(limit=MAX_ROWS)
        return self._coverage(artifacts)

    def inspect_coverage(self) -> CoverageReport:
        return self.discover()

    def fetch_sample(self, *, limit: int = 30) -> tuple[HistoricalArtifact, ...]:
        capped = _cap(limit)
        return self._load()[:capped]

    def fetch_range(self, *, start: date, end: date, limit: int) -> tuple[HistoricalArtifact, ...]:
        capped = _cap(limit)
        artifacts = self._load()
        if not artifacts or artifacts[0].document_type != ROW_DOCUMENT:
            return artifacts[:capped]
        selected = [
            item
            for item in artifacts
            if item.period_end is not None and start <= item.period_end <= end
        ]
        return tuple(selected[:capped])

    def parse(self, artifact: HistoricalArtifact, raw: bytes) -> tuple[ParsedObservation, ...]:
        if artifact.document_type != ROW_DOCUMENT or _sha256(raw) != artifact.content_hash:
            return ()
        content_type = artifact.entity_identifiers.get("content_type")
        status_text = artifact.entity_identifiers.get("http_status", "")
        try:
            status = int(status_text)
        except ValueError:
            status = 0
        verdict = classify_publication(raw, http_status=status, content_type=content_type or None)
        matched = next((row for row in verdict.rows if f"row:{row.index:03d}" == artifact.external_document_id), None)
        if matched is None:
            return ()
        observation = _observation(matched, artifact.content_hash)
        if observation is None:
            return ()
        return (observation,)

    def validate(self, observations: tuple[ParsedObservation, ...]) -> tuple[ParsedObservation, ...]:
        checked: list[ParsedObservation] = []
        for observation in observations:
            errors = observation.quality_errors()
            if observation.quality_status == RecordQuality.ACCEPTED and errors:
                checked.append(
                    replace(
                        observation,
                        quality_status=RecordQuality.QUARANTINE,
                        limitations=observation.limitations + errors,
                    )
                )
            else:
                checked.append(observation)
        return tuple(checked)

    def _clock(self) -> datetime:
        current = self._now() if not isinstance(self._now, datetime) else self._now
        if current.tzinfo is None:
            return current.replace(tzinfo=UTC)
        return current.astimezone(UTC)

    def _load(self) -> tuple[HistoricalArtifact, ...]:
        if self._cached is not None:
            return self._cached
        result = self._transport.request(SOURCE_URL)
        self.last_http_status = result.status
        self.last_raw = result.body
        verdict = classify_publication(
            result.body,
            http_status=result.status,
            content_type=result.content_type,
            truncated=result.truncated,
        )
        self._verdict = verdict
        observed_at = self._clock()
        digest = _sha256(result.body)
        url = result.url or SOURCE_URL
        if verdict.rows:
            artifacts = tuple(
                _row_artifact(
                    row,
                    url=url,
                    digest=digest,
                    observed_at=observed_at,
                    fetch_status=verdict.fetch_status,
                    shared=verdict.limitations,
                    content_type=result.content_type,
                    http_status=result.status,
                )
                for row in verdict.rows
            )
        else:
            artifacts = (
                _access_artifact(
                    verdict,
                    url=url,
                    digest=digest,
                    observed_at=observed_at,
                    content_type=result.content_type,
                    http_status=result.status,
                ),
            )
        self._cached = artifacts
        return artifacts

    def _coverage(self, artifacts: tuple[HistoricalArtifact, ...]) -> CoverageReport:
        verdict = self._verdict
        status = verdict.adapter_status if verdict is not None else AdapterStatus.FAILED
        kind = verdict.kind if verdict is not None else "unknown"
        limitations = verdict.limitations if verdict is not None else ("probe_not_loaded",)
        dated = [item.period_end for item in artifacts if item.period_end is not None]
        return CoverageReport(
            source_id=SOURCE_ID,
            status=status,
            earliest=min(dated) if dated else None,
            latest=max(dated) if dated else None,
            formats=(kind,),
            limitations=limitations,
        )
