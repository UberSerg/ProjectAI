"""Instrument source validity windows. instrument_id is stable; SECID/board are temporal."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import InstrumentSource

SOURCE_MOEX = "MOEX"


class MappingOverlapError(ValueError):
    """Two mappings of the same instrument/source occupy the same role or dated window."""


class InvalidMappingWindowError(ValueError):
    """Window fields are internally inconsistent."""


def is_current_mapping(mapping: InstrumentSource) -> bool:
    """Open-ended current mapping: valid_to IS NULL (start may be unknown)."""
    return mapping.valid_to is None


def mapping_covers_as_of(mapping: InstrumentSource, as_of: date) -> bool:
    """Proven historical window: valid_from <= t < valid_to (valid_to NULL = open-ended).

    valid_from NULL is start-unknown / current-only. It does NOT cover an arbitrary past t.
    """
    if mapping.valid_from is None:
        return False
    if mapping.valid_from > as_of:
        return False
    if mapping.valid_to is not None and as_of >= mapping.valid_to:
        return False
    return True


def validate_mapping_window(mapping: InstrumentSource) -> None:
    if mapping.valid_from is None and mapping.valid_to is not None:
        raise InvalidMappingWindowError("valid_from is required when valid_to is set")
    if (
        mapping.valid_from is not None
        and mapping.valid_to is not None
        and mapping.valid_from >= mapping.valid_to
    ):
        raise InvalidMappingWindowError("valid_from must be < valid_to (half-open window)")


def windows_overlap(left: InstrumentSource, right: InstrumentSource) -> bool:
    """Same instrument/source role conflict.

    Two open-ended mappings (valid_to NULL) conflict.
    Dated half-open windows [from, to) conflict when they intersect.
    A current unknown-start mapping does not occupy a closed historical window.
    """
    if is_current_mapping(left) and is_current_mapping(right):
        return True
    if left.valid_from is None or right.valid_from is None:
        return False
    left_end = left.valid_to if left.valid_to is not None else date.max
    right_end = right.valid_to if right.valid_to is not None else date.max
    return left.valid_from < right_end and right.valid_from < left_end


def mappings_for_instrument(
    session: Session, instrument_id: int, source: str = SOURCE_MOEX
) -> list[InstrumentSource]:
    return list(
        session.scalars(
            select(InstrumentSource).where(
                InstrumentSource.instrument_id == instrument_id,
                InstrumentSource.source == source,
            )
        )
    )


def assert_no_overlap(session: Session, candidate: InstrumentSource) -> None:
    validate_mapping_window(candidate)
    for other in mappings_for_instrument(session, candidate.instrument_id, candidate.source):
        if candidate.id is not None and other.id == candidate.id:
            continue
        if windows_overlap(candidate, other):
            raise MappingOverlapError(
                f"overlapping {candidate.source} mappings for instrument {candidate.instrument_id}"
            )


def resolve_current_source(
    session: Session, instrument_id: int, source: str = SOURCE_MOEX
) -> InstrumentSource | None:
    """Live/current ingest: the single open-ended mapping (valid_to IS NULL)."""
    current = [
        row for row in mappings_for_instrument(session, instrument_id, source) if is_current_mapping(row)
    ]
    if not current:
        return None
    preferred = next((row for row in current if (row.board or "").upper() == "TQBR"), None)
    return preferred or current[0]


def resolve_source_as_of(
    session: Session,
    instrument_id: int,
    as_of: date,
    source: str = SOURCE_MOEX,
) -> InstrumentSource | None:
    """Historical as-of. Never falls back to a current mapping with unknown valid_from."""
    covered = [
        row
        for row in mappings_for_instrument(session, instrument_id, source)
        if mapping_covers_as_of(row, as_of)
    ]
    if not covered:
        return None
    preferred = next((row for row in covered if (row.board or "").upper() == "TQBR"), None)
    return preferred or covered[0]


def add_source_mapping(
    session: Session,
    *,
    instrument_id: int,
    source: str,
    external_id: str,
    board: str | None,
    valid_from: date | None,
    valid_to: date | None,
    source_metadata: dict | None = None,
) -> InstrumentSource:
    row = InstrumentSource(
        instrument_id=instrument_id,
        source=source,
        external_id=external_id,
        board=board or "",
        valid_from=valid_from,
        valid_to=valid_to,
        source_metadata=source_metadata or {},
    )
    assert_no_overlap(session, row)
    session.add(row)
    session.flush()
    return row
