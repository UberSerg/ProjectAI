"""CLI for External Deep History V0.

Default operation is AUDIT ONLY. Staging ingest requires an explicit ``ingest``
command. Nothing here writes to market.candles.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.infrastructure.db.session import core_session
from app.modules.market_history.application.pipeline import (
    run_audit,
    run_curate,
    run_ingest,
    run_reconcile,
    run_status,
)
from app.modules.market_history.application.report import DEFAULT_ARTIFACT_DIR


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "External Deep History V0 — audit / stage / reconcile an untrusted "
            "long-history CSV. Default is audit-only; never mutates market.candles."
        )
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    audit_p = sub.add_parser("audit", help="Profile CSV + register provenance (no candle ingest)")
    audit_p.add_argument("path", type=Path)
    audit_p.add_argument("--limit", type=int, default=None)
    audit_p.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)

    ingest_p = sub.add_parser("ingest", help="Bulk-stage OHLCV into market.external_candles_daily")
    ingest_p.add_argument("path", type=Path)
    ingest_p.add_argument("--batch-rows", type=int, default=50_000)
    ingest_p.add_argument("--limit", type=int, default=None)
    ingest_p.add_argument("--force", action="store_true")

    sub.add_parser("reconcile", help="Compare exact matches to MOEX RAW candles")
    curate_p = sub.add_parser("curate", help="Materialise research eligibility labels")
    curate_p.add_argument("--allow-unknown", action="store_true")
    sub.add_parser("status", help="Print staging status JSON")

    full_p = sub.add_parser(
        "full",
        help="audit → ingest → reconcile → curate (explicit; still never writes market.candles)",
    )
    full_p.add_argument("path", type=Path)
    full_p.add_argument("--batch-rows", type=int, default=50_000)
    full_p.add_argument("--force", action="store_true")
    full_p.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)

    args = parser.parse_args(argv)

    with core_session() as session:
        if args.cmd == "audit":
            result = run_audit(
                session, args.path, limit=args.limit, artifact_dir=args.artifact_dir
            )
            _print(result.to_dict())
        elif args.cmd == "ingest":
            result = run_ingest(
                session,
                args.path,
                batch_rows=args.batch_rows,
                limit=args.limit,
                force=args.force,
            )
            _print(result.to_dict())
        elif args.cmd == "reconcile":
            result = run_reconcile(session)
            _print(result.to_dict())
        elif args.cmd == "curate":
            result = run_curate(session, allow_unknown=args.allow_unknown)
            _print(result.to_dict())
        elif args.cmd == "status":
            _print(run_status(session))
        elif args.cmd == "full":
            payload: dict = {}
            payload["audit"] = run_audit(
                session, args.path, artifact_dir=args.artifact_dir
            ).to_dict()
            payload["ingest"] = run_ingest(
                session, args.path, batch_rows=args.batch_rows, force=args.force
            ).to_dict()
            payload["reconcile"] = run_reconcile(session).to_dict()
            payload["curate"] = run_curate(session).to_dict()
            payload["status"] = run_status(session)
            _print(payload)
        else:
            parser.error(f"unknown command {args.cmd}")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
