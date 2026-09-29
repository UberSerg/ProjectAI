"""Broker fee estimate adapter for Shadow sell economics.

Uses portfolio-domain ``FeeEngine`` (Agent 2). Slippage stays outside this module —
callers add ``slippage_bps`` separately in the sell gate.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol

from app.modules.portfolio.domain.fee_engine import (
    FeeEngine,
    FeeEstimateContext,
    FeeStatus,
    sber_investment_builtin_rules,
)

FEE_PROFILE_CODE_SBER_INVESTMENT = "SBER_INVESTMENT"


class BrokerFeeEstimator(Protocol):
    """Narrow contract: absolute broker fee money, or None if unknown."""

    def broker_fee_estimate(
        self,
        *,
        side: str,
        notional: Decimal,
        instrument_id: int,
        as_of: date,
        fee_profile_id: int | None = None,
        fee_profile_code: str | None = None,
        instrument_symbol: str | None = None,
    ) -> Decimal | None: ...


class FeeEngineEstimator:
    """Wraps :class:`FeeEngine`; never mixes slippage into the fee amount."""

    def __init__(
        self,
        engine: FeeEngine,
        *,
        asset_class: str | None = "EQUITY",
        market: str = "MOEX",
        execution_channel: str = "ONLINE",
    ) -> None:
        self._engine = engine
        self._asset_class = asset_class
        self._market = market
        self._execution_channel = execution_channel

    def broker_fee_estimate(
        self,
        *,
        side: str,
        notional: Decimal,
        instrument_id: int,
        as_of: date,
        fee_profile_id: int | None = None,
        fee_profile_code: str | None = None,
        instrument_symbol: str | None = None,
    ) -> Decimal | None:
        del fee_profile_id, fee_profile_code
        estimate = self._engine.estimate_fee(
            FeeEstimateContext(
                as_of=as_of,
                side=str(side).upper(),
                notional=Decimal(notional),
                market=self._market,
                execution_channel=self._execution_channel,
                asset_class=self._asset_class,
                instrument_id=int(instrument_id),
                instrument_symbol=instrument_symbol,
            )
        )
        if estimate.status == FeeStatus.UNKNOWN or estimate.amount is None:
            return None
        return Decimal(estimate.amount)


class BpsFeeEstimator:
    """Legacy proportional fee for non-FeeProfile shadow specs (V1/V2 commission_bps)."""

    def __init__(self, broker_bps: Decimal) -> None:
        self.broker_bps = Decimal(broker_bps)

    def broker_fee_estimate(
        self,
        *,
        side: str,
        notional: Decimal,
        instrument_id: int,
        as_of: date,
        fee_profile_id: int | None = None,
        fee_profile_code: str | None = None,
        instrument_symbol: str | None = None,
    ) -> Decimal | None:
        del side, instrument_id, as_of, fee_profile_id, fee_profile_code, instrument_symbol
        n = Decimal(notional)
        if n <= 0:
            return Decimal("0")
        return (n * self.broker_bps) / Decimal("10000")


def resolve_broker_fee_estimator(
    *,
    fee_profile_code: str | None,
    commission_bps: float = 0.0,
) -> BrokerFeeEstimator:
    """Sber Investment → FeeEngine builtin rules; else legacy commission_bps."""
    code = (fee_profile_code or "").strip().upper().replace(" ", "").replace("_", "")
    if code in {
        "SBERINVESTMENT",
        "SBER",
        FEE_PROFILE_CODE_SBER_INVESTMENT.replace("_", ""),
    } or (fee_profile_code or "").strip().upper() == FEE_PROFILE_CODE_SBER_INVESTMENT:
        return FeeEngineEstimator(FeeEngine(sber_investment_builtin_rules()))
    return BpsFeeEstimator(Decimal(str(commission_bps)))
