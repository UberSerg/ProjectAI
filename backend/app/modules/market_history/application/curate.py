"""Materialise per-row research eligibility for staged external history.

Eligibility is a research label on the staging tables. It never promotes a symbol
into the operational universe and never merges external bars into market.candles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.market_history.domain.types import (
    Eligibility,
    MatchStatus,
    PriceSemantic,
    QualityStatus,
    SourceStatus,
)

# Row-level eligibility. For MIXED file semantics, only symbols whose MOEX
# overlap is MATCH/SMALL_DIFF may be ELIGIBLE; LIKELY_ADJUSTED / LARGE_DIFF
# stay EXCLUDED_ADJUSTED_SEMANTIC. Historical-only symbols without overlap stay
# excluded unless the whole file is RAW_COMPATIBLE.
_MATERIALIZE_SQL = text(
    """
    INSERT INTO market.external_curated_eligibility (
        source_id, source_symbol, trade_date, eligibility, reason
    )
    SELECT
        e.source_id,
        e.source_symbol,
        e.trade_date,
        CASE
            WHEN e.reject_reason IS NOT NULL THEN 'EXCLUDED_REJECTED_ROW'
            WHEN si.match_status = 'INDEX_OR_NON_EQUITY' THEN 'EXCLUDED_NON_EQUITY'
            WHEN si.quality_status IN ('INVALID', 'DEGRADED', 'UNKNOWN')
                THEN 'EXCLUDED_QUALITY'
            WHEN :price_semantic = 'INCOMPATIBLE' THEN 'EXCLUDED_ADJUSTED_SEMANTIC'
            WHEN :price_semantic = 'LIKELY_ADJUSTED' THEN 'EXCLUDED_ADJUSTED_SEMANTIC'
            WHEN :price_semantic = 'UNKNOWN' THEN 'EXCLUDED_UNKNOWN_SEMANTIC'
            WHEN :price_semantic = 'MIXED'
                 AND COALESCE(r.status, 'UNKNOWN') IN ('LIKELY_ADJUSTED', 'LARGE_DIFF')
                THEN 'EXCLUDED_ADJUSTED_SEMANTIC'
            WHEN :price_semantic = 'MIXED'
                 AND si.match_status = 'EXACT_CURRENT_MATCH'
                 AND COALESCE(r.status, 'UNKNOWN') NOT IN ('MATCH', 'SMALL_DIFF')
                THEN 'EXCLUDED_ADJUSTED_SEMANTIC'
            WHEN :price_semantic = 'MIXED'
                 AND si.match_status = 'UNKNOWN_HISTORICAL_SYMBOL'
                THEN 'EXCLUDED_UNKNOWN_SEMANTIC'
            WHEN :price_semantic = 'RAW_COMPATIBLE' THEN 'ELIGIBLE'
            WHEN :price_semantic = 'MIXED'
                 AND COALESCE(r.status, 'UNKNOWN') IN ('MATCH', 'SMALL_DIFF')
                THEN 'ELIGIBLE'
            ELSE 'EXCLUDED_UNKNOWN_SEMANTIC'
        END AS eligibility,
        CASE
            WHEN e.reject_reason IS NOT NULL THEN e.reject_reason
            WHEN si.match_status = 'INDEX_OR_NON_EQUITY' THEN si.match_status
            WHEN si.quality_status IN ('INVALID', 'DEGRADED', 'UNKNOWN')
                THEN si.quality_status
            WHEN :price_semantic IN ('LIKELY_ADJUSTED', 'INCOMPATIBLE') THEN :price_semantic
            WHEN :price_semantic = 'MIXED'
                 AND COALESCE(r.status, 'UNKNOWN') IN ('LIKELY_ADJUSTED', 'LARGE_DIFF')
                THEN COALESCE(r.status, 'MIXED')
            WHEN :price_semantic = 'UNKNOWN' THEN :price_semantic
            WHEN :price_semantic = 'MIXED'
                 AND si.match_status = 'UNKNOWN_HISTORICAL_SYMBOL'
                THEN 'MIXED_NO_MOEX_OVERLAP'
            ELSE NULL
        END AS reason
    FROM market.external_candles_daily e
    JOIN market.external_source_instruments si
      ON si.source_id = e.source_id AND si.source_symbol = e.source_symbol
    LEFT JOIN market.external_reconciliation r
      ON r.source_id = e.source_id AND r.source_symbol = e.source_symbol
    WHERE e.source_id = :source_id
    ON CONFLICT (source_id, source_symbol, trade_date) DO UPDATE SET
        eligibility = EXCLUDED.eligibility,
        reason = EXCLUDED.reason;
    """
)

_COUNTS_SQL = text(
    """
    SELECT eligibility, count(*) AS rows
    FROM market.external_curated_eligibility
    WHERE source_id = :source_id
    GROUP BY eligibility
    ORDER BY eligibility;
    """
)

# A historical-only symbol can be research eligible: it never re-enters the
# operational universe, it only becomes usable for regime research.
_RESEARCH_FLAG_SQL = text(
    """
    UPDATE market.external_source_instruments si
    SET research_eligible = (
            si.quality_status IN ('OK', 'SPARSE')
            AND si.match_status IN ('EXACT_CURRENT_MATCH', 'UNKNOWN_HISTORICAL_SYMBOL')
            AND (
                :price_semantic = 'RAW_COMPATIBLE'
                OR (
                    :price_semantic = 'MIXED'
                    AND EXISTS (
                        SELECT 1 FROM market.external_reconciliation r
                        WHERE r.source_id = si.source_id
                          AND r.source_symbol = si.source_symbol
                          AND r.status IN ('MATCH', 'SMALL_DIFF')
                    )
                )
            )
        ),
        updated_at = NOW()
    WHERE si.source_id = :source_id;
    """
)


@dataclass(slots=True)
class CurateResult:
    source_id: int
    price_semantic: str
    eligibility_counts: dict[str, int] = field(default_factory=dict)
    research_eligible_symbols: int = 0
    skipped: bool = False
    skip_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "price_semantic": self.price_semantic,
            "eligibility_counts": self.eligibility_counts,
            "eligible_rows": self.eligibility_counts.get(Eligibility.ELIGIBLE.value, 0),
            "research_eligible_symbols": self.research_eligible_symbols,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }


def curate_source(session: Session, source_id: int, *, allow_unknown: bool = False) -> CurateResult:
    """Recompute eligibility for every staged row of the source."""
    semantic = str(
        session.execute(
            text("SELECT price_semantic FROM market.external_sources WHERE id = :source_id"),
            {"source_id": source_id},
        ).scalar_one()
    )
    result = CurateResult(source_id=source_id, price_semantic=semantic)

    if semantic == PriceSemantic.UNKNOWN.value and not allow_unknown:
        result.skipped = True
        result.skip_reason = (
            "price semantics are UNKNOWN; run reconcile first or pass --allow-unknown "
            "to materialise exclusions only"
        )
        return result

    session.execute(_MATERIALIZE_SQL, {"source_id": source_id, "price_semantic": semantic})
    session.execute(_RESEARCH_FLAG_SQL, {"source_id": source_id, "price_semantic": semantic})

    result.eligibility_counts = {
        str(row.eligibility): int(row.rows)
        for row in session.execute(_COUNTS_SQL, {"source_id": source_id})
    }
    result.research_eligible_symbols = int(
        session.execute(
            text(
                "SELECT count(*) FROM market.external_source_instruments "
                "WHERE source_id = :source_id AND research_eligible"
            ),
            {"source_id": source_id},
        ).scalar_one()
    )
    session.execute(
        text(
            "UPDATE market.external_sources SET status = :status, updated_at = NOW() "
            "WHERE id = :source_id"
        ),
        {"status": SourceStatus.CURATED.value, "source_id": source_id},
    )
    return result


def eligible_quality_statuses() -> tuple[str, ...]:
    return (QualityStatus.OK.value, QualityStatus.SPARSE.value)


def eligible_match_statuses() -> tuple[str, ...]:
    return (
        MatchStatus.EXACT_CURRENT_MATCH.value,
        MatchStatus.UNKNOWN_HISTORICAL_SYMBOL.value,
    )
