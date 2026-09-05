"""Feature-stack feasibility of the staged history, by year band.

Row count is not experience: a year is only usable when enough symbols carry a
full rolling warm-up window, so the PIT feature stack can be computed without
look-ahead. This module reports feasibility; it does not build datasets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.market_history.domain.types import (
    FEATURE_WARMUP_OBSERVATIONS,
    ML_PARTIAL_MIN_SYMBOLS,
    ML_READY_MIN_SYMBOLS,
    Eligibility,
    FeatureStackStatus,
)

_YEAR_STATS_SQL = text(
    """
    WITH per_symbol_year AS (
        SELECT
            EXTRACT(YEAR FROM e.trade_date)::INTEGER AS year,
            e.source_symbol,
            count(*) FILTER (WHERE e.reject_reason IS NULL) AS valid_rows,
            count(*) AS rows,
            count(*) FILTER (WHERE ce.eligibility = :eligible) AS eligible_rows
        FROM market.external_candles_daily e
        LEFT JOIN market.external_curated_eligibility ce
          ON ce.source_id = e.source_id
         AND ce.source_symbol = e.source_symbol
         AND ce.trade_date = e.trade_date
        WHERE e.source_id = :source_id
        GROUP BY 1, 2
    )
    SELECT
        year,
        count(*) AS symbols,
        count(*) FILTER (WHERE eligible_rows >= :warmup) AS eligible_symbols,
        sum(rows) AS rows,
        sum(eligible_rows) AS eligible_rows,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY valid_rows) AS median_observations,
        count(*) FILTER (WHERE valid_rows >= :warmup) AS symbols_with_warmup
    FROM per_symbol_year
    GROUP BY year
    ORDER BY year;
    """
)

_UPSERT_SQL = text(
    """
    INSERT INTO market.external_ml_readiness (
        source_id, year, symbols, eligible_symbols, rows, eligible_rows,
        median_observations, feature_stack_status, blocking_reasons, metrics
    ) VALUES (
        :source_id, :year, :symbols, :eligible_symbols, :rows, :eligible_rows,
        :median_observations, :feature_stack_status,
        CAST(:blocking_reasons AS jsonb), CAST(:metrics AS jsonb)
    )
    ON CONFLICT (source_id, year) DO UPDATE SET
        symbols = EXCLUDED.symbols,
        eligible_symbols = EXCLUDED.eligible_symbols,
        rows = EXCLUDED.rows,
        eligible_rows = EXCLUDED.eligible_rows,
        median_observations = EXCLUDED.median_observations,
        feature_stack_status = EXCLUDED.feature_stack_status,
        blocking_reasons = EXCLUDED.blocking_reasons,
        metrics = EXCLUDED.metrics;
    """
)


@dataclass(frozen=True, slots=True)
class YearReadiness:
    year: int
    symbols: int
    eligible_symbols: int
    rows: int
    eligible_rows: int
    median_observations: float | None
    symbols_with_warmup: int
    feature_stack_status: FeatureStackStatus
    blocking_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "symbols": self.symbols,
            "eligible_symbols": self.eligible_symbols,
            "rows": self.rows,
            "eligible_rows": self.eligible_rows,
            "median_observations": self.median_observations,
            "symbols_with_warmup": self.symbols_with_warmup,
            "feature_stack_status": self.feature_stack_status.value,
            "blocking_reasons": self.blocking_reasons,
        }


def classify_year(
    *, eligible_symbols: int, symbols_with_warmup: int, median_observations: float | None
) -> tuple[FeatureStackStatus, list[str]]:
    reasons: list[str] = []
    if median_observations is not None and median_observations < FEATURE_WARMUP_OBSERVATIONS:
        reasons.append(
            f"median_observations_below_warmup_{FEATURE_WARMUP_OBSERVATIONS}"
        )
    if symbols_with_warmup < ML_READY_MIN_SYMBOLS:
        reasons.append(f"symbols_with_warmup_below_{ML_READY_MIN_SYMBOLS}")

    if eligible_symbols >= ML_READY_MIN_SYMBOLS:
        return FeatureStackStatus.READY, reasons
    if eligible_symbols >= ML_PARTIAL_MIN_SYMBOLS:
        reasons.append(f"eligible_symbols_below_{ML_READY_MIN_SYMBOLS}")
        return FeatureStackStatus.PARTIAL, reasons
    if eligible_symbols > 0:
        reasons.append(f"eligible_symbols_below_{ML_PARTIAL_MIN_SYMBOLS}")
        return FeatureStackStatus.INSUFFICIENT, reasons
    reasons.append("no_eligible_symbols")
    return FeatureStackStatus.INSUFFICIENT, reasons


@dataclass(slots=True)
class MlReadinessResult:
    source_id: int
    years: list[YearReadiness] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        ready = [y.year for y in self.years if y.feature_stack_status is FeatureStackStatus.READY]
        return {
            "source_id": self.source_id,
            "warmup_observations": FEATURE_WARMUP_OBSERVATIONS,
            "years_total": len(self.years),
            "years_ready": len(ready),
            "first_ready_year": min(ready) if ready else None,
            "last_ready_year": max(ready) if ready else None,
            "years": [y.to_dict() for y in self.years],
        }


def evaluate_ml_readiness(
    session: Session, source_id: int, *, persist: bool = True
) -> MlReadinessResult:
    rows = session.execute(
        _YEAR_STATS_SQL,
        {
            "source_id": source_id,
            "warmup": FEATURE_WARMUP_OBSERVATIONS,
            "eligible": Eligibility.ELIGIBLE.value,
        },
    ).mappings()

    result = MlReadinessResult(source_id=source_id)
    for row in rows:
        median_observations = (
            None if row["median_observations"] is None else float(row["median_observations"])
        )
        eligible_symbols = int(row["eligible_symbols"])
        symbols_with_warmup = int(row["symbols_with_warmup"])
        status, reasons = classify_year(
            eligible_symbols=eligible_symbols,
            symbols_with_warmup=symbols_with_warmup,
            median_observations=median_observations,
        )
        result.years.append(
            YearReadiness(
                year=int(row["year"]),
                symbols=int(row["symbols"]),
                eligible_symbols=eligible_symbols,
                rows=int(row["rows"] or 0),
                eligible_rows=int(row["eligible_rows"] or 0),
                median_observations=median_observations,
                symbols_with_warmup=symbols_with_warmup,
                feature_stack_status=status,
                blocking_reasons=reasons,
            )
        )

    if persist:
        for year in result.years:
            session.execute(
                _UPSERT_SQL,
                {
                    "source_id": source_id,
                    "year": year.year,
                    "symbols": year.symbols,
                    "eligible_symbols": year.eligible_symbols,
                    "rows": year.rows,
                    "eligible_rows": year.eligible_rows,
                    "median_observations": year.median_observations,
                    "feature_stack_status": year.feature_stack_status.value,
                    "blocking_reasons": json.dumps(year.blocking_reasons),
                    "metrics": json.dumps({"symbols_with_warmup": year.symbols_with_warmup}),
                },
            )
    return result
