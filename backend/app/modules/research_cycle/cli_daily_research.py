"""CLI: Daily Research Cycle V0."""

from __future__ import annotations

import argparse
import json
import sys

from app.infrastructure.db.session import core_session
from app.modules.research_cycle.cycle import run_daily_research_cycle
from app.modules.research_cycle.watermarks import build_operational_status, latest_cycle_workflow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily Research Cycle V0 — prospective forward ops loop")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="Run one end-to-end cycle")
    sub.add_parser("status", help="Show operational status / latest run")
    args = parser.parse_args(argv)

    with core_session() as session:
        if args.command == "status":
            payload = build_operational_status(session)
            latest = latest_cycle_workflow(session)
            if latest is not None:
                payload["latest_workflow_id"] = latest.id
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            return 0

        result = run_daily_research_cycle(session)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("status") in {"SUCCESS", "NO_CHANGES", "BLOCKED"} else 1


if __name__ == "__main__":
    sys.exit(main())
