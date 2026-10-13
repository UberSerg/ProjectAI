"""Bounded, resumable backfill cursor.

A checkpoint remembers how far a source got. It does not download data.
The same content hash is not counted twice.
"""

from __future__ import annotations

from dataclasses import dataclass

STAGE_LIMITS: dict[str, int] = {
    "pilot": 100,
    "stage_1000": 1_000,
    "stage_10000": 10_000,
}


@dataclass(frozen=True, slots=True)
class BackfillCheckpoint:
    source_id: str
    cursor: str
    stage: str
    accepted: int = 0
    quarantined: int = 0
    content_hashes: tuple[str, ...] = ()

    def resume_cursor(self) -> str:
        return self.cursor


def assert_bounded(requested: int, *, stage: str) -> None:
    if stage not in STAGE_LIMITS:
        raise ValueError(f"unknown backfill stage: {stage}")
    if requested <= 0:
        raise ValueError("backfill limit must be positive")
    limit = STAGE_LIMITS[stage]
    if requested > limit:
        raise ValueError(f"requested {requested} exceeds {stage} limit {limit}")


def admit(
    checkpoint: BackfillCheckpoint,
    *,
    content_hash: str,
    next_cursor: str,
    accepted: bool,
) -> BackfillCheckpoint:
    """Advance the cursor. A repeated hash does not change the counts."""
    if content_hash in checkpoint.content_hashes:
        return BackfillCheckpoint(
            source_id=checkpoint.source_id,
            cursor=next_cursor,
            stage=checkpoint.stage,
            accepted=checkpoint.accepted,
            quarantined=checkpoint.quarantined,
            content_hashes=checkpoint.content_hashes,
        )
    hashes = checkpoint.content_hashes + (content_hash,)
    return BackfillCheckpoint(
        source_id=checkpoint.source_id,
        cursor=next_cursor,
        stage=checkpoint.stage,
        accepted=checkpoint.accepted + (1 if accepted else 0),
        quarantined=checkpoint.quarantined + (0 if accepted else 1),
        content_hashes=hashes,
    )
