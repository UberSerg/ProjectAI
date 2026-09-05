"""Operator orchestration for External Deep History V0.

Audit is the safe default. Ingest / reconcile / curate are explicit steps and never
touch market.candles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.modules.market_history.application.audit import audit_file
from app.modules.market_history.application.curate import curate_source
from app.modules.market_history.application.identity import classify_symbols, current_cohort_symbols
from app.modules.market_history.application.ingest import ingest_file, register_source
from app.modules.market_history.application.ml_readiness import evaluate_ml_readiness
from app.modules.market_history.application.read_models import status_payload
from app.modules.market_history.application.reconcile import reconcile_source
from app.modules.market_history.application.report import (
    DEFAULT_ARTIFACT_DIR,
    build_audit_report,
    compact_report,
    finish_run,
    persist_catalog,
    start_run,
    write_artifact,
)
from app.modules.market_history.domain.types import (
    RunStatus,
    RunType,
    SourceStatus,
)
from app.modules.market_history.infrastructure.parser import file_fingerprint


@dataclass(slots=True)
class PipelineResult:
    steps: dict[str, Any] = field(default_factory=dict)
    artifact_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"steps": self.steps, "artifact_path": self.artifact_path}


def run_audit(
    session: Session,
    path: Path,
    *,
    limit: int | None = None,
    artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
) -> PipelineResult:
    """Profile the CSV, register provenance, persist catalog. No candle ingest."""
    out = PipelineResult()
    fingerprint = file_fingerprint(path)
    source, created = register_source(
        session, fingerprint, metadata={"host_path_hint": str(path)}
    )
    session.commit()

    run = start_run(session, RunType.AUDIT, source_id=source.id)
    session.commit()
    try:
        audit = audit_file(path, limit=limit)
        cohort = current_cohort_symbols(session)
        classifications = classify_symbols(list(audit.profiles.keys()), cohort)
        report = build_audit_report(
            audit, classifications, fingerprint, source_id=source.id
        )
        persist_catalog(session, source.id, audit, classifications)
        source.status = SourceStatus.AUDITED.value
        source.audit_summary = {
            **(source.audit_summary or {}),
            "audit": compact_report(report),
        }
        session.add(source)
        finish_run(
            session,
            run,
            status=RunStatus.SUCCESS,
            report=compact_report(report),
            metrics=audit.summary(),
            source_id=source.id,
        )
        session.commit()
        artifact = write_artifact(report, artifact_dir)
        out.artifact_path = str(artifact)
        out.steps["audit"] = {
            "created_source": created,
            "source_id": source.id,
            **audit.summary(),
            "identity": report["identity"],
        }
    except Exception as exc:
        finish_run(session, run, status=RunStatus.FAILED, metrics={"error": str(exc)})
        session.commit()
        raise
    return out


def run_ingest(
    session: Session,
    path: Path,
    *,
    batch_rows: int = 50_000,
    limit: int | None = None,
    force: bool = False,
) -> PipelineResult:
    out = PipelineResult()
    run = start_run(session, RunType.INGEST)
    session.commit()
    try:
        result = ingest_file(
            session, path, batch_rows=batch_rows, limit=limit, force=force
        )
        status = RunStatus.NO_CHANGES if result.status == "NO_CHANGES" else RunStatus.SUCCESS
        finish_run(
            session,
            run,
            status=status,
            metrics=result.to_dict(),
            source_id=result.source_id,
        )
        session.commit()
        out.steps["ingest"] = result.to_dict()
    except Exception as exc:
        finish_run(session, run, status=RunStatus.FAILED, metrics={"error": str(exc)})
        session.commit()
        raise
    return out


def run_reconcile(session: Session, *, source_id: int | None = None) -> PipelineResult:
    from app.modules.market_history.application.ingest import find_source

    out = PipelineResult()
    source = find_source(session) if source_id is None else None
    if source_id is None:
        if source is None:
            raise ValueError("no EXTERNAL_30Y_CSV_V0 source registered; run audit/ingest first")
        source_id = source.id
    run = start_run(session, RunType.RECONCILE, source_id=source_id)
    session.commit()
    try:
        result = reconcile_source(session, source_id)
        finish_run(
            session,
            run,
            status=RunStatus.SUCCESS,
            report=result.to_dict(),
            metrics={
                "price_semantic": result.price_semantic.value,
                "status_counts": result.status_counts(),
            },
            source_id=source_id,
        )
        session.commit()
        out.steps["reconcile"] = result.to_dict()
    except Exception as exc:
        finish_run(session, run, status=RunStatus.FAILED, metrics={"error": str(exc)})
        session.commit()
        raise
    return out


def run_curate(session: Session, *, allow_unknown: bool = False) -> PipelineResult:
    from app.modules.market_history.application.ingest import find_source

    out = PipelineResult()
    source = find_source(session)
    if source is None:
        raise ValueError("no EXTERNAL_30Y_CSV_V0 source registered")
    run = start_run(session, RunType.CURATE, source_id=source.id)
    session.commit()
    try:
        result = curate_source(session, source.id, allow_unknown=allow_unknown)
        ml = evaluate_ml_readiness(session, source.id)
        finish_run(
            session,
            run,
            status=RunStatus.SUCCESS,
            report={"curate": result.to_dict(), "ml_readiness": ml.to_dict()},
            metrics=result.to_dict(),
            source_id=source.id,
        )
        session.commit()
        out.steps["curate"] = result.to_dict()
        out.steps["ml_readiness"] = ml.to_dict()
    except Exception as exc:
        finish_run(session, run, status=RunStatus.FAILED, metrics={"error": str(exc)})
        session.commit()
        raise
    return out


def run_status(session: Session) -> dict[str, Any]:
    return status_payload(session)
