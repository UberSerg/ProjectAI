"""CLI for Historical Simulator V0 / Policy-Risk V1 research."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.infrastructure.db.session import core_session
from app.modules.simulator.application.engine import result_summary
from app.modules.simulator.application.predictions import load_oos_predictions, prediction_date_bounds
from app.modules.simulator.application.runner import run_segment, smoke_window_bounds
from app.modules.simulator.config import (
    POLICY_NAME,
    RISK_NAME,
    hysteresis_dd_v1_spec_kwargs,
    hysteresis_v1_spec_kwargs,
)


def _policy_kwargs(variant: str) -> dict:
    if variant == "V0":
        return {"policy_name": POLICY_NAME, "risk_name": RISK_NAME}
    if variant == "HYST":
        return hysteresis_v1_spec_kwargs()
    if variant == "HYST_DD":
        return hysteresis_dd_v1_spec_kwargs()
    raise ValueError(f"unknown variant: {variant}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Historical Simulator V0 / Policy-Risk V1")
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
    parser.add_argument(
        "--variant",
        choices=["V0", "HYST", "HYST_DD"],
        default="V0",
        help="Policy/risk research variant (default V0 baseline)",
    )
    parser.add_argument("--date-from", type=str, default=None)
    parser.add_argument("--date-to", type=str, default=None)
    args = parser.parse_args()

    from datetime import date as date_cls

    date_from = date_cls.fromisoformat(args.date_from) if args.date_from else None
    date_to = date_cls.fromisoformat(args.date_to) if args.date_to else None
    variant_kwargs = _policy_kwargs(args.variant)

    t0 = time.perf_counter()
    with core_session() as session:
        if args.segment == "SMOKE":
            bundle = load_oos_predictions("DEVELOPMENT_OOS", artifact_dir=args.artifact_dir)
            d0, d1 = prediction_date_bounds(bundle)
            start, end = smoke_window_bounds(d0, d1)
            if date_from is not None:
                start = date_from
            if date_to is not None:
                end = date_to
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
                **variant_kwargs,
            )
        else:
            result, run_id = run_segment(
                session,
                args.segment,
                artifact_dir=args.artifact_dir,
                date_from=date_from,
                date_to=date_to,
                commission_bps=args.commission_bps,
                slippage_bps=args.slippage_bps,
                cost_sensitivity_label=args.cost_label,
                persist=not args.no_persist,
                **variant_kwargs,
            )
        summary = result_summary(result)
        summary["run_id"] = run_id
        summary["variant"] = args.variant
        summary["runtime_sec"] = round(time.perf_counter() - t0, 3)
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
