"""CLI: Dataset V2 vs V3 fair coverage comparison (research-only).

Examples:
  python -m app.modules.learning.cli_compare \\
    --date-from 2024-01-01 --date-to 2024-06-30 \\
    --out .tmp/brain-foundation-v2/v2-v3-evaluation.json

  python -m app.modules.learning.cli_compare \\
    --date-from 2024-01-01 --date-to 2024-06-30 \\
    --v2-run-id 10 --v3-run-id 11 --no-rebuild
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app.infrastructure.db.session import core_session
from app.modules.learning.application.compare_v2_v3 import (
    CompareContractError,
    compare_v2_v3_builds,
)


def _parse_ids(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fair Dataset V2 vs V3 coverage comparison (research-only, no ACTIVE switch)"
    )
    parser.add_argument("--date-from", type=date.fromisoformat, required=True)
    parser.add_argument("--date-to", type=date.fromisoformat, required=True)
    parser.add_argument("--instrument-ids", type=str, default=None)
    parser.add_argument("--v2-run-id", type=int, default=None)
    parser.add_argument("--v3-run-id", type=int, default=None)
    parser.add_argument(
        "--no-rebuild",
        action="store_true",
        help="Require --v2-run-id and --v3-run-id; do not run new builds",
    )
    parser.add_argument("--baseline-commit", type=str, default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(".tmp/brain-foundation-v2/v2-v3-evaluation.json"),
        help="Artifact path (default suitable for brain-foundation-v2 eval)",
    )
    args = parser.parse_args(argv)

    try:
        with core_session() as session:
            artifact = compare_v2_v3_builds(
                session,
                date_from=args.date_from,
                date_to=args.date_to,
                instrument_ids=_parse_ids(args.instrument_ids),
                baseline_commit=args.baseline_commit,
                v2_run_id=args.v2_run_id,
                v3_run_id=args.v3_run_id,
                rebuild=not args.no_rebuild,
            )
            session.commit()
    except CompareContractError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "written": str(args.out),
                "isolation_ok": artifact["active_dataset_spec"]["isolation_ok"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
