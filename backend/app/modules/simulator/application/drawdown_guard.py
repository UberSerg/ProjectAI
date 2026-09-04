"""DRAWDOWN_GUARD_V1 — causal portfolio-state exposure cap."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from app.domain.ports.portfolio import PortfolioDecision
from app.domain.ports.risk import RiskDecision, RiskOutput
from app.modules.simulator.config import (
    RISK_DD_GUARD_V1,
    V1_DD_NORMAL_GROSS,
    V1_DD_RECOVERY,
    V1_DD_RISK_OFF_GROSS,
    V1_DD_TRIGGER,
)

RiskMode = Literal["normal", "risk_off"]


@dataclass
class DrawdownGuardState:
    mode: RiskMode = "normal"
    exposure_cap: float = V1_DD_NORMAL_GROSS
    events: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.events is None:
            self.events = []


def update_drawdown_guard(
    state: DrawdownGuardState,
    *,
    as_of: date,
    nav: float,
    peak_nav: float,
    drawdown: float,
    trigger: float = V1_DD_TRIGGER,
    recovery: float = V1_DD_RECOVERY,
    risk_off_gross: float = V1_DD_RISK_OFF_GROSS,
    normal_gross: float = V1_DD_NORMAL_GROSS,
) -> DrawdownGuardState:
    """Update guard using only information known at as_of (after MTM)."""
    prev_mode = state.mode
    prev_cap = state.exposure_cap
    mode = state.mode
    cap = state.exposure_cap
    reason: str | None = None

    if mode == "normal" and drawdown <= trigger + 1e-15:
        mode = "risk_off"
        cap = float(risk_off_gross)
        reason = "DD_GUARD_REDUCE"
    elif mode == "risk_off" and drawdown >= recovery - 1e-15:
        mode = "normal"
        cap = float(normal_gross)
        reason = "DD_GUARD_RECOVER"

    events = list(state.events or [])
    if reason is not None:
        events.append(
            {
                "date": as_of.isoformat(),
                "nav": nav,
                "running_peak": peak_nav,
                "drawdown": drawdown,
                "previous_mode": prev_mode,
                "new_mode": mode,
                "previous_exposure_cap": prev_cap,
                "new_exposure_cap": cap,
                "reason": reason,
                "risk": RISK_DD_GUARD_V1,
            }
        )
    return DrawdownGuardState(mode=mode, exposure_cap=cap, events=events)


def apply_exposure_cap(
    decisions: tuple[RiskDecision, ...] | tuple[PortfolioDecision, ...],
    *,
    exposure_cap: float,
    max_single_weight: float,
) -> RiskOutput:
    """Scale active target weights by exposure_cap; clamp single-name and gross."""
    scaled: list[RiskDecision] = []
    for d in decisions:
        meta = dict(getattr(d, "metadata", None) or {})
        blocked = bool(getattr(d, "blocked", False))
        block_reason = getattr(d, "block_reason", None)
        w = float(d.target_weight) * float(exposure_cap)
        if w > max_single_weight + 1e-12:
            meta["clamped_from"] = w
            w = max_single_weight
            meta["clamped"] = True
        if exposure_cap < 1.0 - 1e-12:
            meta["dd_guard_scaled"] = True
            meta["exposure_cap"] = exposure_cap
        scaled.append(
            RiskDecision(
                ticker=d.ticker,
                target_weight=w,
                rationale=d.rationale,
                metadata=meta,
                blocked=blocked,
                block_reason=block_reason,
            )
        )
    active = [x for x in scaled if not x.blocked and x.target_weight > 0]
    gross = sum(x.target_weight for x in active)
    max_gross = float(exposure_cap)
    if gross > max_gross + 1e-12 and gross > 0:
        factor = max_gross / gross
        rescaled: list[RiskDecision] = []
        for x in scaled:
            if x.blocked or x.target_weight <= 0:
                rescaled.append(x)
                continue
            meta = dict(x.metadata or {})
            meta["gross_scaled_from"] = x.target_weight
            rescaled.append(
                RiskDecision(
                    ticker=x.ticker,
                    target_weight=x.target_weight * factor,
                    rationale=x.rationale,
                    metadata=meta,
                    blocked=False,
                    block_reason=None,
                )
            )
        scaled = rescaled
        active = [x for x in scaled if not x.blocked and x.target_weight > 0]
        gross = sum(x.target_weight for x in active)

    return RiskOutput(
        decisions=tuple(scaled),
        metadata={
            "risk": RISK_DD_GUARD_V1,
            "exposure_cap": exposure_cap,
            "gross_exposure": gross,
            "cash_weight": max(0.0, 1.0 - gross),
        },
    )
