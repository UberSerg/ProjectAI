"""CLI for Fundamental & Event Intelligence + FNS RAS sync.

    python -m app.modules.fundamentals.cli audit
    python -m app.modules.fundamentals.cli sync-identity [--symbols SBER,GAZP]
    python -m app.modules.fundamentals.cli sync-events
    python -m app.modules.fundamentals.cli sync-fns [--symbols LKOH,GAZP] [--dry-run]
    python -m app.modules.fundamentals.cli status
    python -m app.modules.fundamentals.cli coverage
    python -m app.modules.fundamentals.cli dataset-v3-gate
    python -m app.modules.fundamentals.cli backfill
"""

from __future__ import annotationsimport argparseimport jsonimport sysfrom pathlib import Pathfrom typing import Anyfrom app.infrastructure.db.session import core_sessionfrom app.modules.fundamentals.application.audit import run_source_auditfrom app.modules.fundamentals.application.corporate_events_sync import sync_corporate_eventsfrom app.modules.fundamentals.application.coverage_service import FundamentalCoverageServicefrom app.modules.fundamentals.application.dataset_v3_gate import build_dataset_v3_readiness_gatefrom app.modules.fundamentals.application.identity import sync_issuer_identityfrom app.modules.fundamentals.application.ingest_dividends import run_dividend_ingestionfrom app.modules.fundamentals.application.ingest_reports import run_report_ingestionfrom app.modules.fundamentals.application.metric_registry import ensure_metric_registryfrom app.modules.fundamentals.application.quality import run_quality_checksfrom app.modules.fundamentals.application.read_models import status_payloadfrom app.modules.fundamentals.application.readiness import build_readiness_reportfrom app.modules.fundamentals.application.sync_fundamentals_fns import sync_fundamentals_fnsfrom app.modules.fundamentals.config import DEFAULT_ARTIFACT_DIR, FNS_ARTIFACT_DIRfrom app.modules.fundamentals.infrastructure.moex_issuer_provider import (    MoexIssuerIdentityProvider,)def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _symbols(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [part.strip().upper() for part in raw.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fundamental & Event Intelligence — identity, FNS RAS sync, corporate events, "
            "source audit and PIT status."
        )
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    audit_p = sub.add_parser("audit", help="Print/persist the source audit verdicts")
    audit_p.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    audit_p.add_argument("--no-artifact", action="store_true")

    identity_p = sub.add_parser("sync-identity", help="Sync issuers + mappings from MOEX ISS")
    identity_p.add_argument("--symbols", type=str, default=None)
    identity_p.add_argument("--dry-run", action="store_true")

    events_p = sub.add_parser("sync-events", help="Project market.corporate_actions SPLIT events")
    events_p.add_argument("--dry-run", action="store_true")

    fns_p = sub.add_parser("sync-fns", help="Sync industrial RAS reports from FNS GIR BO")
    fns_p.add_argument("--symbols", type=str, default=None)
    fns_p.add_argument("--dry-run", action="store_true")
    fns_p.add_argument("--max-issuers", type=int, default=None)

    sub.add_parser("status", help="Coverage, readiness, quality and recent runs")
    sub.add_parser("coverage", help="Research cohort fundamental coverage table")
    sub.add_parser("dataset-v3-gate", help="Dataset V3 readiness gate (no Dataset creation)")

    backfill_p = sub.add_parser(
        "backfill",
        help="identity + events + FNS RAS; dividends stay DEFERRED without provider",
    )
    backfill_p.add_argument("--symbols", type=str, default=None)
    backfill_p.add_argument("--skip-fns", action="store_true")

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
        elif args.cmd == "sync-fns":
            ensure_metric_registry(session)
            result = sync_fundamentals_fns(
                session,
                symbols=_symbols(args.symbols),
                max_issuers=args.max_issuers,
            )
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
                    "dataset_v3_gate": build_dataset_v3_readiness_gate(session),
                }
            )
        elif args.cmd == "coverage":
            table = FundamentalCoverageService(session).cohort_table()
            FNS_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
            path = FNS_ARTIFACT_DIR / "fundamental-coverage.json"
            path.write_text(
                json.dumps(table, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
            _print({**table, "artifact_path": str(path)})
        elif args.cmd == "dataset-v3-gate":
            gate = build_dataset_v3_readiness_gate(session)
            FNS_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
            path = FNS_ARTIFACT_DIR / "dataset-v3-readiness.json"
            path.write_text(
                json.dumps(gate, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
            _print({**gate, "artifact_path": str(path)})
        elif args.cmd == "backfill":
            payload: dict[str, Any] = {"metric_registry": ensure_metric_registry(session)}
            payload["identity"] = sync_issuer_identity(
                session, MoexIssuerIdentityProvider(), symbols=_symbols(args.symbols)
            ).to_dict()
            payload["events"] = sync_corporate_events(session).to_dict()
            if args.skip_fns:
                payload["reports"] = run_report_ingestion(session).to_dict()
            else:
                payload["fns"] = sync_fundamentals_fns(
                    session, symbols=_symbols(args.symbols)
                ).to_dict()
            payload["dividends"] = run_dividend_ingestion(session).to_dict()
            session.commit()
            payload["readiness"] = build_readiness_report(session)
            payload["dataset_v3_gate"] = build_dataset_v3_readiness_gate(session)
            _print(payload)
        else:  # pragma: no cover
            parser.error(f"unknown command {args.cmd}")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
