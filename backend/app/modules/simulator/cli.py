"""CLI for Historical Simulator V0."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.infrastructure.db.session import core_session
from app.modules.simulator.application.engine import result_summary
from app.modules.simulator.application.predictions import load_oos_predictions, prediction_date_bounds
from app.modules.simulator.application.runner import run_segment, smoke_window_bounds


def main() -> None:
    parser = argparse.ArgumentParser(description="Historical Simulator V0")
    parser.add_argument(
        "--segment",
        choices=["DEVELOPMENT_OOS", "FINAL_HOLDOUT", "SMOKE"],
        required=True,
    )
    parser.add_argument("--commission-bps", type=float, default=0.0)
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--artifact-dir", type=Path, default=None)
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--cost-label", type=str, default=None)
    args = parser.parse_args()

    t0 = time.perf_counter()
    with core_session() as session:
        if args.segment == "SMOKE":
            bundle = load_oos_predictions("DEVELOPMENT_OOS", artifact_dir=args.artifact_dir)
            d0, d1 = prediction_date_bounds(bundle)
            start, end = smoke_window_bounds(d0, d1)
            result, run_id = run_segment(
                session,
                "DEVELOPMENT_OOS",
                artifact_dir=args.artifact_dir,
                date_from=start,
                date_to=end,
                commission_bps=args.commission_bps,
                slippage_bps=args.slippage_bps,
                cost_sensitivity_label=args.cost_label,
                persist=not args.no_persist,
            )
        else:
            result, run_id = run_segment(
                session,
                args.segment,
                artifact_dir=args.artifact_dir,
                commission_bps=args.commission_bps,
                slippage_bps=args.slippage_bps,
                cost_sensitivity_label=args.cost_label,
                persist=not args.no_persist,
            )
        summary = result_summary(result)
        summary["run_id"] = run_id
        summary["runtime_sec"] = round(time.perf_counter() - t0, 3)
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
