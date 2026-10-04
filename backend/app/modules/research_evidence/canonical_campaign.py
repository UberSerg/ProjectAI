"""CLI for Canonical Evidence Campaign V1 — resume/start, never Candidate promotion.

Usage:
  python -m app.modules.research_evidence.canonical_campaign --prepare-only
  python -m app.modules.research_evidence.canonical_campaign --resume
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

NIGHT_WORKFLOW_ID = "live-canonical-v1-20261003-retry-specs"


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Canonical Evidence Campaign V1")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Run or resume CanonicalEvidenceCampaignV1 (long historical stages).",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Verify specs and mark stale RUNNING v3/v4 campaign builds. Do not build.",
    )
    parser.add_argument("--workflow-id", default=NIGHT_WORKFLOW_ID)
    parser.add_argument("--exact-rerun", action="store_true")
    args = parser.parse_args(argv)
    if not args.resume and not args.prepare_only:
        parser.error("pass --prepare-only or --resume")
    if args.resume and args.prepare_only:
        parser.error("use either --prepare-only or --resume")

    from app.infrastructure.db.session import core_session, memory_session
    from app.modules.learning.dataset_config import PIT_DAILY_CORE_ACTIVE_VERSION
    from app.modules.prediction.candidate_config import CandidateV0Config
    from app.modules.prediction.candidate_v1_config import CandidateV1RankerConfig
    from app.modules.research_evidence.campaign_recovery import (
        INTERRUPT_REASON,
        interrupt_stale_campaign_dataset_builds,
        verify_research_specs,
    )
    from app.modules.research_evidence.campaign_runner import run_canonical_evidence_campaign_v1
    from app.modules.research_evidence.paths import campaign_runtime_dir, research_evidence_root

    if PIT_DAILY_CORE_ACTIVE_VERSION != 1:
        raise SystemExit("PIT_DAILY_CORE_ACTIVE_VERSION must remain 1")
    if CandidateV0Config().dataset_spec_version != 2:
        raise SystemExit("Candidate V0 must remain DatasetSpec 2")
    if CandidateV1RankerConfig().dataset_spec_version != 2:
        raise SystemExit("Candidate V1 must remain DatasetSpec 2")

    with core_session() as session:
        specs = verify_research_specs(session)
        interrupted = interrupt_stale_campaign_dataset_builds(session)
        session.commit()
    _print(
        {
            "mode": "prepare-only" if args.prepare_only else "resume",
            "specs": specs,
            "interrupted_stale_runs": interrupted,
            "interrupt_reason": INTERRUPT_REASON,
            "persist_registry": False,
            "research_only": True,
        }
    )
    if args.prepare_only:
        return 0

    def _hook(name: str, status: str, error: str | None = None) -> None:
        extra = f" error={error}" if error else ""
        print(f"STAGE {name} {status}{extra}", flush=True)

    with core_session() as core, memory_session() as memory:
        result = run_canonical_evidence_campaign_v1(
            core,
            memory,
            workflow_id=args.workflow_id,
            exact_rerun=bool(args.exact_rerun),
            persist_registry=False,
            step_hook=_hook,
        )
    _print(result)
    runtime = campaign_runtime_dir(args.workflow_id)
    print(f"RUNTIME_DIR {runtime}", flush=True)
    print(f"ARTIFACT_ROOT {research_evidence_root()}", flush=True)
    status_path = Path(result.get("artifact_dir") or runtime) / "execution.json"
    if status_path.is_file():
        print(f"EXECUTION {status_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
