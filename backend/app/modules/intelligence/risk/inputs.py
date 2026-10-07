"""Explicit risk factor inputs. Missing stays None — never treated as zero risk."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.modules.intelligence.contracts.provenance import EvidenceRef


@dataclass(frozen=True, slots=True)
class RiskFactorInputs:
    """Point-in-time risk factors for one instrument.

    Callers supply only information known at ``as_of``. This engine does not
    fetch market data; upstream collectors own PIT gates.
    """

    as_of: date
    instrument_id: int

    # Volatility proxies (annualized fraction / daily ATR fraction of price).
    realized_vol: float | None = None
    atr_pct: float | None = None

    # Drawdown from recent peak as positive magnitude in [0, 1], or signed (<=0).
    drawdown: float | None = None

    # Liquidity.
    avg_daily_value: float | None = None
    spread_proxy_bps: float | None = None
    liquidity_state_hint: str | None = None

    # Coarse market regime label from macro/regime agents when available.
    market_regime: str | None = None

    # Event / CA / fundamental qualitative levels.
    event_risk_level: str | None = None
    material_adverse_event: bool = False
    ca_uncertainty: str | None = None
    fundamental_deterioration: str | None = None

    # Data quality.
    data_stale: bool = False
    data_missing_critical: bool = False
    stale_days: int | None = None

    # Optional portfolio context.
    position_weight: float | None = None
    position_nav: float | None = None

    evidence_refs: tuple[EvidenceRef, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def drawdown_magnitude(self) -> float | None:
        if self.drawdown is None:
            return None
        value = float(self.drawdown)
        return abs(value)
