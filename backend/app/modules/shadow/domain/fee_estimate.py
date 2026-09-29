"""Broker fee estimate adapter for Shadow sell economics / lot plan / fills.

Uses portfolio-domain ``FeeEngine``. Slippage stays outside this module —
callers add ``slippage_bps`` separately in the sell gate and execution adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.modules.portfolio.domain.fee_engine import (
    FeeEngine,
    FeeEstimate,
    FeeEstimateContext,
    FeeStatus,
    sber_investment_builtin_rules,
)

FEE_PROFILE_CODE_SBER_INVESTMENT = "SBER_INVESTMENT"
FEE_PROFILE_VERSION_SBER_INVESTMENT = 1
FEE_RULE_UNAVAILABLE_AT_EXECUTION = "FEE_RULE_UNAVAILABLE_AT_EXECUTION"


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


@dataclass(frozen=True, slots=True)
class ShadowFeeQuote:
    """FeeEngine result plus profile identity for order/fill provenance."""

    status: FeeStatus
    amount: Decimal | None
    fee_rule_id: int | None
    matched_rule_code: str | None
    explanation: str
    fee_profile_code: str | None
    fee_profile_version: int | None
    fee_date: date
    exclude_from_turnover: bool = False

    @property
    def is_unknown(self) -> bool:
        return self.status == FeeStatus.UNKNOWN or self.amount is None

    def to_provenance(self, *, estimated: bool) -> dict[str, Any]:
        amount_key = "estimated_fee" if estimated else "actual_fee"
        return {
            "fee_profile_code": self.fee_profile_code,
            "fee_profile_version": self.fee_profile_version,
            "fee_date": self.fee_date.isoformat(),
            amount_key: float(self.amount) if self.amount is not None else None,
            "fee_rule_id": self.fee_rule_id,
            "fee_rule_code": self.matched_rule_code,
            "fee_status": str(self.status),
            "fee_explanation": self.explanation,
            "exclude_from_turnover": bool(self.exclude_from_turnover),
        }


def _normalize_profile_code(fee_profile_code: str | None) -> str | None:
    raw = (fee_profile_code or "").strip().upper()
    if not raw:
        return None
    compact = raw.replace(" ", "").replace("_", "")
    if compact in {"SBERINVESTMENT", "SBER"} or raw == FEE_PROFILE_CODE_SBER_INVESTMENT:
        return FEE_PROFILE_CODE_SBER_INVESTMENT
    return raw


def _is_sber_investment(fee_profile_code: str | None) -> bool:
    return _normalize_profile_code(fee_profile_code) == FEE_PROFILE_CODE_SBER_INVESTMENT


class FeeEngineEstimator:
    """Wraps :class:`FeeEngine`; never mixes slippage into the fee amount."""

    def __init__(
        self,
        engine: FeeEngine,
        *,
        fee_profile_code: str | None = None,
        fee_profile_version: int | None = None,
        asset_class: str | None = "EQUITY",
        market: str = "MOEX",
        execution_channel: str = "ONLINE",
    ) -> None:
        self._engine = engine
        self.fee_profile_code = fee_profile_code
        self.fee_profile_version = fee_profile_version
        self._asset_class = asset_class
        self._market = market
        self._execution_channel = execution_channel

    def estimate(
        self,
        *,
        side: str,
        notional: Decimal,
        instrument_id: int,
        as_of: date,
        instrument_symbol: str | None = None,
        fee_profile_id: int | None = None,
        fee_profile_code: str | None = None,
    ) -> ShadowFeeQuote:
        del fee_profile_id
        code = _normalize_profile_code(fee_profile_code) or self.fee_profile_code
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
        return ShadowFeeQuote(
            status=estimate.status,
            amount=Decimal(estimate.amount) if estimate.amount is not None else None,
            fee_rule_id=estimate.fee_rule_id,
            matched_rule_code=estimate.matched_rule_code,
            explanation=estimate.explanation,
            fee_profile_code=code,
            fee_profile_version=self.fee_profile_version,
            fee_date=as_of,
            exclude_from_turnover=bool(estimate.exclude_from_turnover),
        )

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
        quote = self.estimate(
            side=side,
            notional=notional,
            instrument_id=instrument_id,
            as_of=as_of,
            instrument_symbol=instrument_symbol,
            fee_profile_id=fee_profile_id,
            fee_profile_code=fee_profile_code,
        )
        if quote.is_unknown:
            return None
        return quote.amount


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


class UnknownFeeEstimator:
    """V3-safe estimator when a configured FeeProfile cannot be resolved.

    Always returns None / UNKNOWN — never fabricates 0% via legacy bps.
    """

    def __init__(
        self,
        *,
        fee_profile_code: str | None = None,
        fee_profile_version: int | None = None,
        explanation: str = "Fee profile unavailable or unsupported",
    ) -> None:
        self.fee_profile_code = fee_profile_code
        self.fee_profile_version = fee_profile_version
        self.explanation = explanation

    def estimate(
        self,
        *,
        side: str,
        notional: Decimal,
        instrument_id: int,
        as_of: date,
        instrument_symbol: str | None = None,
        fee_profile_id: int | None = None,
        fee_profile_code: str | None = None,
    ) -> ShadowFeeQuote:
        del side, notional, instrument_id, instrument_symbol, fee_profile_id
        code = _normalize_profile_code(fee_profile_code) or self.fee_profile_code
        return ShadowFeeQuote(
            status=FeeStatus.UNKNOWN,
            amount=None,
            fee_rule_id=None,
            matched_rule_code=None,
            explanation=self.explanation,
            fee_profile_code=code,
            fee_profile_version=self.fee_profile_version,
            fee_date=as_of,
        )

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
        del side, notional, instrument_id, as_of, fee_profile_id, fee_profile_code
        del instrument_symbol
        return None


def load_fee_engine_for_profile(
    session: Session | None,
    *,
    fee_profile_code: str | None,
    fee_profile_version: int | None = None,
) -> tuple[FeeEngine | None, str | None, int | None]:
    """Prefer DB rules when a session is available; else Sber builtin mirror.

    Returns ``(engine, normalized_code, version)``. Engine is None when the
    profile is unknown / unsupported.

    The in-memory Sber builtin mirror represents **exactly**
    ``SBER_INVESTMENT`` / ``FEE_PROFILE_VERSION_SBER_INVESTMENT`` (v1).
    It must not impersonate any other requested version.
    """
    code = _normalize_profile_code(fee_profile_code)
    if code is None:
        return None, None, None
    version = int(fee_profile_version or FEE_PROFILE_VERSION_SBER_INVESTMENT)

    if session is not None:
        try:
            from app.modules.portfolio.application.broker_fee_service import (
                load_fee_engine_by_code_version,
            )

            engine = load_fee_engine_by_code_version(
                session, code=code, version=version
            )
            if engine is not None:
                return engine, code, version
        except Exception:
            # Controlled: only fall through to the intentional Sber builtin mirror
            # below when the requested version is the builtin v1. Do not invent
            # fees for other profiles or unsupported Sber versions.
            pass

    if (
        _is_sber_investment(code)
        and version == FEE_PROFILE_VERSION_SBER_INVESTMENT
    ):
        return FeeEngine(sber_investment_builtin_rules()), code, version
    return None, code, version


def resolve_fee_engine_estimator(
    *,
    fee_profile_code: str | None,
    fee_profile_version: int | None = None,
    commission_bps: float = 0.0,
    session: Session | None = None,
    allow_legacy_bps_fallback: bool = True,
) -> BrokerFeeEstimator:
    """Resolve FeeEngine estimator; optionally fall back to legacy commission_bps.

    V1/V2: ``allow_legacy_bps_fallback=True`` (default) preserves flat bps.
    V3: ``allow_legacy_bps_fallback=False`` — missing/unsupported profile →
    :class:`UnknownFeeEstimator` (UNKNOWN), never fabricated 0%.
    """
    engine, code, version = load_fee_engine_for_profile(
        session,
        fee_profile_code=fee_profile_code,
        fee_profile_version=fee_profile_version,
    )
    if engine is not None:
        return FeeEngineEstimator(
            engine,
            fee_profile_code=code,
            fee_profile_version=version,
        )
    if allow_legacy_bps_fallback:
        return BpsFeeEstimator(Decimal(str(commission_bps)))
    return UnknownFeeEstimator(
        fee_profile_code=code,
        fee_profile_version=version if code is not None else fee_profile_version,
        explanation=(
            f"Fee profile unavailable or unsupported: code={code!r} version={version!r}"
            if code is not None
            else "Fee profile required but not configured"
        ),
    )


def resolve_broker_fee_estimator(
    *,
    fee_profile_code: str | None,
    commission_bps: float = 0.0,
    fee_profile_version: int | None = None,
    session: Session | None = None,
    allow_legacy_bps_fallback: bool = True,
) -> BrokerFeeEstimator:
    """Backward-compatible alias for sell-gate / unit callers."""
    return resolve_fee_engine_estimator(
        fee_profile_code=fee_profile_code,
        fee_profile_version=fee_profile_version,
        commission_bps=commission_bps,
        session=session,
        allow_legacy_bps_fallback=allow_legacy_bps_fallback,
    )


def estimate_shadow_fee(
    estimator: BrokerFeeEstimator,
    *,
    side: str,
    notional: Decimal,
    instrument_id: int,
    as_of: date,
    fee_profile_code: str | None = None,
    fee_profile_version: int | None = None,
    instrument_symbol: str | None = None,
) -> ShadowFeeQuote:
    """Uniform quote for plan/fill provenance (works with FeeEngine or bps)."""
    if isinstance(estimator, FeeEngineEstimator | UnknownFeeEstimator):
        return estimator.estimate(
            side=side,
            notional=notional,
            instrument_id=instrument_id,
            as_of=as_of,
            instrument_symbol=instrument_symbol,
            fee_profile_code=fee_profile_code,
        )
    amount = estimator.broker_fee_estimate(
        side=side,
        notional=notional,
        instrument_id=instrument_id,
        as_of=as_of,
        fee_profile_code=fee_profile_code,
        instrument_symbol=instrument_symbol,
    )
    if amount is None:
        return ShadowFeeQuote(
            status=FeeStatus.UNKNOWN,
            amount=None,
            fee_rule_id=None,
            matched_rule_code=None,
            explanation="No matching fee rule for this trade context",
            fee_profile_code=_normalize_profile_code(fee_profile_code),
            fee_profile_version=fee_profile_version,
            fee_date=as_of,
        )
    return ShadowFeeQuote(
        status=FeeStatus.KNOWN,
        amount=Decimal(amount),
        fee_rule_id=None,
        matched_rule_code=None,
        explanation=f"Legacy commission_bps fee={amount}",
        fee_profile_code=_normalize_profile_code(fee_profile_code),
        fee_profile_version=fee_profile_version,
        fee_date=as_of,
    )


def domain_estimate_from_quote(quote: ShadowFeeQuote) -> FeeEstimate:
    """Map Shadow quote back to portfolio-domain FeeEstimate when needed."""
    return FeeEstimate(
        status=quote.status,
        amount=quote.amount,
        fee_rule_id=quote.fee_rule_id,
        explanation=quote.explanation,
        exclude_from_turnover=quote.exclude_from_turnover,
        matched_rule_code=quote.matched_rule_code,
    )
