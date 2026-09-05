"""Economic viability of a model against the fixed cash hurdle.

The matrix is a reporting layer over Research Lab / Simulator runs. It never re-runs a
configuration that already exists, and it never writes hurdle interest into any portfolio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.modules.model_edge.application.cash_hurdle import compute_cash_hurdle
from app.modules.model_edge.config import (
    CASH_HURDLE_ANNUAL_RATE,
    ECONOMIC_COST_GRID_BPS,
    INITIAL_CAPITAL,
    SHADOW_POLICY_NAME,
    SHADOW_RISK_NAME,
    VIABILITY_CLEARLY_ABOVE,
    VIABILITY_CLEARLY_BELOW,
)
from app.modules.model_edge.domain.types import CashHurdle, ViabilityLabel
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
from app.modules.prediction.candidate_v1_config import CANDIDATE_V1_RANKER_CONFIG
from app.modules.research_lab.application.service import launch_research_run
from app.modules.research_lab.catalog import ALLOWED_RESEARCH_SEGMENT


@dataclass(frozen=True, slots=True)
class EconomicCell:
    candidate_id: str
    candidate_version: str
    commission_bps: float
    run_id: int | None
    status: str
    date_from: date | None
    date_to: date | None
    total_price_return: float | None
    max_drawdown: float | None
    hurdle: CashHurdle | None
    excess_vs_cash: float | None
    viability: ViabilityLabel
    reused: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_version": self.candidate_version,
            "commission_bps": self.commission_bps,
            "run_id": self.run_id,
            "status": self.status,
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "total_price_return": self.total_price_return,
            "max_drawdown": self.max_drawdown,
            "cash_hurdle": self.hurdle.to_dict() if self.hurdle else None,
            "excess_vs_cash": self.excess_vs_cash,
            "viability": self.viability,
            "reused": self.reused,
            "error": self.error,
        }


def viability_label(excess: float | None) -> ViabilityLabel:
    """Coarse three-way verdict; the inconclusive band avoids over-reading small gaps."""
    if excess is None:
        return "INSUFFICIENT_DATA"
    if excess >= VIABILITY_CLEARLY_ABOVE:
        return "ABOVE_CASH_HURDLE"
    if excess <= VIABILITY_CLEARLY_BELOW:
        return "BELOW_CASH_HURDLE"
    return "INCONCLUSIVE_VS_CASH_HURDLE"


def excess_over_cash_hurdle(
    total_return: float | None,
    period_from: date | None,
    period_to: date | None,
    *,
    annual_rate: float = CASH_HURDLE_ANNUAL_RATE,
) -> tuple[CashHurdle | None, float | None]:
    if total_return is None or period_from is None or period_to is None:
        return None, None
    hurdle = compute_cash_hurdle(period_from, period_to, annual_rate=annual_rate)
    return hurdle, float(total_return) - hurdle.hurdle_return


def _candidate_ids() -> list[tuple[str, str]]:
    return [
        (
            f"{CANDIDATE_V0_CONFIG.candidate_name}/{CANDIDATE_V0_CONFIG.candidate_version}",
            CANDIDATE_V0_CONFIG.candidate_version,
        ),
        (
            f"{CANDIDATE_V1_RANKER_CONFIG.candidate_name}/"
            f"{CANDIDATE_V1_RANKER_CONFIG.candidate_version}",
            CANDIDATE_V1_RANKER_CONFIG.candidate_version,
        ),
    ]


def _parse_iso(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def build_economic_matrix(
    session: Session,
    *,
    costs_bps: tuple[float, ...] = ECONOMIC_COST_GRID_BPS,
    annual_rate: float = CASH_HURDLE_ANNUAL_RATE,
    initial_capital: float = INITIAL_CAPITAL,
    date_from: date | None = None,
    date_to: date | None = None,
    compute_missing: bool = True,
) -> dict[str, Any]:
    """Candidate × cost grid measured against the cash hurdle over the same window."""
    cells: list[EconomicCell] = []
    for candidate_id, version in _candidate_ids():
        for bps in costs_bps:
            request = {
                "candidate_id": candidate_id,
                "segment": ALLOWED_RESEARCH_SEGMENT,
                "policy_id": SHADOW_POLICY_NAME,
                "risk_id": SHADOW_RISK_NAME,
                "commission_bps": bps,
                "initial_capital": initial_capital,
                "force_rerun": False,
            }
            if date_from is not None:
                request["date_from"] = date_from.isoformat()
            if date_to is not None:
                request["date_to"] = date_to.isoformat()

            if not compute_missing:
                request["force_rerun"] = False
            try:
                outcome = launch_research_run(session, request)
            except Exception as exc:  # noqa: BLE001 — a missing artifact is a reportable cell
                cells.append(
                    EconomicCell(
                        candidate_id=candidate_id,
                        candidate_version=version,
                        commission_bps=bps,
                        run_id=None,
                        status="ERROR",
                        date_from=None,
                        date_to=None,
                        total_price_return=None,
                        max_drawdown=None,
                        hurdle=None,
                        excess_vs_cash=None,
                        viability="INSUFFICIENT_DATA",
                        reused=False,
                        error=str(exc)[:2000],
                    )
                )
                continue

            run = outcome.get("run") or {}
            metrics = run.get("metrics") or {}
            d0 = _parse_iso(run.get("date_from"))
            d1 = _parse_iso(run.get("date_to"))
            total_return = metrics.get("total_price_return")
            hurdle, excess = excess_over_cash_hurdle(
                total_return, d0, d1, annual_rate=annual_rate
            )
            cells.append(
                EconomicCell(
                    candidate_id=candidate_id,
                    candidate_version=version,
                    commission_bps=bps,
                    run_id=run.get("id"),
                    status=str(outcome.get("status") or "UNKNOWN"),
                    date_from=d0,
                    date_to=d1,
                    total_price_return=(
                        float(total_return) if total_return is not None else None
                    ),
                    max_drawdown=metrics.get("max_drawdown"),
                    hurdle=hurdle,
                    excess_vs_cash=excess,
                    viability=viability_label(excess),
                    reused=outcome.get("outcome") == "REUSE_EXISTING",
                )
            )

    return {
        "segment": ALLOWED_RESEARCH_SEGMENT,
        "policy_id": SHADOW_POLICY_NAME,
        "risk_id": SHADOW_RISK_NAME,
        "initial_capital": initial_capital,
        "cash_hurdle_annual_rate": annual_rate,
        "cash_hurdle_mutates_portfolio": False,
        "costs_bps": list(costs_bps),
        "cells": [c.to_dict() for c in cells],
        "note": (
            "Historical DEVELOPMENT_OOS research. Survivorship bias present; the cash "
            "hurdle is a post-hoc benchmark and never credited to portfolio cash."
        ),
    }
