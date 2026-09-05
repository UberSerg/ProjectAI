"""CLI: offline Prediction Candidate V1 Ranker (smoke or full DEVELOPMENT)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.infrastructure.db.session import core_session
from app.modules.prediction.application.runner_v1 import run_candidate_v1_ranker
from app.modules.prediction.candidate_v1_config import CANDIDATE_V1_RANKER_CONFIG


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prediction Candidate V1 Ranker (DEV only)")
    parser.add_argument("--smoke", action="store_true", help="Bounded single-fold smoke run")
    parser.add_argument("--artifact-root", type=Path, default=None)
    args = parser.parse_args(argv)
    with core_session() as session:
        result = run_candidate_v1_ranker(
            session,
            config=CANDIDATE_V1_RANKER_CONFIG,
            artifact_root=args.artifact_root,
            smoke=args.smoke,
        )
        session.commit()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
