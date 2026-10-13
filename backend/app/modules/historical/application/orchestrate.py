"""Bounded backfill over a caller-supplied page callback.

Nothing here downloads, calls the network, or writes a database. The caller
hands in fetch_page and, when resuming, the hashes already counted.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.modules.historical.application.checkpoint import (
    STAGE_LIMITS,
    BackfillCheckpoint,
    admit,
    assert_bounded,
)
from app.modules.historical.application.registry import require_registered


@dataclass(frozen=True, slots=True)
class PageRecord:
    """One small row from a page callback. Bytes stay with the caller."""

    content_hash: str
    next_cursor: str


@dataclass(frozen=True, slots=True)
class BoundedRun:
    source_id: str
    stage: str
    cursor: str
    accepted: int
    skipped: int
    content_hashes: tuple[str, ...]


FetchPage = Callable[[str], Sequence[PageRecord]]
SeenHash = Callable[[str], bool]


def run_bounded(
    source_id: str,
    *,
    stage: str,
    requested: int,
    fetch_page: FetchPage,
    seen: SeenHash | None = None,
    cursor: str = "",
) -> BoundedRun:
    """Walk fetch_page until requested new hashes are in, or the page ends.

    source_id must be registered. BLOCKED sources are refused before any
    page is read. requested above the stage limit is refused the same way.
    seen(hash) True means that hash was already counted: the cursor moves,
    and the hash does not count again. A hash repeated inside this run is
    treated the same way.
    """
    registration = require_registered(source_id)
    if registration.pilot_status == "BLOCKED":
        raise ValueError(f"backfill refused for BLOCKED source: {source_id}")
    assert_bounded(requested, stage=stage)
    cap = min(requested, STAGE_LIMITS[stage])

    checkpoint = BackfillCheckpoint(source_id=source_id, cursor=cursor, stage=stage)
    skipped = 0
    while checkpoint.accepted < cap:
        page = tuple(fetch_page(checkpoint.cursor))
        if not page:
            break
        previous = checkpoint.cursor
        for record in page:
            if checkpoint.accepted >= cap:
                break
            digest, nxt = _parts(record)
            if _already_counted(digest, checkpoint, seen):
                skipped += 1
                checkpoint = _advance(checkpoint, nxt)
                continue
            checkpoint = admit(
                checkpoint,
                content_hash=digest,
                next_cursor=nxt,
                accepted=True,
            )
        if checkpoint.cursor == previous:
            break

    return BoundedRun(
        source_id=checkpoint.source_id,
        stage=checkpoint.stage,
        cursor=checkpoint.cursor,
        accepted=checkpoint.accepted,
        skipped=skipped,
        content_hashes=checkpoint.content_hashes,
    )


def _already_counted(
    digest: str,
    checkpoint: BackfillCheckpoint,
    seen: SeenHash | None,
) -> bool:
    if digest in checkpoint.content_hashes:
        return True
    return seen is not None and seen(digest)


def _advance(checkpoint: BackfillCheckpoint, cursor: str) -> BackfillCheckpoint:
    return BackfillCheckpoint(
        source_id=checkpoint.source_id,
        cursor=cursor,
        stage=checkpoint.stage,
        accepted=checkpoint.accepted,
        quarantined=checkpoint.quarantined,
        content_hashes=checkpoint.content_hashes,
    )


def _parts(record: PageRecord) -> tuple[str, str]:
    digest = getattr(record, "content_hash", None)
    nxt = getattr(record, "next_cursor", None)
    if not isinstance(digest, str) or digest == "":
        raise ValueError("page record requires a non-empty content_hash")
    if not isinstance(nxt, str):
        raise ValueError("page record requires next_cursor")
    return digest, nxt
