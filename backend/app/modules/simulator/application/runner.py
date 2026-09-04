"""Orchestrate Historical Simulator V0 runs."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
from app.modules.simulator.application.engine import SimulationResult, run_simulation
from app.modules.simulator.application.market_view import load_market_view
from app.modules.simulator.application.predictions import (
    load_oos_predictions,
    prediction_date_bounds,
    summarize_bundle,
)
from app.modules.simulator.config import SimulationSegment, SimulationSpecV0
from app.modules.simulator.infrastructure.repository import persist_simulation_result


def build_spec(
    segment: SimulationSegment,
    *,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
    cost_sensitivity_label: str | None = None,
    prediction_hash: str,
    candidate_config_hash: str,
    dataset_values_hash: str,
) -> SimulationSpecV0:
    return SimulationSpecV0(
        segment=segment,
        candidate_name=CANDIDATE_V0_CONFIG.candidate_name,
        candidate_version=CANDIDATE_V0_CONFIG.candidate_version,
        candidate_config_hash=candidate_config_hash,
        dataset_values_hash=dataset_values_hash,
        prediction_hash=prediction_hash,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        cost_sensitivity_label=cost_sensitivity_label,
    )


def run_segment(
    session: Session,
    segment: SimulationSegment,
    *,
    artifact_dir: Path | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
    cost_sensitivity_label: str | None = None,
    persist: bool = True,
) -> tuple[SimulationResult, int | None]:
    bundle = load_oos_predictions(segment, artifact_dir=artifact_dir)
    d0, d1 = prediction_date_bounds(bundle)
    # Market window: pad for next-open after last prediction
    market_from = date_from or (d0 - timedelta(days=5))
    market_to = date_to or (d1 + timedelta(days=14))
    instrument_ids = set(int(x) for x in bundle.frame["instrument_id"].unique())
    market = load_market_view(
        session,
        instrument_ids=instrument_ids,
        date_from=market_from,
        date_to=market_to,
    )
    spec = build_spec(
        segment,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        cost_sensitivity_label=cost_sensitivity_label,
        prediction_hash=bundle.prediction_hash,
        candidate_config_hash=bundle.candidate_config_hash,
        dataset_values_hash=bundle.dataset_values_hash,
    )
    result = run_simulation(
        spec=spec,
        bundle=bundle,
        market=market,
        date_from=date_from,
        date_to=date_to,
    )
    run_id = None
    if persist:
        run = persist_simulation_result(session, result)
        session.flush()
        run_id = run.id
    return result, run_id


def smoke_window_bounds(bundle_date_from: date, bundle_date_to: date) -> tuple[date, date]:
    """~3–6 month smoke window near the end of available predictions."""
    end = bundle_date_to
    start = max(bundle_date_from, end - timedelta(days=120))
    return start, end


def describe_ready(artifact_dir: Path | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for segment in ("DEVELOPMENT_OOS", "FINAL_HOLDOUT"):
        try:
            bundle = load_oos_predictions(segment, artifact_dir=artifact_dir)  # type: ignore[arg-type]
            out[segment] = summarize_bundle(bundle)
        except Exception as exc:  # noqa: BLE001 — readiness probe
            out[segment] = {"error": str(exc)}
    return out
