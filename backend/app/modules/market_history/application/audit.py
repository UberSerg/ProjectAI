"""Streaming profile of the external CSV: catalog, quality, jump detection.

Single pass, bounded memory: per-symbol aggregates only, never the full frame.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.modules.market_history.domain.types import (
    JUMP_RELATIVE_THRESHOLD,
    MAX_REJECT_RATE_DEGRADED,
    MAX_REJECT_RATE_OK,
    MIN_OBSERVATIONS_OK,
    MIN_OBSERVATIONS_SPARSE,
    SPLIT_LIKE_FACTORS,
    SPLIT_LIKE_TOLERANCE,
    QualityStatus,
    RejectReason,
)
from app.modules.market_history.infrastructure.parser import (
    MalformedRow,
    ParsedRow,
    iter_rows,
)


@dataclass(slots=True)
class SymbolProfile:
    """Per-symbol aggregate accumulated in one streaming pass."""

    source_symbol: str
    observations: int = 0
    valid_observations: int = 0
    rejected_observations: int = 0
    duplicate_dates: int = 0
    out_of_order_rows: int = 0
    first_date: date | None = None
    last_date: date | None = None
    years: set[int] = field(default_factory=set)
    reject_counts: Counter[str] = field(default_factory=Counter)
    min_close: Decimal | None = None
    max_close: Decimal | None = None
    zero_volume_rows: int = 0
    jump_count: int = 0
    split_like_jumps: list[dict[str, Any]] = field(default_factory=list)
    max_abs_jump: float = 0.0
    _prev_date: date | None = None
    _prev_close: Decimal | None = None
    _seen_dates: set[date] = field(default_factory=set)

    @property
    def reject_rate(self) -> float:
        if self.observations == 0:
            return 0.0
        return self.rejected_observations / self.observations

    @property
    def quality_status(self) -> QualityStatus:
        if self.valid_observations == 0:
            return QualityStatus.INVALID
        rate = self.reject_rate
        if rate > MAX_REJECT_RATE_DEGRADED:
            return QualityStatus.INVALID
        if self.valid_observations < MIN_OBSERVATIONS_SPARSE:
            return QualityStatus.SPARSE
        if rate > MAX_REJECT_RATE_OK or self.duplicate_dates > 0:
            return QualityStatus.DEGRADED
        if self.valid_observations < MIN_OBSERVATIONS_OK:
            return QualityStatus.SPARSE
        return QualityStatus.OK

    def observe(self, row: ParsedRow) -> str | None:
        """Fold one parsed row in. Returns an effective reject reason, if any."""
        self.observations += 1
        reason = row.reject_reason

        if row.trade_date in self._seen_dates:
            self.duplicate_dates += 1
            reason = reason or RejectReason.DUPLICATE_DATE.value
        else:
            self._seen_dates.add(row.trade_date)

        if self._prev_date is not None and row.trade_date < self._prev_date:
            self.out_of_order_rows += 1

        if self.first_date is None or row.trade_date < self.first_date:
            self.first_date = row.trade_date
        if self.last_date is None or row.trade_date > self.last_date:
            self.last_date = row.trade_date
        self.years.add(row.trade_date.year)
        self._prev_date = row.trade_date

        if reason is not None:
            self.rejected_observations += 1
            self.reject_counts[reason] += 1
            return reason

        self.valid_observations += 1
        close = row.close
        assert close is not None  # guaranteed by parser validation
        if self.min_close is None or close < self.min_close:
            self.min_close = close
        if self.max_close is None or close > self.max_close:
            self.max_close = close
        if row.volume is not None and row.volume == 0:
            self.zero_volume_rows += 1

        if self._prev_close is not None and self._prev_close > 0:
            self._record_jump(close, row.trade_date)
        self._prev_close = close
        return None

    def _record_jump(self, close: Decimal, trade_date: date) -> None:
        assert self._prev_close is not None
        ratio = float(close / self._prev_close)
        change = ratio - 1.0
        if abs(change) > abs(self.max_abs_jump):
            self.max_abs_jump = change
        if abs(change) < JUMP_RELATIVE_THRESHOLD:
            return
        self.jump_count += 1
        factor = classify_split_like(ratio)
        if factor is not None and len(self.split_like_jumps) < 50:
            self.split_like_jumps.append(
                {
                    "trade_date": trade_date.isoformat(),
                    "ratio": round(ratio, 8),
                    "implied_factor": factor,
                }
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_symbol": self.source_symbol,
            "observations": self.observations,
            "valid_observations": self.valid_observations,
            "rejected_observations": self.rejected_observations,
            "reject_rate": round(self.reject_rate, 6),
            "duplicate_dates": self.duplicate_dates,
            "out_of_order_rows": self.out_of_order_rows,
            "first_date": self.first_date.isoformat() if self.first_date else None,
            "last_date": self.last_date.isoformat() if self.last_date else None,
            "active_years": sorted(self.years),
            "quality_status": self.quality_status.value,
            "min_close": float(self.min_close) if self.min_close is not None else None,
            "max_close": float(self.max_close) if self.max_close is not None else None,
            "zero_volume_rows": self.zero_volume_rows,
            "jump_count": self.jump_count,
            "max_abs_jump": round(self.max_abs_jump, 6),
            "split_like_jumps": self.split_like_jumps,
            "reject_counts": dict(self.reject_counts),
        }


def classify_split_like(ratio: float) -> float | None:
    """Return the implied price divisor when a close jump looks split-shaped.

    ``ratio`` is ``close_t / close_{t-1}``. A 1:10 split divides the raw price by
    10, so ratio ~ 0.1 implies divisor 10; a 5000:1 reverse split gives ratio
    ~ 5000 and divisor 1/5000.
    """
    if ratio <= 0:
        return None
    for factor in SPLIT_LIKE_FACTORS:
        for candidate in (factor, 1.0 / factor):
            if abs(ratio / candidate - 1.0) <= SPLIT_LIKE_TOLERANCE:
                return round(1.0 / candidate, 8)
    return None


@dataclass(slots=True)
class AuditResult:
    total_rows: int = 0
    valid_rows: int = 0
    rejected_rows: int = 0
    malformed_rows: int = 0
    reject_counts: Counter[str] = field(default_factory=Counter)
    profiles: dict[str, SymbolProfile] = field(default_factory=dict)
    min_date: date | None = None
    max_date: date | None = None
    rows_per_year: Counter[int] = field(default_factory=Counter)
    elapsed_sec: float = 0.0
    truncated: bool = False

    @property
    def rows_per_sec(self) -> float:
        if self.elapsed_sec <= 0:
            return 0.0
        return round(self.total_rows / self.elapsed_sec, 1)

    def balances(self) -> bool:
        """Row accounting must reconcile: nothing silently disappears."""
        return self.total_rows == self.valid_rows + self.rejected_rows + self.malformed_rows

    def summary(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "valid_rows": self.valid_rows,
            "rejected_rows": self.rejected_rows,
            "malformed_rows": self.malformed_rows,
            "row_accounting_balanced": self.balances(),
            "reject_counts": dict(self.reject_counts),
            "symbols": len(self.profiles),
            "min_date": self.min_date.isoformat() if self.min_date else None,
            "max_date": self.max_date.isoformat() if self.max_date else None,
            "rows_per_year": {str(y): c for y, c in sorted(self.rows_per_year.items())},
            "elapsed_sec": round(self.elapsed_sec, 3),
            "rows_per_sec": self.rows_per_sec,
            "truncated": self.truncated,
        }


def audit_file(path: Path, *, limit: int | None = None) -> AuditResult:
    """One streaming pass over the CSV. No database access, no ingest."""
    result = AuditResult(truncated=limit is not None)
    started = time.perf_counter()
    for row, _line in iter_rows(path, limit=limit):
        result.total_rows += 1
        if isinstance(row, MalformedRow):
            result.malformed_rows += 1
            result.reject_counts[row.reject_reason] += 1
            continue
        profile = result.profiles.get(row.source_symbol)
        if profile is None:
            profile = SymbolProfile(source_symbol=row.source_symbol)
            result.profiles[row.source_symbol] = profile
        reason = profile.observe(row)
        if reason is None:
            result.valid_rows += 1
        else:
            result.rejected_rows += 1
            result.reject_counts[reason] += 1
        if result.min_date is None or row.trade_date < result.min_date:
            result.min_date = row.trade_date
        if result.max_date is None or row.trade_date > result.max_date:
            result.max_date = row.trade_date
        result.rows_per_year[row.trade_date.year] += 1
    result.elapsed_sec = time.perf_counter() - started
    return result
