"""CLI: IntelligenceRefreshV1 — OWNER manual refresh (no aggressive polling).

  python -m app.modules.intelligence.operations.cli run
  python -m app.modules.intelligence.operations.cli run --force
  python -m app.modules.intelligence.operations.cli run --dry-run
  python -m app.modules.intelligence.operations.cli run --instruments 1,2,3 --as-of 2026-10-07
  python -m app.modules.intelligence.operations.cli status
"""

from __future__ import annotations

import argparse
import json
import sys

from app.infrastructure.db.session import core_session
from app.modules.intelligence.operations.refresh import run_intelligence_refresh
from app.modules.intelligence.operations.status import build_operational_status


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _instrument_ids(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="IntelligenceRefreshV1 — OWNER manual intelligence stack refresh"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run one end-to-end intelligence refresh")
    run_p.add_argument("--instruments", type=str, default=None, help="Comma-separated instrument ids")
    run_p.add_argument("--as-of", type=str, default=None, dest="as_of", help="Optional as_of date ISO")
    run_p.add_argument(
        "--force",
        action="store_true",
        help="Skip idempotent short-circuit for identical fingerprint",
    )
    run_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Persist a dry-run run without executing stage hooks",
    )

    sub.add_parser("status", help="Show stage status / source health / last success")

    args = parser.parse_args(argv)

    with core_session() as session:
        if args.command == "status":
            _print(build_operational_status(session))
            return 0

        result = run_intelligence_refresh(
            session,
            instrument_ids=_instrument_ids(args.instruments),
            as_of=args.as_of,
            force=bool(args.force),
            dry_run=bool(args.dry_run),
        )
        _print(result)
        return 0 if result.get("status") in {"SUCCESS", "NO_CHANGES", "WARNING", "BLOCKED"} else 1


if __name__ == "__main__":
    sys.exit(main())
