"""Chunked reader for the external long-history CSV.

The file carries ~88 columns, of which ~79 are precomputed TA-Lib indicators.
Only OHLCV source facts are read; indicators are ignored on purpose so that no
derived value can ever be mistaken for an observation.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.modules.market_history.domain.types import CSV_USECOLS, RejectReason

DEFAULT_CHUNK_ROWS = 200_000
_SHA256_BLOCK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ParsedRow:
    """One staged bar. ``reject_reason`` set means the row is kept but excluded."""

    source_symbol: str
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: Decimal | None
    value: Decimal | None
    reject_reason: str | None

    @property
    def is_valid(self) -> bool:
        return self.reject_reason is None


@dataclass(frozen=True, slots=True)
class MalformedRow:
    """A physical line that could not yield even a symbol/date identity."""

    line_number: int
    reject_reason: str
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    file_name: str
    file_size: int
    sha256: str


def file_fingerprint(path: Path) -> FileFingerprint:
    """Stable business identity of the file. The absolute path is never a key."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(_SHA256_BLOCK)
            if not block:
                break
            size += len(block)
            digest.update(block)
    return FileFingerprint(file_name=path.name, file_size=size, sha256=digest.hexdigest())


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            return [c.strip() for c in row]
    return []


def missing_required_columns(header: list[str]) -> list[str]:
    present = set(header)
    return [c for c in CSV_USECOLS if c not in present]


def _to_decimal(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    return value


def _to_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    head = text.split(" ", 1)[0].split("T", 1)[0]
    try:
        return date.fromisoformat(head)
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def _classify(
    op: Decimal | None,
    hi: Decimal | None,
    lo: Decimal | None,
    cl: Decimal | None,
    vol: Decimal | None,
) -> str | None:
    prices = (op, hi, lo, cl)
    if any(p is None for p in prices):
        return RejectReason.NON_NUMERIC.value
    assert op is not None and hi is not None and lo is not None and cl is not None
    if any(p <= 0 for p in (op, hi, lo, cl)):
        return RejectReason.NON_POSITIVE_PRICE.value
    if hi < lo or hi < op or hi < cl or lo > op or lo > cl:
        return RejectReason.OHLC_INCONSISTENT.value
    if vol is not None and vol < 0:
        return RejectReason.NEGATIVE_VOLUME.value
    return None


def parse_values(
    symbol_raw: str | None,
    begin_raw: str | None,
    open_raw: str | None,
    high_raw: str | None,
    low_raw: str | None,
    close_raw: str | None,
    volume_raw: str | None,
    value_raw: str | None,
) -> ParsedRow | MalformedRow:
    """Validate one already-projected record."""
    symbol = (symbol_raw or "").strip().upper()
    if not symbol:
        return MalformedRow(0, RejectReason.MISSING_FIELD.value)
    trade_date = _to_date(begin_raw)
    if trade_date is None:
        return MalformedRow(0, RejectReason.INVALID_DATE.value)

    op = _to_decimal(open_raw)
    hi = _to_decimal(high_raw)
    lo = _to_decimal(low_raw)
    cl = _to_decimal(close_raw)
    vol = _to_decimal(volume_raw)
    val = _to_decimal(value_raw)
    return ParsedRow(
        source_symbol=symbol,
        trade_date=trade_date,
        open=op,
        high=hi,
        low=lo,
        close=cl,
        volume=vol,
        value=val,
        reject_reason=_classify(op, hi, lo, cl, vol),
    )


def parse_record(record: dict[str, str]) -> ParsedRow | MalformedRow:
    """Validate one CSV record given as a mapping (test/diagnostic helper)."""
    return parse_values(
        record.get("ticker"),
        record.get("begin"),
        record.get("open"),
        record.get("high"),
        record.get("low"),
        record.get("close"),
        record.get("volume"),
        record.get("value"),
    )


def iter_rows(
    path: Path, *, limit: int | None = None
) -> Iterator[tuple[ParsedRow | MalformedRow, int]]:
    """Stream the file row by row with bounded memory.

    Only the OHLCV columns are projected out of the ~88 physical columns.
    Yields ``(row, line_number)``; ``line_number`` is 1-based over data rows.
    """
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = [c.strip() for c in next(reader)]
        except StopIteration:
            return
        missing = missing_required_columns(header)
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")
        idx = {name: header.index(name) for name in CSV_USECOLS}
        width = len(header)
        i_sym = idx["ticker"]
        i_beg = idx["begin"]
        i_open = idx["open"]
        i_high = idx["high"]
        i_low = idx["low"]
        i_close = idx["close"]
        i_vol = idx["volume"]
        i_val = idx["value"]

        for line_number, cells in enumerate(reader, start=1):
            if len(cells) < width:
                yield MalformedRow(line_number, RejectReason.MISSING_FIELD.value), line_number
            else:
                parsed = parse_values(
                    cells[i_sym],
                    cells[i_beg],
                    cells[i_open],
                    cells[i_high],
                    cells[i_low],
                    cells[i_close],
                    cells[i_vol],
                    cells[i_val],
                )
                if isinstance(parsed, MalformedRow):
                    parsed = MalformedRow(line_number, parsed.reject_reason)
                yield parsed, line_number
            if limit is not None and line_number >= limit:
                return


def iter_chunks(
    path: Path, *, chunk_rows: int = DEFAULT_CHUNK_ROWS, limit: int | None = None
) -> Iterator[tuple[list[ParsedRow], list[MalformedRow]]]:
    """Stream the file in bounded batches suitable for COPY."""
    rows: list[ParsedRow] = []
    malformed: list[MalformedRow] = []
    for parsed, _ in iter_rows(path, limit=limit):
        if isinstance(parsed, MalformedRow):
            malformed.append(parsed)
        else:
            rows.append(parsed)
        if len(rows) + len(malformed) >= chunk_rows:
            yield rows, malformed
            rows, malformed = [], []
    if rows or malformed:
        yield rows, malformed
