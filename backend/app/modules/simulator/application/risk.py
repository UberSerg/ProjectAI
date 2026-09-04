"""Risk Guardrails V0 — hard constraints only."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.domain.ports.portfolio import PortfolioDecision
from app.domain.ports.risk import RiskDecision, RiskManager, RiskOutput
from app.modules.simulator.config import (
    CANONICAL_MAX_SINGLE_WEIGHT,
    RISK_NAME,
)


class RiskGuardrailsV0(RiskManager):
    """Long-only, no leverage, max single-name weight, gross exposure <= 100%."""

    def apply(
        self,
        decisions: Sequence[PortfolioDecision],
        *,
        constraints: dict[str, Any] | None = None,
    ) -> RiskOutput:
        c = constraints or {}
        max_single = float(c.get("max_single_weight", CANONICAL_MAX_SINGLE_WEIGHT))
        max_gross = float(c.get("max_gross_exposure", 1.0))
        long_only = bool(c.get("long_only", True))

        out: list[RiskDecision] = []
        for d in decisions:
            w = float(d.target_weight)
            blocked = False
            reason: str | None = None
            meta = dict(d.metadata or {})
            if long_only and w < 0:
                blocked = True
                reason = "short_not_allowed"
                w = 0.0
            if w > max_single + 1e-12:
                meta["clamped_from"] = w
                w = max_single
                meta["clamped"] = True
            out.append(
                RiskDecision(
                    ticker=d.ticker,
                    target_weight=w,
                    rationale=d.rationale if not blocked else f"blocked: {reason}",
                    metadata=meta,
                    blocked=blocked,
                    block_reason=reason,
                )
            )

        active = [x for x in out if not x.blocked and x.target_weight > 0]
        gross = sum(x.target_weight for x in active)
        if gross > max_gross + 1e-12 and gross > 0:
            scale = max_gross / gross
            scaled: list[RiskDecision] = []
            for x in out:
                if x.blocked or x.target_weight <= 0:
                    scaled.append(x)
                    continue
                meta = dict(x.metadata or {})
                meta["gross_scaled_from"] = x.target_weight
                scaled.append(
                    RiskDecision(
                        ticker=x.ticker,
                        target_weight=x.target_weight * scale,
                        rationale=x.rationale,
                        metadata=meta,
                        blocked=False,
                        block_reason=None,
                    )
                )
            out = scaled
            active = [x for x in out if not x.blocked and x.target_weight > 0]
            gross = sum(x.target_weight for x in active)

        cash_weight = max(0.0, 1.0 - gross)
        return RiskOutput(
            decisions=tuple(out),
            metadata={
                "risk": RISK_NAME,
                "gross_exposure": gross,
                "cash_weight": cash_weight,
                "max_single_weight": max_single,
                "max_gross_exposure": max_gross,
            },
        )
