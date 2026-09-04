"""CLI: Forward Signal V0 — live PIT prediction for latest complete as_of."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app.infrastructure.db.session import core_session
from app.modules.prediction.application.forward_runner import run_forward_signal_v0
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Forward Signal V0 — immutable live PIT predictions (no retrain, no portfolio)"
    )
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="Explicit as_of date (YYYY-MM-DD). Default: latest complete market date.",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="Override MODELS_DATA_PATH root",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Run inference without writing DB rows",
    )
    args = parser.parse_args(argv)

    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    with core_session() as session:
        result = run_forward_signal_v0(
            session,
            as_of=as_of,
            config=CANDIDATE_V0_CONFIG,
            artifact_root=args.artifact_root,
            persist=not args.no_persist,
        )
        if result.status in {"SUCCESS", "NO_CHANGES"} and not args.no_persist:
            session.commit()
    payload = {
        "status": result.status,
        "batch_id": result.batch_id,
        "as_of": result.as_of.isoformat() if result.as_of else None,
        **result.summary,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0 if result.status in {"SUCCESS", "NO_CHANGES"} else 1


if __name__ == "__main__":
    sys.exit(main())
