"""Pure storage / volume estimators for Intelligence Stack V1 (no DB I/O).

Intraday bars reuse ``market.candles`` with ``timeframe='60m'`` — no separate
candle table and no new database.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# MOEX main session roughly 10:00–18:40 MSK → ~9 hourly closes; round to 10
# to cover open auction / evening session extensions conservatively.
DEFAULT_BARS_PER_SESSION_60M = 10
DEFAULT_TRADING_DAYS_PER_YEAR = 250

# Heap row for market.candles (NUMERIC OHLCV + text + timestamps) ≈ 180–220 B;
# btree index entry on (instrument_id, timeframe, timestamp) ≈ 40–80 B.
# Use mid-band totals including toast/alignment slack.
DEFAULT_BYTES_PER_CANDLE_HEAP = 200
DEFAULT_BYTES_PER_CANDLE_INDEX = 64

# Daily intelligence feature snapshot JSONB row (not raw bars).
DEFAULT_BYTES_PER_INTRADAY_FEATURE_ROW = 1200


@dataclass(frozen=True, slots=True)
class IntradayStorageEstimate:
    schema: str = "IntradayStorageEstimateV1"
    instruments: int = 0
    bars_per_session: int = DEFAULT_BARS_PER_SESSION_60M
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR
    years: float = 1.0
    rows_per_year: int = 0
    rows_total: int = 0
    heap_bytes: int = 0
    index_bytes: int = 0
    total_bytes: int = 0
    heap_gib: float = 0.0
    total_gib: float = 0.0
    feature_snapshot_rows_per_year: int = 0
    feature_snapshot_bytes_per_year: int = 0
    assumptions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_intraday_rows_per_year(
    instruments: int,
    *,
    bars_per_session: int = DEFAULT_BARS_PER_SESSION_60M,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
) -> int:
    """Rows/year in ``market.candles`` for one timeframe (e.g. 60m)."""
    if instruments < 0 or bars_per_session < 0 or trading_days_per_year < 0:
        raise ValueError("counts must be non-negative")
    return int(instruments) * int(bars_per_session) * int(trading_days_per_year)


def estimate_intraday_storage(
    instruments: int,
    *,
    years: float = 1.0,
    bars_per_session: int = DEFAULT_BARS_PER_SESSION_60M,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
    bytes_per_heap_row: int = DEFAULT_BYTES_PER_CANDLE_HEAP,
    bytes_per_index_row: int = DEFAULT_BYTES_PER_CANDLE_INDEX,
    bytes_per_feature_snapshot: int = DEFAULT_BYTES_PER_INTRADAY_FEATURE_ROW,
) -> IntradayStorageEstimate:
    """Estimate 60m candle + daily feature-snapshot footprint (single Postgres)."""
    if years < 0:
        raise ValueError("years must be non-negative")
    rows_year = estimate_intraday_rows_per_year(
        instruments,
        bars_per_session=bars_per_session,
        trading_days_per_year=trading_days_per_year,
    )
    rows_total = int(round(rows_year * float(years)))
    heap = rows_total * int(bytes_per_heap_row)
    index = rows_total * int(bytes_per_index_row)
    total = heap + index
    feature_rows_year = int(instruments) * int(trading_days_per_year)
    feature_bytes_year = feature_rows_year * int(bytes_per_feature_snapshot)
    gib = 1024.0**3
    return IntradayStorageEstimate(
        instruments=int(instruments),
        bars_per_session=int(bars_per_session),
        trading_days_per_year=int(trading_days_per_year),
        years=float(years),
        rows_per_year=rows_year,
        rows_total=rows_total,
        heap_bytes=heap,
        index_bytes=index,
        total_bytes=total,
        heap_gib=round(heap / gib, 4),
        total_gib=round(total / gib, 4),
        feature_snapshot_rows_per_year=feature_rows_year,
        feature_snapshot_bytes_per_year=feature_bytes_year,
        assumptions=(
            "timeframe=60m in market.candles (no separate intraday table)",
            f"bars_per_session={bars_per_session} (MOEX hourly, conservative)",
            f"trading_days_per_year={trading_days_per_year}",
            f"heap≈{bytes_per_heap_row}B/row, index≈{bytes_per_index_row}B/row",
            "feature snapshots: 1 row/(instrument·session day) in intelligence.intraday_feature_snapshots",
            "excludes WAL, bloat, TOAST for large JSONB, replicas",
        ),
    )


def default_scenario_table() -> list[dict[str, Any]]:
    """Canonical scenarios for docs / API-free reporting."""
    scenarios = (
        ("research_equity_v1", 40, 1.0),
        ("research_equity_v1", 40, 5.0),
        ("liquid_expanded", 200, 1.0),
        ("liquid_expanded", 200, 5.0),
        ("cautionary_catalog", 1000, 1.0),
    )
    rows: list[dict[str, Any]] = []
    for label, n, years in scenarios:
        est = estimate_intraday_storage(n, years=years)
        payload = est.to_dict()
        payload["scenario"] = label
        rows.append(payload)
    return rows
