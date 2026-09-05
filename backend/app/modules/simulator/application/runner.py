"""Orchestrate Historical Simulator V0 / Policy-Risk V1 research runs."""

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
    policy_name: str | None = None,
    risk_name: str | None = None,
    candidate_name: str | None = None,
    candidate_version: str | None = None,
    **policy_risk_kwargs: Any,
) -> SimulationSpecV0:
    kwargs: dict[str, Any] = {
        "segment": segment,
        "candidate_name": candidate_name or CANDIDATE_V0_CONFIG.candidate_name,
        "candidate_version": candidate_version or CANDIDATE_V0_CONFIG.candidate_version,
        "candidate_config_hash": candidate_config_hash,
        "dataset_values_hash": dataset_values_hash,
        "prediction_hash": prediction_hash,
        "commission_bps": commission_bps,
        "slippage_bps": slippage_bps,
        "cost_sensitivity_label": cost_sensitivity_label,
    }
    if policy_name is not None:
        kwargs["policy_name"] = policy_name
    if risk_name is not None:
        kwargs["risk_name"] = risk_name
    kwargs.update(policy_risk_kwargs)
    return SimulationSpecV0(**kwargs)


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
    policy_name: str | None = None,
    risk_name: str | None = None,
    candidate_name: str | None = None,
    candidate_version: str | None = None,
    config_hash: str | None = None,
    **policy_risk_kwargs: Any,
) -> tuple[SimulationResult, int | None]:
    bundle = load_oos_predictions(
        segment,
        artifact_dir=artifact_dir,
        candidate_name=candidate_name,
        candidate_version=candidate_version,
        config_hash=config_hash,
    )
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
        policy_name=policy_name,
        risk_name=risk_name,
        candidate_name=bundle.candidate_name,
        candidate_version=bundle.candidate_version,
        **policy_risk_kwargs,
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
