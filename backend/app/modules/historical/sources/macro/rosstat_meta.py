"""ROS-04: publication facts that are actually present in a Fedstat payload.

dataGrid JSON from the 2026-10-13 probe had only ``results`` and ``__count``.
The indicator passport HTML has ``Последнее обновление данных`` as a calendar
date. That date is the dataset update, not an observation release timestamp,
so point-in-time quality stays research-only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.modules.historical.domain.evidence import AdapterStatus, PitQuality, PublishedAtPrecision

_PASSPORT_UPDATE = re.compile(
    r"Последнее обновление данных</div>\s*<p>\s*(\d{2}\.\d{2}\.\d{4})(?:\s+(\d{2}:\d{2}(?::\d{2})?))?\s*</p>",
    re.IGNORECASE,
)
_GRID_META_KEYS = (
    "published_at",
    "publishedat",
    "publication_timestamp",
    "publicationtimestamp",
    "publicationdate",
    "publication_date",
    "updated_at",
    "updatedat",
    "updatedate",
    "lastupdate",
    "last_update",
    "modified",
)
_ISO_STAMP = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{2}):(\d{2})(?::(\d{2}))?(?:Z|[+-]\d{2}:\d{2})?)?$"
)


@dataclass(frozen=True, slots=True)
class PublicationFacts:
    """What the fetched payloads said about publication. Missing fields stay empty."""

    data_updated_on: date | None
    published_at: datetime | None
    precision: PublishedAtPrecision
    pit_quality: PitQuality
    timestamp_present: bool
    status: AdapterStatus
    evidence: str | None
    limitations: tuple[str, ...]


def load_json_object(raw: bytes) -> dict[str, object] | None:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def assess_publication(
    *,
    grid_bodies: tuple[bytes, ...],
    passport_body: bytes,
    passport_status: int,
) -> PublicationFacts:
    limitations = [f"passport_http_status={passport_status}", "sdmx_download_not_called"]
    grid_keys: list[str] = []
    grid_hit: _ParsedStamp | None = None
    grid_unparsed = False
    for raw in grid_bodies:
        payload = load_json_object(raw)
        if payload is None:
            limitations.append("datagrid_not_json")
            continue
        keys = tuple(sorted(str(key) for key in payload))
        if keys and not grid_keys:
            grid_keys.extend(keys)
        hit, unparsed = _stamp_from_grid(payload)
        grid_unparsed = grid_unparsed or unparsed
        if hit is not None and (grid_hit is None or hit.has_time):
            grid_hit = hit
    if grid_keys:
        limitations.append("datagrid_keys=" + ",".join(grid_keys))
    if grid_unparsed and grid_hit is None:
        limitations.append("publication_field_present_unparsed")

    passport_hit = _stamp_from_passport(passport_body) if passport_status == 200 else None
    if grid_hit is not None and grid_hit.has_time:
        chosen = grid_hit
        from_grid = True
    elif passport_hit is not None and passport_hit.has_time:
        chosen = passport_hit
        from_grid = False
    elif grid_hit is not None:
        chosen = grid_hit
        from_grid = True
    else:
        chosen = passport_hit
        from_grid = False
    if chosen is None:
        if passport_status in {0, 401, 403}:
            limitations.append("passport_blocked")
        limitations.append("publication_metadata_absent")
        return PublicationFacts(
            data_updated_on=None,
            published_at=None,
            precision=PublishedAtPrecision.UNKNOWN,
            pit_quality=PitQuality.RESEARCH_ONLY,
            timestamp_present=False,
            status=AdapterStatus.BLOCKED,
            evidence=None,
            limitations=tuple(dict.fromkeys(limitations)),
        )

    limitations.append("dataset_last_update_is_not_observation_publication")
    if chosen.has_time:
        limitations.append(
            "datagrid_publication_timestamp" if from_grid else "passport_publication_timestamp"
        )
        evidence = (
            "fedstat.datagrid.publication_field" if from_grid else "fedstat.passport.last_data_update"
        )
        precision = PublishedAtPrecision.TIMESTAMP
    else:
        limitations.append("datagrid_publication_timestamp_absent")
        limitations.append(
            "datagrid_publication_date_only" if from_grid else "passport_last_update_date_only"
        )
        evidence = (
            "fedstat.datagrid.publication_field" if from_grid else "fedstat.passport.last_data_update"
        )
        precision = PublishedAtPrecision.DATE_ONLY
    return PublicationFacts(
        data_updated_on=chosen.day,
        published_at=chosen.published_at,
        precision=precision,
        pit_quality=PitQuality.RESEARCH_ONLY,
        timestamp_present=chosen.has_time,
        status=AdapterStatus.PARTIAL,
        evidence=evidence,
        limitations=tuple(dict.fromkeys(limitations)),
    )


@dataclass(frozen=True, slots=True)
class _ParsedStamp:
    day: date
    published_at: datetime
    has_time: bool


def _stamp_from_grid(payload: dict[str, object]) -> tuple[_ParsedStamp | None, bool]:
    unparsed = False
    found: _ParsedStamp | None = None
    for key, value in payload.items():
        if str(key).lower() not in _GRID_META_KEYS or not isinstance(value, str):
            continue
        parsed = _parse_stamp(value.strip())
        if parsed is None:
            unparsed = True
            continue
        if found is None or parsed.has_time:
            found = parsed
    return found, unparsed


def _stamp_from_passport(body: bytes) -> _ParsedStamp | None:
    text = body.decode("utf-8", errors="replace")
    match = _PASSPORT_UPDATE.search(text)
    if match is None:
        return None
    clock = match.group(2)
    written = match.group(1) if clock is None else f"{match.group(1)} {clock}"
    return _parse_stamp(written)


def _parse_stamp(text: str) -> _ParsedStamp | None:
    if not text:
        return None
    dotted = re.fullmatch(
        r"(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?",
        text,
    )
    if dotted is not None:
        return _from_parts(
            int(dotted.group(3)),
            int(dotted.group(2)),
            int(dotted.group(1)),
            dotted.group(4),
            dotted.group(5),
            dotted.group(6),
        )
    iso = _ISO_STAMP.fullmatch(text)
    if iso is None:
        return None
    return _from_parts(
        int(iso.group(1)),
        int(iso.group(2)),
        int(iso.group(3)),
        iso.group(4),
        iso.group(5),
        iso.group(6),
    )


def _from_parts(
    year: int,
    month: int,
    day: int,
    hour: str | None,
    minute: str | None,
    second: str | None,
) -> _ParsedStamp | None:
    has_time = hour is not None and minute is not None
    try:
        if has_time:
            published = datetime(
                year,
                month,
                day,
                int(hour),
                int(minute),
                int(second or "0"),
                tzinfo=UTC,
            )
        else:
            published = datetime(year, month, day, tzinfo=UTC)
    except ValueError:
        return None
    return _ParsedStamp(day=published.date(), published_at=published, has_time=has_time)
