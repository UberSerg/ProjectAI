"""CLI: offline Prediction ML Candidate V0 (smoke or full)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.infrastructure.db.session import core_session
from app.modules.prediction.application.runner import run_candidate_v0
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prediction ML Candidate V0 offline trainer")
    parser.add_argument("--smoke", action="store_true", help="Bounded single-fold smoke run")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="Override MODELS_DATA_PATH root",
    )
    args = parser.parse_args(argv)
    with core_session() as session:
        result = run_candidate_v0(
            session,
            config=CANDIDATE_V0_CONFIG,
            artifact_root=args.artifact_root,
            smoke=args.smoke,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
