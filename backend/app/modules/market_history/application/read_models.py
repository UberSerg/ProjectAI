"""Read-only projections of External Deep History V0 staging for the API."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.modules.market_history.domain.types import (
    AUDIT_REPORT_KIND,
    SOURCE_CODE,
    Eligibility,
    RunType,
)
from app.modules.market_history.infrastructure.models import (
    ExternalAuditRun,
    ExternalSource,
)


def get_source(session: Session) -> ExternalSource | None:
    return session.scalar(select(ExternalSource).where(ExternalSource.source_code == SOURCE_CODE))


def _source_dict(source: ExternalSource) -> dict[str, Any]:
    return {
        "source_id": source.id,
        "source_code": source.source_code,
        "file_name": source.file_name,
        "file_size": source.file_size,
        "file_sha256": source.file_sha256,
        "parser_version": source.parser_version,
        "price_semantic": source.price_semantic,
        "status": source.status,
        "imported_at": source.imported_at.isoformat() if source.imported_at else None,
    }


def status_payload(session: Session) -> dict[str, Any]:
    """Lightweight liveness view: is anything staged, and how far did it get."""
    source = get_source(session)
    if source is None:
        return {
            "kind": AUDIT_REPORT_KIND,
            "source_code": SOURCE_CODE,
            "registered": False,
            "status": "NOT_REGISTERED",
            "price_semantic": "UNKNOWN",
            "runs": [],
        }

    runs = list(
        session.scalars(
            select(ExternalAuditRun)
            .where(ExternalAuditRun.source_id == source.id)
            .order_by(ExternalAuditRun.started_at.desc())
            .limit(10)
        )
    )
    staged_rows = int(
        session.execute(
            text("SELECT count(*) FROM market.external_candles_daily WHERE source_id = :sid"),
            {"sid": source.id},
        ).scalar_one()
    )
    return {
        "kind": AUDIT_REPORT_KIND,
        "registered": True,
        **_source_dict(source),
        "staged_rows": staged_rows,
        "runs": [
            {
                "id": run.id,
                "run_type": run.run_type,
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "metrics": run.metrics,
            }
            for run in runs
        ],
    }


def summary_payload(session: Session) -> dict[str, Any]:
    """Aggregate counters plus the latest audit report metrics."""
    source = get_source(session)
    if source is None:
        return {"kind": AUDIT_REPORT_KIND, "registered": False}

    totals = session.execute(
        text(
            """
            SELECT count(*) AS rows,
                   count(*) FILTER (WHERE reject_reason IS NULL) AS valid_rows,
                   count(*) FILTER (WHERE reject_reason IS NOT NULL) AS rejected_rows,
                   count(DISTINCT source_symbol) AS symbols,
                   min(trade_date) AS min_date,
                   max(trade_date) AS max_date
            FROM market.external_candles_daily
            WHERE source_id = :sid
            """
        ),
        {"sid": source.id},
    ).mappings().one()

    match_counts = {
        str(row.match_status): int(row.symbols)
        for row in session.execute(
            text(
                "SELECT match_status, count(*) AS symbols "
                "FROM market.external_source_instruments WHERE source_id = :sid "
                "GROUP BY match_status ORDER BY match_status"
            ),
            {"sid": source.id},
        )
    }
    quality_counts = {
        str(row.quality_status): int(row.symbols)
        for row in session.execute(
            text(
                "SELECT quality_status, count(*) AS symbols "
                "FROM market.external_source_instruments WHERE source_id = :sid "
                "GROUP BY quality_status ORDER BY quality_status"
            ),
            {"sid": source.id},
        )
    }
    eligibility_counts = {
        str(row.eligibility): int(row.rows)
        for row in session.execute(
            text(
                "SELECT eligibility, count(*) AS rows "
                "FROM market.external_curated_eligibility WHERE source_id = :sid "
                "GROUP BY eligibility ORDER BY eligibility"
            ),
            {"sid": source.id},
        )
    }

    latest_audit = session.scalar(
        select(ExternalAuditRun)
        .where(
            ExternalAuditRun.source_id == source.id,
            ExternalAuditRun.run_type == RunType.AUDIT.value,
        )
        .order_by(ExternalAuditRun.started_at.desc())
        .limit(1)
    )

    return {
        "kind": AUDIT_REPORT_KIND,
        "registered": True,
        **_source_dict(source),
        "rows": int(totals["rows"]),
        "valid_rows": int(totals["valid_rows"]),
        "rejected_rows": int(totals["rejected_rows"]),
        "symbols": int(totals["symbols"]),
        "min_date": totals["min_date"].isoformat() if totals["min_date"] else None,
        "max_date": totals["max_date"].isoformat() if totals["max_date"] else None,
        "match_counts": match_counts,
        "quality_counts": quality_counts,
        "eligibility_counts": eligibility_counts,
        "audit_summary": source.audit_summary,
        "latest_audit_metrics": latest_audit.metrics if latest_audit else {},
        "canonical_candles_untouched": True,
    }


def instruments_payload(
    session: Session,
    *,
    match_status: str | None = None,
    research_eligible: bool | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    source = get_source(session)
    if source is None:
        return {"items": [], "total": 0}

    where = ["source_id = :sid"]
    params: dict[str, Any] = {"sid": source.id, "limit": limit, "offset": offset}
    if match_status is not None:
        where.append("match_status = :match_status")
        params["match_status"] = match_status
    if research_eligible is not None:
        where.append("research_eligible = :research_eligible")
        params["research_eligible"] = research_eligible
    clause = " AND ".join(where)

    total = int(
        session.execute(
            text(
                f"SELECT count(*) FROM market.external_source_instruments WHERE {clause}"  # noqa: S608
            ),
            params,
        ).scalar_one()
    )
    rows = session.execute(
        text(
            f"""
            SELECT source_symbol, first_date, last_date, observations, active_years,
                   match_status, mapping_confidence, project_symbol, quality_status,
                   research_eligible, metadata
            FROM market.external_source_instruments
            WHERE {clause}
            ORDER BY source_symbol
            LIMIT :limit OFFSET :offset
            """  # noqa: S608
        ),
        params,
    ).mappings()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "source_symbol": row["source_symbol"],
                "first_date": row["first_date"].isoformat() if row["first_date"] else None,
                "last_date": row["last_date"].isoformat() if row["last_date"] else None,
                "observations": int(row["observations"]),
                "active_years": list(row["active_years"] or []),
                "match_status": row["match_status"],
                "mapping_confidence": float(row["mapping_confidence"]),
                "project_symbol": row["project_symbol"],
                "quality_status": row["quality_status"],
                "research_eligible": bool(row["research_eligible"]),
                "metrics": row["metadata"],
            }
            for row in rows
        ],
    }


def coverage_payload(session: Session) -> dict[str, Any]:
    source = get_source(session)
    if source is None:
        return {"items": []}

    rows = session.execute(
        text(
            """
            SELECT EXTRACT(YEAR FROM e.trade_date)::INTEGER AS year,
                   count(*) AS rows,
                   count(*) FILTER (WHERE e.reject_reason IS NULL) AS valid_rows,
                   count(DISTINCT e.source_symbol) AS symbols,
                   count(*) FILTER (WHERE ce.eligibility = :eligible) AS eligible_rows
            FROM market.external_candles_daily e
            LEFT JOIN market.external_curated_eligibility ce
              ON ce.source_id = e.source_id
             AND ce.source_symbol = e.source_symbol
             AND ce.trade_date = e.trade_date
            WHERE e.source_id = :sid
            GROUP BY 1
            ORDER BY 1
            """
        ),
        {"sid": source.id, "eligible": Eligibility.ELIGIBLE.value},
    ).mappings()

    return {
        "source_id": source.id,
        "items": [
            {
                "year": int(row["year"]),
                "rows": int(row["rows"]),
                "valid_rows": int(row["valid_rows"]),
                "symbols": int(row["symbols"]),
                "eligible_rows": int(row["eligible_rows"]),
            }
            for row in rows
        ],
    }


def reconciliation_payload(session: Session, *, limit: int = 200) -> dict[str, Any]:
    source = get_source(session)
    if source is None:
        return {"items": [], "price_semantic": "UNKNOWN"}

    rows = session.execute(
        text(
            """
            SELECT source_symbol, project_symbol, overlap_rows, exact_ohlc_rows,
                   close_rel_med, close_rel_p95, close_rel_p99, volume_rel_med,
                   status, metrics
            FROM market.external_reconciliation
            WHERE source_id = :sid
            ORDER BY source_symbol
            LIMIT :limit
            """
        ),
        {"sid": source.id, "limit": limit},
    ).mappings()

    items = [
        {
            "source_symbol": row["source_symbol"],
            "project_symbol": row["project_symbol"],
            "overlap_rows": int(row["overlap_rows"]),
            "exact_ohlc_rows": int(row["exact_ohlc_rows"]),
            "exact_ohlc_share": (
                round(int(row["exact_ohlc_rows"]) / int(row["overlap_rows"]), 6)
                if row["overlap_rows"]
                else None
            ),
            "close_rel_med": row["close_rel_med"],
            "close_rel_p95": row["close_rel_p95"],
            "close_rel_p99": row["close_rel_p99"],
            "volume_rel_med": row["volume_rel_med"],
            "status": row["status"],
            "metrics": row["metrics"],
        }
        for row in rows
    ]
    status_counts: dict[str, int] = {}
    for item in items:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1

    return {
        "source_id": source.id,
        "price_semantic": source.price_semantic,
        "semantic_evidence": (source.audit_summary or {}).get("reconcile", {}),
        "status_counts": status_counts,
        "items": items,
    }


def ml_readiness_payload(session: Session) -> dict[str, Any]:
    source = get_source(session)
    if source is None:
        return {"items": []}

    rows = session.execute(
        text(
            """
            SELECT year, symbols, eligible_symbols, rows, eligible_rows,
                   median_observations, feature_stack_status, blocking_reasons, metrics
            FROM market.external_ml_readiness
            WHERE source_id = :sid
            ORDER BY year
            """
        ),
        {"sid": source.id},
    ).mappings()

    items = [
        {
            "year": int(row["year"]),
            "symbols": int(row["symbols"]),
            "eligible_symbols": int(row["eligible_symbols"]),
            "rows": int(row["rows"]),
            "eligible_rows": int(row["eligible_rows"]),
            "median_observations": row["median_observations"],
            "feature_stack_status": row["feature_stack_status"],
            "blocking_reasons": row["blocking_reasons"],
            "metrics": row["metrics"],
        }
        for row in rows
    ]
    ready_years = [i["year"] for i in items if i["feature_stack_status"] == "READY"]
    return {
        "source_id": source.id,
        "years_total": len(items),
        "years_ready": len(ready_years),
        "first_ready_year": min(ready_years) if ready_years else None,
        "last_ready_year": max(ready_years) if ready_years else None,
        "items": items,
    }


def ca_probes_payload(session: Session) -> dict[str, Any]:
    source = get_source(session)
    if source is None:
        return {"items": []}

    rows = session.execute(
        text(
            """
            SELECT source_symbol, ca_probe_result
            FROM market.external_reconciliation
            WHERE source_id = :sid AND ca_probe_result -> 'probes' IS NOT NULL
            ORDER BY source_symbol
            """
        ),
        {"sid": source.id},
    ).mappings()

    items: list[dict[str, Any]] = []
    for row in rows:
        for probe in (row["ca_probe_result"] or {}).get("probes", []):
            items.append(probe)

    verdict_counts: dict[str, int] = {}
    for item in items:
        verdict = str(item.get("verdict", "UNKNOWN"))
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1

    return {
        "source_id": source.id,
        "price_semantic": source.price_semantic,
        "verdict_counts": verdict_counts,
        "items": items,
    }
