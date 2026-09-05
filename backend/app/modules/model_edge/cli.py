"""CLI for Prospective Model A/B V0 and Model Diagnostics V0."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.infrastructure.db.session import core_session
from app.modules.model_edge.application.diagnostics import load_diagnostics_from_file
from app.modules.model_edge.application.experiment import activate_experiment
from app.modules.model_edge.application.paired_forward import run_paired_forward
from app.modules.model_edge.application.paired_outcome import evaluate_paired_outcomes
from app.modules.model_edge.application.read_models import prospective_latest
from app.modules.shadow.application.service import advance_all_shadow_portfolios
from app.modules.shadow.config import MODEL_AB_EXPERIMENT_GROUP as SHADOW_AB_GROUP


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Model Edge Research Pack V0")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("activate", help="Activate PROSPECTIVE_MODEL_AB_V0 (no backfill)")
    sub.add_parser("status", help="Experiment + portfolio status")
    sub.add_parser("paired-forward", help="Run paired V0/V1 forward for latest eligible as_of")
    sub.add_parser("paired-shadow", help="Advance MODEL_AB shadow portfolios only")
    sub.add_parser("paired-outcome", help="Evaluate paired outcomes")
    diag = sub.add_parser("load-diagnostics", help="Persist diagnostics JSON artifact")
    diag.add_argument("path", type=Path)

    args = parser.parse_args(argv)

    with core_session() as session:
        if args.cmd == "activate":
            result = activate_experiment(session)
            session.commit()
            _print(result)
            return 0
        if args.cmd == "status":
            _print(prospective_latest(session))
            return 0
        if args.cmd == "paired-forward":
            result = run_paired_forward(session, persist=True)
            session.commit()
            _print(result.to_dict())
            return 0 if result.status not in {"ERROR"} else 1
        if args.cmd == "paired-shadow":
            results = advance_all_shadow_portfolios(
                session, experiment_groups=[SHADOW_AB_GROUP]
            )
            session.commit()
            _print(
                [
                    {"portfolio_id": r.portfolio_id, "name": r.name, "status": r.status, **r.summary}
                    for r in results
                ]
            )
            return 0
        if args.cmd == "paired-outcome":
            result = evaluate_paired_outcomes(session)
            session.commit()
            _print(result.to_dict())
            return 0
        if args.cmd == "load-diagnostics":
            row = load_diagnostics_from_file(session, args.path)
            session.commit()
            _print(
                {
                    "status": "SUCCESS",
                    "id": row.id,
                    "input_hash": row.input_hash,
                    "period_from": row.period_from,
                    "period_to": row.period_to,
                }
            )
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
