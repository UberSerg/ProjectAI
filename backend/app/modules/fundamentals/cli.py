"""CLI for Fundamental & Event Intelligence V1.

Only identity and corporate events can actually be populated today. `backfill` therefore
means identity + events; report and dividend ingestion deliberately record a DEFERRED run
instead of inventing data.

    python -m app.modules.fundamentals.cli audit
    python -m app.modules.fundamentals.cli sync-identity [--symbols SBER,GAZP] [--dry-run]
    python -m app.modules.fundamentals.cli sync-events
    python -m app.modules.fundamentals.cli status
    python -m app.modules.fundamentals.cli providers
    python -m app.modules.fundamentals.cli backfill
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.infrastructure.db.session import core_session
from app.modules.fundamentals.application.audit import run_source_audit
from app.modules.fundamentals.application.corporate_events_sync import sync_corporate_events
from app.modules.fundamentals.application.identity import sync_issuer_identity
from app.modules.fundamentals.application.ingest_dividends import run_dividend_ingestion
from app.modules.fundamentals.application.ingest_reports import run_report_ingestion
from app.modules.fundamentals.application.metric_registry import ensure_metric_registry
from app.modules.fundamentals.application.providers_matrix import build_providers_matrix
from app.modules.fundamentals.application.quality import run_quality_checks
from app.modules.fundamentals.application.read_models import status_payload
from app.modules.fundamentals.application.readiness import build_readiness_report
from app.modules.fundamentals.config import DEFAULT_ARTIFACT_DIR
from app.modules.fundamentals.infrastructure.moex_issuer_provider import (
    MoexIssuerIdentityProvider,
)


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _symbols(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [part.strip().upper() for part in raw.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fundamental & Event Intelligence V1 — issuer identity, corporate events, "
            "source audit and PIT status. Never scrapes and never invents data."
        )
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    audit_p = sub.add_parser("audit", help="Print/persist the source audit verdicts")
    audit_p.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    audit_p.add_argument("--no-artifact", action="store_true")

    identity_p = sub.add_parser("sync-identity", help="Sync issuers + mappings from MOEX ISS")
    identity_p.add_argument("--symbols", type=str, default=None)
    identity_p.add_argument(
        "--dry-run", action="store_true", help="Roll back instead of committing"
    )

    events_p = sub.add_parser(
        "sync-events", help="Project market.corporate_actions SPLIT events (idempotent)"
    )
    events_p.add_argument("--dry-run", action="store_true")

    sub.add_parser("status", help="Coverage, readiness, quality and recent runs")

    sub.add_parser("providers", help="Provider matrix: configured, reachable, PIT capability")

    backfill_p = sub.add_parser(
        "backfill",
        help="identity + events; reports/dividends are recorded DEFERRED (no provider)",
    )
    backfill_p.add_argument("--symbols", type=str, default=None)

    args = parser.parse_args(argv)

    with core_session() as session:
        if args.cmd == "audit":
            payload = run_source_audit(
                session, artifact_dir=None if args.no_artifact else args.artifact_dir
            )
            session.commit()
            _print(payload)
        elif args.cmd == "sync-identity":
            ensure_metric_registry(session)
            result = sync_issuer_identity(
                session, MoexIssuerIdentityProvider(), symbols=_symbols(args.symbols)
            )
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
            _print({**result.to_dict(), "dry_run": bool(args.dry_run)})
        elif args.cmd == "sync-events":
            result = sync_corporate_events(session)
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
            _print({**result.to_dict(), "dry_run": bool(args.dry_run)})
        elif args.cmd == "status":
            _print(
                {
                    "status": status_payload(session),
                    "readiness": build_readiness_report(session),
                    "quality": run_quality_checks(session),
                }
            )
        elif args.cmd == "providers":
            _print(build_providers_matrix(live=False))
        elif args.cmd == "backfill":
            payload: dict[str, Any] = {"metric_registry": ensure_metric_registry(session)}
            payload["identity"] = sync_issuer_identity(
                session, MoexIssuerIdentityProvider(), symbols=_symbols(args.symbols)
            ).to_dict()
            payload["events"] = sync_corporate_events(session).to_dict()
            payload["reports"] = run_report_ingestion(session).to_dict()
            payload["dividends"] = run_dividend_ingestion(session).to_dict()
            session.commit()
            payload["readiness"] = build_readiness_report(session)
            _print(payload)
        else:  # pragma: no cover - argparse enforces the choices
            parser.error(f"unknown command {args.cmd}")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
