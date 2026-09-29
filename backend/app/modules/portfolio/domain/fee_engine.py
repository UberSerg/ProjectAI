"""Pure broker Fee Engine (no FastAPI / SQLAlchemy).

Estimates broker commission from versioned FeeRule specs.
Slippage and exchange fees are out of scope — never mixed into the result.
Fee base is clean notional (excludes NKD).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.modules.portfolio.domain.personal_ledger import ZERO, money

# percentage_rate is a fraction of notional: 0.003 == 0.3%.


class FeeStatus(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class FeeType(StrEnum):
    PERCENTAGE = "PERCENTAGE"
    FIXED = "FIXED"
    PERCENTAGE_PLUS_FIXED = "PERCENTAGE_PLUS_FIXED"


@dataclass(frozen=True)
class FeeRuleSpec:
    """Immutable matching rule for FeeEngine (DB row or in-memory seed)."""

    id: int | None
    code: str | None = None
    market: str | None = None
    trading_system: str | None = None
    execution_channel: str | None = None
    side: str | None = None  # BUY | SELL | ANY | None(=any)
    asset_class: str | None = None
    instrument_subtype: str | None = None
    instrument_id: int | None = None
    instrument_symbol: str | None = None
    turnover_from: Decimal | None = None  # inclusive same-day account turnover
    turnover_to: Decimal | None = None  # exclusive upper bound; None = unbounded
    fee_type: str = FeeType.PERCENTAGE
    percentage_rate: Decimal | None = None
    fixed_amount: Decimal | None = None
    exclude_from_turnover: bool = False
    priority: int = 100  # lower wins
    valid_from: date | None = None
    valid_to: date | None = None
    explanation: str | None = None
    active: bool = True


@dataclass(frozen=True)
class FeeEstimateContext:
    """Inputs for one fee estimate.

    ``notional`` is the trade turnover base and must exclude NKD.
    ``nkd`` is accepted only so callers can pass accrued interest without
    accidentally enlarging the fee base — it is never added to notional.
    Daily ``broker_account_day_turnover`` is shared across Kraken portfolios
    that use the same BrokerAccount (tier matching); it must already exclude
    NKD and trades marked exclude_from_turnover.
    """

    as_of: date
    side: str  # BUY | SELL
    notional: Decimal
    nkd: Decimal = ZERO
    market: str = "MOEX"
    trading_system: str | None = None
    execution_channel: str | None = "ONLINE"
    asset_class: str | None = None
    instrument_subtype: str | None = None
    instrument_id: int | None = None
    instrument_symbol: str | None = None
    broker_account_day_turnover: Decimal = ZERO


@dataclass(frozen=True)
class FeeEstimate:
    status: FeeStatus
    amount: Decimal | None
    fee_rule_id: int | None
    explanation: str
    exclude_from_turnover: bool = False
    matched_rule_code: str | None = None

    @property
    def is_unknown(self) -> bool:
        return self.status == FeeStatus.UNKNOWN


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().upper()
    return text or None


def _side_matches(rule_side: str | None, trade_side: str) -> bool:
    rs = _norm(rule_side)
    if rs is None or rs == "ANY":
        return True
    return rs == _norm(trade_side)


def _dim_matches(rule_value: str | None, ctx_value: str | None) -> bool:
    """Null rule dimension = wildcard. If rule sets a value, context must match."""
    rv = _norm(rule_value)
    if rv is None:
        return True
    return rv == _norm(ctx_value)


def _date_in_range(as_of: date, valid_from: date | None, valid_to: date | None) -> bool:
    if valid_from is not None and as_of < valid_from:
        return False
    if valid_to is not None and as_of > valid_to:
        return False
    return True


def _turnover_matches(
    day_turnover: Decimal,
    turnover_from: Decimal | None,
    turnover_to: Decimal | None,
) -> bool:
    if turnover_from is not None and day_turnover < turnover_from:
        return False
    if turnover_to is not None and day_turnover >= turnover_to:
        return False
    return True


def _instrument_matches(rule: FeeRuleSpec, ctx: FeeEstimateContext) -> bool:
    """Instrument override: if rule pins id and/or symbol, context must match."""
    if rule.instrument_id is not None:
        if ctx.instrument_id is None or ctx.instrument_id != rule.instrument_id:
            return False
    if rule.instrument_symbol is not None:
        if _norm(ctx.instrument_symbol) != _norm(rule.instrument_symbol):
            return False
    return True


def fee_base_notional(ctx: FeeEstimateContext) -> Decimal:
    """Clean notional for broker turnover / % fee. NKD is never included."""
    # Explicitly ignore nkd for the fee base (caller may pass it for provenance).
    _ = ctx.nkd
    base = money(ctx.notional)
    if base < ZERO:
        return ZERO
    return base


def compute_fee_amount(rule: FeeRuleSpec, base: Decimal) -> Decimal:
    fee_type = _norm(rule.fee_type) or FeeType.PERCENTAGE
    pct = Decimal(str(rule.percentage_rate)) if rule.percentage_rate is not None else ZERO
    fixed = money(rule.fixed_amount) if rule.fixed_amount is not None else ZERO

    if fee_type == FeeType.FIXED:
        return money(fixed)
    if fee_type == FeeType.PERCENTAGE_PLUS_FIXED:
        return money(base * pct + fixed)
    # PERCENTAGE (default)
    return money(base * pct)


class FeeEngine:
    """Match FeeRuleSpec list and estimate broker commission."""

    def __init__(self, rules: Sequence[FeeRuleSpec]) -> None:
        self._rules = list(rules)

    def estimate_fee(self, context: FeeEstimateContext) -> FeeEstimate:
        base = fee_base_notional(context)
        day_to = money(context.broker_account_day_turnover)
        if day_to < ZERO:
            day_to = ZERO

        matched = self._match(context, day_to)
        if matched is None:
            return FeeEstimate(
                status=FeeStatus.UNKNOWN,
                amount=None,
                fee_rule_id=None,
                explanation="No matching fee rule for this trade context",
                exclude_from_turnover=False,
                matched_rule_code=None,
            )

        amount = compute_fee_amount(matched, base)
        explanation = matched.explanation or (
            f"Matched rule {matched.code or matched.id}: "
            f"fee={amount} on clean notional {base}"
        )
        return FeeEstimate(
            status=FeeStatus.KNOWN,
            amount=amount,
            fee_rule_id=matched.id,
            explanation=explanation,
            exclude_from_turnover=matched.exclude_from_turnover,
            matched_rule_code=matched.code,
        )

    def _match(self, ctx: FeeEstimateContext, day_turnover: Decimal) -> FeeRuleSpec | None:
        candidates: list[FeeRuleSpec] = []
        for rule in self._rules:
            if not rule.active:
                continue
            if not _date_in_range(ctx.as_of, rule.valid_from, rule.valid_to):
                continue
            if not _side_matches(rule.side, ctx.side):
                continue
            if not _dim_matches(rule.market, ctx.market):
                continue
            if not _dim_matches(rule.trading_system, ctx.trading_system):
                continue
            if not _dim_matches(rule.execution_channel, ctx.execution_channel):
                continue
            if not _dim_matches(rule.asset_class, ctx.asset_class):
                continue
            if not _dim_matches(rule.instrument_subtype, ctx.instrument_subtype):
                continue
            if not _instrument_matches(rule, ctx):
                continue
            if not _turnover_matches(day_turnover, rule.turnover_from, rule.turnover_to):
                continue
            candidates.append(rule)

        if not candidates:
            return None

        # Specificity: instrument-pinned rules beat generic at same priority.
        def sort_key(r: FeeRuleSpec) -> tuple[int, int, int]:
            specificity = 0
            if r.instrument_id is not None or r.instrument_symbol is not None:
                specificity -= 10
            if r.side is not None and _norm(r.side) not in (None, "ANY"):
                specificity -= 1
            return (r.priority, specificity, r.id if r.id is not None else 10**9)

        candidates.sort(key=sort_key)
        return candidates[0]


def sber_investment_builtin_rules(*, profile_rule_ids: dict[str, int] | None = None) -> list[FeeRuleSpec]:
    """In-memory mirror of the seeded Sber Investment rules (for pure unit tests)."""
    ids = profile_rule_ids or {}
    return [
        FeeRuleSpec(
            id=ids.get("SBER_SBFR_ZERO_TEMP", 1),
            code="SBER_SBFR_ZERO_TEMP",
            market="MOEX",
            execution_channel="ONLINE",
            side="ANY",
            instrument_symbol="SBFR",
            fee_type=FeeType.PERCENTAGE,
            percentage_rate=Decimal("0"),
            exclude_from_turnover=True,
            priority=10,
            valid_from=date(2026, 8, 4),
            valid_to=date(2026, 12, 31),
            explanation=(
                "Temporary zero broker fee for verified УК Первая BPIF (SBFR). "
                "Turnover excluded from broker daily turnover."
            ),
        ),
        FeeRuleSpec(
            id=ids.get("SBER_MOEX_ONLINE_DEFAULT", 2),
            code="SBER_MOEX_ONLINE_DEFAULT",
            market="MOEX",
            execution_channel="ONLINE",
            side="ANY",
            fee_type=FeeType.PERCENTAGE,
            percentage_rate=Decimal("0.003"),
            exclude_from_turnover=False,
            priority=100,
            # Snapshot known_at: generic 0.3% is valid from the tariff snapshot date,
            # not from calendar year start. SBFR temp zero remains 2026-08-04..2026-12-31.
            valid_from=date(2026, 9, 29),
            explanation=(
                "Default MOEX stock-market online trades: 0.3% of turnover "
                "(broker commission; exchange fees separate). Turnover excludes NKD."
            ),
        ),
    ]
