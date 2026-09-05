"""Reconcile staged external bars against canonical RAW MOEX candles.

Read-only against market.candles. External data is evidence about the source
file, never a correction applied to the canonical observation store.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.market_history.application.ca_probes import (
    CaProbeOutcome,
    run_ca_probes,
)
from app.modules.market_history.domain.types import (
    MOEX_CANDLE_SOURCE,
    MOEX_CANDLE_TIMEFRAME,
    RECON_ADJUSTED_MIN_MEDIAN,
    RECON_MATCH_MAX_MEDIAN,
    RECON_MIN_OVERLAP_ROWS,
    RECON_SMALL_DIFF_MAX_MEDIAN,
    CaProbeVerdict,
    MatchStatus,
    PriceSemantic,
    ReconciliationStatus,
)

# Percentile aggregates are computed in PostgreSQL so no candle frame is
# materialised in Python.
_RECONCILE_SQL = text(
    """
    WITH ext AS (
        SELECT e.source_symbol, e.trade_date, e.open, e.high, e.low, e.close, e.volume
        FROM market.external_candles_daily e
        JOIN market.external_source_instruments si
          ON si.source_id = e.source_id AND si.source_symbol = e.source_symbol
        WHERE e.source_id = :source_id
          AND e.reject_reason IS NULL
          AND si.match_status = :match_status
          AND si.project_symbol IS NOT NULL
    ),
    moex AS (
        SELECT i.symbol AS project_symbol,
               (c.timestamp AT TIME ZONE 'UTC')::date AS trade_date,
               c.open, c.high, c.low, c.close, c.volume
        FROM market.candles c
        JOIN market.instruments i ON i.id = c.instrument_id
        WHERE c.timeframe = :timeframe AND c.source = :source
    ),
    joined AS (
        SELECT ext.source_symbol,
               moex.project_symbol,
               ext.trade_date,
               ext.close AS ext_close,
               moex.close AS moex_close,
               ext.volume AS ext_volume,
               moex.volume AS moex_volume,
               (ext.open = moex.open AND ext.high = moex.high
                AND ext.low = moex.low AND ext.close = moex.close) AS exact_ohlc,
               CASE WHEN moex.close > 0
                    THEN abs(ext.close - moex.close) / moex.close END AS close_rel,
               CASE WHEN moex.volume > 0
                    THEN abs(ext.volume - moex.volume) / moex.volume END AS volume_rel
        FROM ext
        JOIN moex ON moex.project_symbol = ext.source_symbol
                 AND moex.trade_date = ext.trade_date
    )
    SELECT source_symbol,
           min(project_symbol) AS project_symbol,
           count(*) AS overlap_rows,
           count(*) FILTER (WHERE exact_ohlc) AS exact_ohlc_rows,
           percentile_cont(0.50) WITHIN GROUP (ORDER BY close_rel) AS close_rel_med,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY close_rel) AS close_rel_p95,
           percentile_cont(0.99) WITHIN GROUP (ORDER BY close_rel) AS close_rel_p99,
           percentile_cont(0.50) WITHIN GROUP (ORDER BY volume_rel) AS volume_rel_med,
           min(trade_date) AS overlap_from,
           max(trade_date) AS overlap_to
    FROM joined
    GROUP BY source_symbol
    ORDER BY source_symbol;
    """
)

_UPSERT_SQL = text(
    """
    INSERT INTO market.external_reconciliation (
        source_id, source_symbol, project_symbol, overlap_rows, exact_ohlc_rows,
        close_rel_med, close_rel_p95, close_rel_p99, volume_rel_med, status,
        ca_probe_result, metrics, updated_at
    ) VALUES (
        :source_id, :source_symbol, :project_symbol, :overlap_rows, :exact_ohlc_rows,
        :close_rel_med, :close_rel_p95, :close_rel_p99, :volume_rel_med, :status,
        CAST(:ca_probe_result AS jsonb), CAST(:metrics AS jsonb), NOW()
    )
    ON CONFLICT (source_id, source_symbol) DO UPDATE SET
        project_symbol = EXCLUDED.project_symbol,
        overlap_rows = EXCLUDED.overlap_rows,
        exact_ohlc_rows = EXCLUDED.exact_ohlc_rows,
        close_rel_med = EXCLUDED.close_rel_med,
        close_rel_p95 = EXCLUDED.close_rel_p95,
        close_rel_p99 = EXCLUDED.close_rel_p99,
        volume_rel_med = EXCLUDED.volume_rel_med,
        status = EXCLUDED.status,
        ca_probe_result = EXCLUDED.ca_probe_result,
        metrics = EXCLUDED.metrics,
        updated_at = NOW();
    """
)


@dataclass(frozen=True, slots=True)
class SymbolReconciliation:
    source_symbol: str
    project_symbol: str | None
    overlap_rows: int
    exact_ohlc_rows: int
    close_rel_med: float | None
    close_rel_p95: float | None
    close_rel_p99: float | None
    volume_rel_med: float | None
    status: ReconciliationStatus
    overlap_from: str | None = None
    overlap_to: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_symbol": self.source_symbol,
            "project_symbol": self.project_symbol,
            "overlap_rows": self.overlap_rows,
            "exact_ohlc_rows": self.exact_ohlc_rows,
            "exact_ohlc_share": (
                round(self.exact_ohlc_rows / self.overlap_rows, 6) if self.overlap_rows else None
            ),
            "close_rel_med": self.close_rel_med,
            "close_rel_p95": self.close_rel_p95,
            "close_rel_p99": self.close_rel_p99,
            "volume_rel_med": self.volume_rel_med,
            "status": self.status.value,
            "overlap_from": self.overlap_from,
            "overlap_to": self.overlap_to,
        }


def classify_reconciliation(
    *, overlap_rows: int, close_rel_med: float | None, close_rel_p95: float | None
) -> ReconciliationStatus:
    """Bucket one symbol from overlap statistics alone."""
    if overlap_rows < RECON_MIN_OVERLAP_ROWS or close_rel_med is None:
        return ReconciliationStatus.UNKNOWN
    if close_rel_med <= RECON_MATCH_MAX_MEDIAN:
        return ReconciliationStatus.MATCH
    if close_rel_med <= RECON_SMALL_DIFF_MAX_MEDIAN:
        return ReconciliationStatus.SMALL_DIFF
    if close_rel_med >= RECON_ADJUSTED_MIN_MEDIAN:
        # A systematic level offset across the whole overlap is the signature of
        # back-adjusted prices rather than random data corruption.
        if close_rel_p95 is not None and close_rel_p95 / max(close_rel_med, 1e-12) < 20.0:
            return ReconciliationStatus.LIKELY_ADJUSTED
    return ReconciliationStatus.LARGE_DIFF


@dataclass(slots=True)
class ReconcileResult:
    source_id: int
    symbols: list[SymbolReconciliation] = field(default_factory=list)
    probes: list[CaProbeOutcome] = field(default_factory=list)
    price_semantic: PriceSemantic = PriceSemantic.UNKNOWN
    semantic_evidence: dict[str, Any] = field(default_factory=dict)

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.symbols:
            counts[row.status.value] = counts.get(row.status.value, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "symbols_compared": len(self.symbols),
            "status_counts": self.status_counts(),
            "price_semantic": self.price_semantic.value,
            "semantic_evidence": self.semantic_evidence,
            "symbols": [s.to_dict() for s in self.symbols],
            "ca_probes": [p.to_dict() for p in self.probes],
        }


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


def compare_symbols(session: Session, source_id: int) -> list[SymbolReconciliation]:
    rows = session.execute(
        _RECONCILE_SQL,
        {
            "source_id": source_id,
            "match_status": MatchStatus.EXACT_CURRENT_MATCH.value,
            "timeframe": MOEX_CANDLE_TIMEFRAME,
            "source": MOEX_CANDLE_SOURCE,
        },
    ).mappings()

    out: list[SymbolReconciliation] = []
    for row in rows:
        close_rel_med = _f(row["close_rel_med"])
        close_rel_p95 = _f(row["close_rel_p95"])
        overlap_rows = int(row["overlap_rows"])
        out.append(
            SymbolReconciliation(
                source_symbol=row["source_symbol"],
                project_symbol=row["project_symbol"],
                overlap_rows=overlap_rows,
                exact_ohlc_rows=int(row["exact_ohlc_rows"]),
                close_rel_med=close_rel_med,
                close_rel_p95=close_rel_p95,
                close_rel_p99=_f(row["close_rel_p99"]),
                volume_rel_med=_f(row["volume_rel_med"]),
                status=classify_reconciliation(
                    overlap_rows=overlap_rows,
                    close_rel_med=close_rel_med,
                    close_rel_p95=close_rel_p95,
                ),
                overlap_from=row["overlap_from"].isoformat() if row["overlap_from"] else None,
                overlap_to=row["overlap_to"].isoformat() if row["overlap_to"] else None,
            )
        )
    return out


def classify_price_semantic(
    symbols: list[SymbolReconciliation], probes: list[CaProbeOutcome]
) -> tuple[PriceSemantic, dict[str, Any]]:
    """Combine overlap statistics and corporate-action probes.

    Deliberately not a single threshold: a verdict needs agreement between the
    level comparison against RAW MOEX and the mechanical-event fingerprints.
    """
    decided = [p for p in probes if p.verdict is not CaProbeVerdict.UNKNOWN]
    raw_probes = [p for p in decided if p.verdict is CaProbeVerdict.RAW]
    adjusted_probes = [p for p in decided if p.verdict is not CaProbeVerdict.RAW]

    comparable = [s for s in symbols if s.status is not ReconciliationStatus.UNKNOWN]
    matching = [
        s
        for s in comparable
        if s.status in (ReconciliationStatus.MATCH, ReconciliationStatus.SMALL_DIFF)
    ]
    adjusted_like = [s for s in comparable if s.status is ReconciliationStatus.LIKELY_ADJUSTED]
    large_diff = [s for s in comparable if s.status is ReconciliationStatus.LARGE_DIFF]

    evidence: dict[str, Any] = {
        "probes_total": len(probes),
        "probes_decided": len(decided),
        "probes_raw": len(raw_probes),
        "probes_adjusted": len(adjusted_probes),
        "symbols_comparable": len(comparable),
        "symbols_matching": len(matching),
        "symbols_likely_adjusted": len(adjusted_like),
        "symbols_large_diff": len(large_diff),
    }

    if not comparable and not decided:
        evidence["rule"] = "no_evidence"
        return PriceSemantic.UNKNOWN, evidence

    match_share = len(matching) / len(comparable) if comparable else None
    adjusted_share = len(adjusted_like) / len(comparable) if comparable else None
    large_share = len(large_diff) / len(comparable) if comparable else None
    evidence["match_share"] = None if match_share is None else round(match_share, 4)
    evidence["adjusted_share"] = None if adjusted_share is None else round(adjusted_share, 4)
    evidence["large_diff_share"] = None if large_share is None else round(large_share, 4)

    probes_all_raw = bool(decided) and not adjusted_probes
    probes_all_adjusted = bool(decided) and not raw_probes
    overlap_raw_like = match_share is not None and match_share >= 0.9
    overlap_adjusted_like = adjusted_share is not None and adjusted_share >= 0.5

    # Overlap disagreement dominates: some names match RAW MOEX while others are
    # systematically offset (classic mixed Finam/vendor back-adjusted subset).
    if match_share is not None and adjusted_share is not None and matching and adjusted_like:
        evidence["rule"] = "overlap_statuses_disagree"
        return PriceSemantic.MIXED, evidence

    if raw_probes and adjusted_probes:
        evidence["rule"] = "probe_verdicts_disagree"
        return PriceSemantic.MIXED, evidence

    if (probes_all_raw and (match_share is None or overlap_raw_like)) or (
        not decided and overlap_raw_like
    ):
        evidence["rule"] = "raw_probes_and_overlap_agree"
        return PriceSemantic.RAW_COMPATIBLE, evidence

    if probes_all_adjusted or (not decided and overlap_adjusted_like):
        evidence["rule"] = "adjusted_signature_dominant"
        return PriceSemantic.LIKELY_ADJUSTED, evidence

    if large_share is not None and large_share >= 0.5:
        evidence["rule"] = "overlap_large_diff_without_adjustment_signature"
        return PriceSemantic.INCOMPATIBLE, evidence

    evidence["rule"] = "insufficient_agreement"
    return PriceSemantic.UNKNOWN, evidence


def reconcile_source(session: Session, source_id: int, *, persist: bool = True) -> ReconcileResult:
    symbols = compare_symbols(session, source_id)
    probes = run_ca_probes(session, source_id)
    semantic, evidence = classify_price_semantic(symbols, probes)
    result = ReconcileResult(
        source_id=source_id,
        symbols=symbols,
        probes=probes,
        price_semantic=semantic,
        semantic_evidence=evidence,
    )
    if persist:
        _persist(session, result)
    return result


def _persist(session: Session, result: ReconcileResult) -> None:
    probes_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for probe in result.probes:
        probes_by_symbol.setdefault(probe.symbol, []).append(probe.to_dict())

    for row in result.symbols:
        session.execute(
            _UPSERT_SQL,
            {
                "source_id": result.source_id,
                "source_symbol": row.source_symbol,
                "project_symbol": row.project_symbol,
                "overlap_rows": row.overlap_rows,
                "exact_ohlc_rows": row.exact_ohlc_rows,
                "close_rel_med": row.close_rel_med,
                "close_rel_p95": row.close_rel_p95,
                "close_rel_p99": row.close_rel_p99,
                "volume_rel_med": row.volume_rel_med,
                "status": row.status.value,
                "ca_probe_result": json.dumps(
                    {"probes": probes_by_symbol.get(row.source_symbol, [])}
                ),
                "metrics": json.dumps(
                    {"overlap_from": row.overlap_from, "overlap_to": row.overlap_to}
                ),
            },
        )

    session.execute(
        text(
            """
            UPDATE market.external_sources
            SET price_semantic = :semantic,
                status = :status,
                audit_summary = audit_summary
                    || jsonb_build_object('reconcile', CAST(:evidence AS jsonb)),
                updated_at = NOW()
            WHERE id = :source_id
            """
        ),
        {
            "semantic": result.price_semantic.value,
            "status": "RECONCILED",
            "evidence": json.dumps(
                {
                    "price_semantic": result.price_semantic.value,
                    "evidence": result.semantic_evidence,
                    "status_counts": result.status_counts(),
                    "evaluated_at": datetime.now(UTC).isoformat(),
                }
            ),
            "source_id": result.source_id,
        },
    )
