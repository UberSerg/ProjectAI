"""Incremental refresh and safe parser reprocessing.

A refresh plan opens strictly after the cursor. It does not download, and it
does not move ``first_observed_at`` earlier than that cursor.

Reprocessing the same bytes with a new parser version appends a generation.
The previous ``parser_version`` rows stay in place. The same content hash
with the same parser version is a no-op.

No network, no mass fetch, and no database writes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RefreshCursor:
    """Last observation already stored. The next window starts after it."""

    first_observed_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.first_observed_at, name="cursor.first_observed_at")


@dataclass(frozen=True, slots=True)
class RefreshPlan:
    """Exclusive window ``(after, until]`` and the stamp for newly seen rows.

    ``first_observed_at`` is never earlier than ``after``.
    """

    after: datetime
    until: datetime
    first_observed_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.after, name="after")
        _require_aware(self.until, name="until")
        _require_aware(self.first_observed_at, name="first_observed_at")
        if self.until < self.after:
            raise ValueError("refresh window cannot run backward")
        if self.first_observed_at < self.after:
            raise ValueError("first_observed_at cannot move before the cursor")

    @property
    def empty(self) -> bool:
        return self.until <= self.after

    def covers(self, moment: datetime) -> bool:
        """Return whether ``moment`` is inside the open-closed refresh window."""
        _require_aware(moment, name="moment")
        return self.after < moment <= self.until


def plan_refresh(cursor: RefreshCursor, *, now: datetime) -> RefreshPlan:
    """Plan the next incremental window. Nothing is fetched.

    The window starts strictly after ``cursor.first_observed_at``. When
    ``now`` is not later than the cursor, the plan is empty and
    ``first_observed_at`` stays on the cursor.
    """
    _require_aware(now, name="now")
    after = cursor.first_observed_at
    if now <= after:
        return RefreshPlan(after=after, until=after, first_observed_at=after)
    return RefreshPlan(after=after, until=now, first_observed_at=now)


@dataclass(frozen=True, slots=True)
class VersionedRecord:
    """One stored parse of a raw document.

    Identity is ``(content_hash, parser_version)``. A later parser does not
    replace this row; it adds another generation.
    """

    content_hash: str
    parser_version: str
    first_observed_at: datetime
    generation: int = 1

    def __post_init__(self) -> None:
        if not self.content_hash:
            raise ValueError("content_hash is required")
        if not self.parser_version:
            raise ValueError("parser_version is required")
        if self.generation < 1:
            raise ValueError("generation must be positive")
        _require_aware(self.first_observed_at, name="first_observed_at")


@dataclass(frozen=True, slots=True)
class ReprocessBatch:
    """Previous generations plus any newly tagged parser generation.

    ``retained`` is the input, object for object. ``produced`` holds only
    the new parser version. ``records`` is retained followed by produced,
    so storing the batch cannot drop the old generation.
    """

    retained: tuple[VersionedRecord, ...]
    produced: tuple[VersionedRecord, ...]

    @property
    def records(self) -> tuple[VersionedRecord, ...]:
        return self.retained + self.produced


def reprocess(
    records: Sequence[VersionedRecord],
    *,
    new_parser_version: str,
) -> ReprocessBatch:
    """Append one new generation per content hash. Do not delete the old ones.

    A content hash that already has ``new_parser_version`` is left unchanged.
    The new row keeps the earliest ``first_observed_at`` already stored for
    that hash, so reprocessing cannot move the first sighting backward.
    """
    if not new_parser_version or not new_parser_version.strip():
        raise ValueError("new_parser_version must be non-empty")
    retained = tuple(records)
    present = {(record.content_hash, record.parser_version) for record in retained}
    latest_generation: dict[str, int] = {}
    earliest_seen: dict[str, datetime] = {}
    for record in retained:
        latest_generation[record.content_hash] = max(
            latest_generation.get(record.content_hash, 0),
            record.generation,
        )
        seen = earliest_seen.get(record.content_hash)
        if seen is None or record.first_observed_at < seen:
            earliest_seen[record.content_hash] = record.first_observed_at

    produced: list[VersionedRecord] = []
    emitted: set[str] = set()
    for record in retained:
        content_hash = record.content_hash
        if record.parser_version == new_parser_version:
            continue
        if (content_hash, new_parser_version) in present or content_hash in emitted:
            continue
        emitted.add(content_hash)
        produced.append(
            VersionedRecord(
                content_hash=content_hash,
                parser_version=new_parser_version,
                first_observed_at=earliest_seen[content_hash],
                generation=latest_generation[content_hash] + 1,
            )
        )
    return ReprocessBatch(retained=retained, produced=tuple(produced))


def _require_aware(value: datetime, *, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
