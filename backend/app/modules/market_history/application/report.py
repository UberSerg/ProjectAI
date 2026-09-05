"""EXTERNAL_DEEP_HISTORY_AUDIT_V0 report assembly and persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.market_history.application.audit import AuditResult
from app.modules.market_history.application.identity import SymbolClassification
from app.modules.market_history.domain.types import (
    AUDIT_REPORT_KIND,
    PARSER_VERSION,
    SOURCE_CODE,
    MatchStatus,
    RunStatus,
    RunType,
)
from app.modules.market_history.infrastructure.models import ExternalAuditRun
from app.modules.market_history.infrastructure.parser import FileFingerprint

DEFAULT_ARTIFACT_DIR = Path(".tmp/external-deep-history-v0")
MAX_SYMBOLS_IN_DB_REPORT = 400

_UPSERT_INSTRUMENT_SQL = text(
    """
    INSERT INTO market.external_source_instruments (
        source_id, source_symbol, first_date, last_date, observations, active_years,
        match_status, mapping_confidence, project_symbol, quality_status,
        research_eligible, metadata, updated_at
    ) VALUES (
        :source_id, :source_symbol, :first_date, :last_date, :observations,
        CAST(:active_years AS integer[]), :match_status, :mapping_confidence,
        :project_symbol, :quality_status, FALSE, CAST(:metadata AS jsonb), NOW()
    )
    ON CONFLICT (source_id, source_symbol) DO UPDATE SET
        first_date = EXCLUDED.first_date,
        last_date = EXCLUDED.last_date,
        observations = EXCLUDED.observations,
        active_years = EXCLUDED.active_years,
        match_status = EXCLUDED.match_status,
        mapping_confidence = EXCLUDED.mapping_confidence,
        project_symbol = EXCLUDED.project_symbol,
        quality_status = EXCLUDED.quality_status,
        metadata = EXCLUDED.metadata,
        updated_at = NOW();
    """
)


def start_run(
    session: Session, run_type: RunType, *, source_id: int | None = None
) -> ExternalAuditRun:
    run = ExternalAuditRun(
        source_id=source_id,
        run_type=run_type.value,
        status=RunStatus.RUNNING.value,
    )
    session.add(run)
    session.flush()
    return run


def finish_run(
    session: Session,
    run: ExternalAuditRun,
    *,
    status: RunStatus,
    report: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    source_id: int | None = None,
) -> ExternalAuditRun:
    run.status = status.value
    run.finished_at = datetime.now(UTC)
    if report is not None:
        run.report = report
    if metrics is not None:
        run.metrics = metrics
    if source_id is not None:
        run.source_id = source_id
    session.add(run)
    session.flush()
    return run


def build_audit_report(
    audit: AuditResult,
    classifications: dict[str, SymbolClassification],
    fingerprint: FileFingerprint,
    *,
    source_id: int | None = None,
) -> dict[str, Any]:
    """Full audit payload: file identity, row accounting, catalog, identity split."""
    match_counts: dict[str, int] = {}
    quality_counts: dict[str, int] = {}
    instruments: list[dict[str, Any]] = []

    for symbol in sorted(audit.profiles):
        profile = audit.profiles[symbol]
        classification = classifications.get(symbol)
        match_status = (
            classification.match_status.value
            if classification
            else MatchStatus.UNKNOWN_HISTORICAL_SYMBOL.value
        )
        match_counts[match_status] = match_counts.get(match_status, 0) + 1
        entry = profile.to_dict()
        quality_counts[entry["quality_status"]] = quality_counts.get(entry["quality_status"], 0) + 1
        entry["match_status"] = match_status
        entry["mapping_confidence"] = classification.mapping_confidence if classification else 0.0
        entry["project_symbol"] = classification.project_symbol if classification else None
        instruments.append(entry)

    coverage_by_year = [
        {"year": year, "rows": count} for year, count in sorted(audit.rows_per_year.items())
    ]
    split_like_total = sum(len(p.split_like_jumps) for p in audit.profiles.values())

    return {
        "kind": AUDIT_REPORT_KIND,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_code": SOURCE_CODE,
        "source_id": source_id,
        "parser_version": PARSER_VERSION,
        "file": {
            "file_name": fingerprint.file_name,
            "file_size": fingerprint.file_size,
            "file_sha256": fingerprint.sha256,
        },
        "rows": audit.summary(),
        "identity": {
            "match_counts": match_counts,
            "note": (
                "Exact symbol match only. Historical renames are never inferred; "
                "unmatched symbols stay UNKNOWN_HISTORICAL_SYMBOL for human curation."
            ),
        },
        "quality": {"quality_counts": quality_counts},
        "corporate_action_signals": {
            "split_like_jump_candidates": split_like_total,
            "symbols_with_jumps": sum(1 for p in audit.profiles.values() if p.jump_count > 0),
        },
        "coverage_by_year": coverage_by_year,
        "instruments": instruments,
    }


def compact_report(report: dict[str, Any]) -> dict[str, Any]:
    """Trim the per-symbol catalog before storing the report in JSONB."""
    instruments = report.get("instruments", [])
    compact = dict(report)
    compact["instruments_total"] = len(instruments)
    if len(instruments) > MAX_SYMBOLS_IN_DB_REPORT:
        compact["instruments"] = instruments[:MAX_SYMBOLS_IN_DB_REPORT]
        compact["instruments_truncated"] = True
    else:
        compact["instruments_truncated"] = False
    return compact


def persist_catalog(
    session: Session,
    source_id: int,
    audit: AuditResult,
    classifications: dict[str, SymbolClassification],
) -> int:
    """Upsert the per-symbol catalog. research_eligible is decided by curate()."""
    for symbol in sorted(audit.profiles):
        profile = audit.profiles[symbol]
        classification = classifications.get(symbol)
        session.execute(
            _UPSERT_INSTRUMENT_SQL,
            {
                "source_id": source_id,
                "source_symbol": symbol,
                "first_date": profile.first_date,
                "last_date": profile.last_date,
                "observations": profile.observations,
                "active_years": "{" + ",".join(str(y) for y in sorted(profile.years)) + "}",
                "match_status": (
                    classification.match_status.value
                    if classification
                    else MatchStatus.UNKNOWN_HISTORICAL_SYMBOL.value
                ),
                "mapping_confidence": (
                    classification.mapping_confidence if classification else 0.0
                ),
                "project_symbol": classification.project_symbol if classification else None,
                "quality_status": profile.quality_status.value,
                "metadata": json.dumps(
                    {
                        "valid_observations": profile.valid_observations,
                        "rejected_observations": profile.rejected_observations,
                        "reject_rate": round(profile.reject_rate, 6),
                        "duplicate_dates": profile.duplicate_dates,
                        "out_of_order_rows": profile.out_of_order_rows,
                        "jump_count": profile.jump_count,
                        "split_like_jumps": profile.split_like_jumps,
                        "min_close": (
                            float(profile.min_close) if profile.min_close is not None else None
                        ),
                        "max_close": (
                            float(profile.max_close) if profile.max_close is not None else None
                        ),
                    }
                ),
            },
        )
    return len(audit.profiles)


def write_artifact(report: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"audit_{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    latest = out_dir / "audit_latest.json"
    latest.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return path
