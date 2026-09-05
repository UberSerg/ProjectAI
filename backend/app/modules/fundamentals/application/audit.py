"""FUNDAMENTAL_SOURCE_AUDIT_V1 — what each candidate source actually returns.

The verdicts below are the outcome of a live probe of every candidate feed. They are
recorded as data (not prose) so the honest coverage of this module is inspectable from
the API and from a JSON artifact. Nothing here scrapes, retries a 403, or guesses a
publication date; a rejected source stays rejected until a lawful provider exists.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.modules.fundamentals.application.runs import finish_run, start_run
from app.modules.fundamentals.config import DEFAULT_ARTIFACT_DIR, PROVIDER_SOURCE_AUDIT
from app.modules.fundamentals.domain.types import (
    SOURCE_AUDIT_KIND,
    IngestionStatus,
    SourceVerdict,
)
from app.modules.fundamentals.infrastructure.models import fundamentals_schema_ready

AUDIT_DATE = date(2026, 9, 5)


@dataclass(frozen=True, slots=True)
class SourceFinding:
    """One probed endpoint and what it really returned."""

    source: str
    purpose: str
    endpoint: str
    observed: str
    verdict: str
    decision: str


SOURCE_FINDINGS: tuple[SourceFinding, ...] = (
    SourceFinding(
        source="MOEX ISS",
        purpose="ISSUER_IDENTITY",
        endpoint="/iss/securities.json?q={SECID}",
        observed=(
            "Returns emitent_id, emitent_title, emitent_inn, emitent_okpo, isin, type "
            "per security."
        ),
        verdict=SourceVerdict.ACCEPTED.value,
        decision=(
            "Used for issuer identity and instrument→issuer mapping. Exact SECID match only."
        ),
    ),
    SourceFinding(
        source="MOEX ISS",
        purpose="DIVIDENDS",
        endpoint="/iss/securities/{SECID}/dividends.json",
        observed=(
            "Does not return a dividend table — responds with the security description block."
        ),
        verdict=SourceVerdict.REJECTED.value,
        decision="Not used. No dividend rows are derived from this endpoint.",
    ),
    SourceFinding(
        source="MOEX ISS",
        purpose="DIVIDENDS",
        endpoint="/iss/history/engines/stock/markets/shares/.../dividends",
        observed="Returns candle history, not dividend records.",
        verdict=SourceVerdict.REJECTED.value,
        decision="Not used.",
    ),
    SourceFinding(
        source="e-disclosure.ru",
        purpose="FINANCIAL_REPORTS_AND_DISCLOSURE",
        endpoint="https://www.e-disclosure.ru/",
        observed="HTTP 403 for automated access.",
        verdict=SourceVerdict.REJECTED.value,
        decision=(
            "Not automated. The block is not bypassed and the site is not scraped; "
            "a lawful API or licensed feed is required."
        ),
    ),
    SourceFinding(
        source="market.corporate_actions",
        purpose="CORPORATE_EVENTS",
        endpoint="internal (MOEX ISS statistics splits feed)",
        observed=(
            "SPLIT / REVERSE_SPLIT rows with an effective date; the feed carries no "
            "announcement timestamp (known_at is nullable)."
        ),
        verdict=SourceVerdict.ACCEPTED.value,
        decision=(
            "Projected into fundamentals.corporate_events with known_at falling back to "
            "the effective date (conservative, recorded as known_at_basis)."
        ),
    ),
    SourceFinding(
        source="—",
        purpose="FINANCIAL_REPORTS",
        endpoint="—",
        observed="No free source with a provable per-report publication date was found.",
        verdict=SourceVerdict.DEFERRED.value,
        decision=(
            "fundamentals.financial_reports stays empty. Report ingestion records a "
            "DEFERRED run instead of inventing periods or publication dates."
        ),
    ),
    SourceFinding(
        source="—",
        purpose="DIVIDENDS",
        endpoint="—",
        observed="No accepted dividend feed with announcement dates.",
        verdict=SourceVerdict.DEFERRED.value,
        decision=(
            "fundamentals.dividend_events stays empty. Dividends are not credited to any "
            "portfolio and raw dividend price gaps in market.candles are left untouched."
        ),
    ),
)


def build_source_audit_report() -> dict[str, Any]:
    """Deterministic audit payload. Performs no network calls."""
    verdict_counts: dict[str, int] = {}
    for finding in SOURCE_FINDINGS:
        verdict_counts[finding.verdict] = verdict_counts.get(finding.verdict, 0) + 1
    return {
        "kind": SOURCE_AUDIT_KIND,
        "generated_at": datetime.now(UTC).isoformat(),
        "audit_date": AUDIT_DATE.isoformat(),
        "verdict_counts": verdict_counts,
        "findings": [asdict(finding) for finding in SOURCE_FINDINGS],
        "known_at_policy": {
            "rule": "A record is visible at t only when known_at <= t.",
            "no_invented_publication_dates": True,
            "corporate_event_fallback": (
                "known_at = effective date when the split feed provides no announcement "
                "timestamp; later than the truth, so it cannot leak information."
            ),
        },
        "not_done": [
            "No scraping and no 403 bypass.",
            "No invented dividends or reports.",
            "No fuzzy IFRS/RAS metric mapping.",
            "No model training, no Dataset V2 / Forward / Shadow / Policy change.",
            "No dividend credited to any portfolio.",
        ],
    }


def write_audit_artifact(
    report: dict[str, Any], out_dir: Path = DEFAULT_ARTIFACT_DIR
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    path = out_dir / f"source_audit_{stamp}.json"
    path.write_text(payload, encoding="utf-8")
    (out_dir / "source_audit_latest.json").write_text(payload, encoding="utf-8")
    return path


def run_source_audit(
    session: Session,
    *,
    artifact_dir: Path | None = DEFAULT_ARTIFACT_DIR,
) -> dict[str, Any]:
    """Build the report, optionally persist an artifact, and record an ingestion run."""
    report = build_source_audit_report()
    if artifact_dir is not None:
        report["artifact_path"] = str(write_audit_artifact(report, artifact_dir))
    if fundamentals_schema_ready(session):
        run = start_run(session, PROVIDER_SOURCE_AUDIT, requested_range=AUDIT_DATE.isoformat())
        finish_run(session, run, status=IngestionStatus.SUCCESS, summary=report)
        report["run_id"] = run.id
    else:
        report["run_id"] = None
        report["schema_ready"] = False
    return report
