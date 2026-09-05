"""Asset Allocation Foundation V0 — domain contracts (framework-free).

Asset Allocation uses model/opportunity outputs; it does not replace prediction models.
No ML, no historical weight optimization, no real trading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from app.modules.investment.domain.allocation import AssetSleeve


class PredictionQuality(StrEnum):
    UNKNOWN = "UNKNOWN"
    OBSERVED = "OBSERVED"
    CALIBRATED = "CALIBRATED"


class AllocationStatus(StrEnum):
    READY = "READY"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class PolicyId(StrEnum):
    STATIC_100_EQUITY = "STATIC_100_EQUITY"
    STATIC_100_FIXED_INCOME = "STATIC_100_FIXED_INCOME"
    STATIC_100_CASH = "STATIC_100_CASH"
    CBR_HURDLE_GATE_V0 = "CBR_HURDLE_GATE_V0"


@dataclass(frozen=True, slots=True)
class EquityOpportunity:
    expected_return: float | None
    expected_excess_return: float | None
    confidence: float | None
    model_source: str | None
    timestamp: datetime | date | None
    limitations: tuple[str, ...] = ()
    prediction_quality: PredictionQuality = PredictionQuality.UNKNOWN
    calibration_status: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class FixedIncomeOpportunity:
    expected_yield: float | None
    duration: float | None
    credit_quality: str  # UNKNOWN | OBSERVED | …
    liquidity: str  # UNKNOWN | OK | LIMITED
    data_quality: str  # READY | PARTIAL | NOT_READY
    supported_ratio: float | None  # share of FI universe with SUPPORTED cashflows
    limitations: tuple[str, ...] = ()
    yield_source: str | None = None
    liquidity_status: str | None = None
    support_status: str | None = None

    @property
    def yield_is_guaranteed(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class CashOpportunity:
    annual_rate: float | None
    horizon_return: float | None
    source: str
    quality: str  # DATE_ONLY | EXACT_TIMESTAMP | UNKNOWN
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RiskState:
    drawdown: float | None = None
    volatility: float | None = None
    concentration: float | None = None
    liquidity_stress: bool = False
    source: str = "EXISTING_COMPONENTS_OR_UNKNOWN"
    limitations: tuple[str, ...] = ("No dedicated Risk Engine in V0",)


@dataclass(frozen=True, slots=True)
class LiquidityState:
    can_rebalance: bool = True
    stale_prices: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AllocationConstraints:
    """Research configuration — values are not optimized."""

    max_equity_weight: float = 1.0
    max_single_position: float = 1.0
    min_cash: float = 0.0
    min_fixed_income: float = 0.0
    max_fixed_income: float = 1.0
    require_supported_bonds_for_fi: bool = True


@dataclass(frozen=True, slots=True)
class AllocationContext:
    as_of_date: date
    available_capital: Decimal
    cbr_hurdle_annual: float | None
    equity: EquityOpportunity | None
    fixed_income: FixedIncomeOpportunity | None
    cash: CashOpportunity | None
    risk: RiskState = field(default_factory=RiskState)
    liquidity: LiquidityState = field(default_factory=LiquidityState)
    constraints: AllocationConstraints = field(default_factory=AllocationConstraints)
    # Research gate: equity must clear hurdle by at least this premium (not tuned).
    required_equity_premium: float = 0.0


@dataclass(frozen=True, slots=True)
class AllocationDecision:
    policy_id: str
    equity_weight: float
    fixed_income_weight: float
    cash_weight: float
    reason_codes: tuple[str, ...]
    explanation_ru: str
    status: AllocationStatus
    confidence: float | None
    limitations: tuple[str, ...]

    def weights(self) -> dict[AssetSleeve, float]:
        return {
            AssetSleeve.EQUITY_ALPHA: self.equity_weight,
            AssetSleeve.FIXED_INCOME: self.fixed_income_weight,
            AssetSleeve.CASH: self.cash_weight,
        }


class AssetAllocationPolicy(Protocol):
    """Framework-free allocation policy port."""

    policy_id: str

    def decide(self, context: AllocationContext) -> AllocationDecision: ...


def _validate_weights(equity: float, fi: float, cash: float) -> None:
    if equity < 0 or fi < 0 or cash < 0:
        raise ValueError("allocation weights must be non-negative")
    if abs((equity + fi + cash) - 1.0) > 1e-9:
        raise ValueError("allocation weights must sum to 1.0")


def _decision(
    *,
    policy_id: str,
    equity: float,
    fixed_income: float,
    cash: float,
    reason_codes: tuple[str, ...],
    explanation_ru: str,
    status: AllocationStatus,
    confidence: float | None,
    limitations: tuple[str, ...],
) -> AllocationDecision:
    _validate_weights(equity, fixed_income, cash)
    return AllocationDecision(
        policy_id=policy_id,
        equity_weight=equity,
        fixed_income_weight=fixed_income,
        cash_weight=cash,
        reason_codes=reason_codes,
        explanation_ru=explanation_ru,
        status=status,
        confidence=confidence,
        limitations=limitations,
    )


@dataclass(frozen=True, slots=True)
class StaticHundredPolicy:
    """STATIC_100_* research benchmarks — deterministic, not optimized."""

    policy_id: str
    equity: float
    fixed_income: float
    cash: float
    explanation_ru: str

    def decide(self, context: AllocationContext) -> AllocationDecision:
        _ = context
        return _decision(
            policy_id=self.policy_id,
            equity=self.equity,
            fixed_income=self.fixed_income,
            cash=self.cash,
            reason_codes=(f"static_benchmark:{self.policy_id}",),
            explanation_ru=self.explanation_ru,
            status=AllocationStatus.RESEARCH_ONLY,
            confidence=1.0,
            limitations=("Static research benchmark — not an optimized policy",),
        )


STATIC_100_EQUITY = StaticHundredPolicy(
    PolicyId.STATIC_100_EQUITY.value,
    1.0,
    0.0,
    0.0,
    "Исследовательский бенчмарк: весь капитал в Equity Alpha (100%).",
)
STATIC_100_FIXED_INCOME = StaticHundredPolicy(
    PolicyId.STATIC_100_FIXED_INCOME.value,
    0.0,
    1.0,
    0.0,
    "Исследовательский бенчмарк: весь капитал в Fixed Income (100%). "
    "Облигация не всегда безопасна — корпоративные бумаги несут кредитный риск.",
)
STATIC_100_CASH = StaticHundredPolicy(
    PolicyId.STATIC_100_CASH.value,
    0.0,
    0.0,
    1.0,
    "Исследовательский бенчмарк: капитал остаётся в денежной альтернативе (CBR hurdle).",
)


@dataclass(frozen=True, slots=True)
class CbrHurdleGatePolicyV0:
    """Reduce equity when expected excess return does not clear the hurdle premium.

    Research-only. Does not optimize weights on history.
    """

    policy_id: str = PolicyId.CBR_HURDLE_GATE_V0.value

    def decide(self, context: AllocationContext) -> AllocationDecision:
        limitations: list[str] = [
            "Research-only gate — not production capital management",
            "No ML / no historical weight optimization",
            "Облигация не всегда является безопасным активом. " "Корпоративные облигации несут кредитный риск.",
        ]
        reasons: list[str] = []

        if context.cbr_hurdle_annual is None and (context.cash is None or context.cash.annual_rate is None):
            return _decision(
                policy_id=self.policy_id,
                equity=0.0,
                fixed_income=0.0,
                cash=1.0,
                reason_codes=("insufficient_data:cbr_hurdle",),
                explanation_ru=(
                    "Недостаточно данных по ключевой ставке ЦБ — Kraken не угадывает "
                    "распределение и оставляет капитал в денежной позиции как безопасный default."
                ),
                status=AllocationStatus.INSUFFICIENT_DATA,
                confidence=None,
                limitations=tuple(limitations + ["CBR hurdle missing"]),
            )

        equity_ok, equity_reasons = _equity_clears_gate(context)
        reasons.extend(equity_reasons)

        fi_ok, fi_reasons = _fixed_income_usable(context)
        reasons.extend(fi_reasons)

        if context.liquidity.stale_prices:
            reasons.append("stale_prices")
            limitations.append("Stale prices observed — treat as data-quality warning")

        if equity_ok:
            equity_w = min(1.0, context.constraints.max_equity_weight)
            # Prefer keeping some cash if configured.
            cash_w = max(context.constraints.min_cash, 0.0)
            fi_w = max(context.constraints.min_fixed_income, 0.0)
            remaining = 1.0 - cash_w - fi_w
            equity_w = min(equity_w, remaining)
            leftover = 1.0 - equity_w - cash_w - fi_w
            if leftover > 0:
                if fi_ok:
                    fi_w += leftover
                else:
                    cash_w += leftover
            explanation = (
                "Ожидаемая премия акций над ключевой ставкой достаточна для research-гейта — "
                "доля Equity Alpha сохранена. Это не сигнал покупать и не обещание доходности."
            )
            status = AllocationStatus.RESEARCH_ONLY
            confidence = (
                0.5 if context.equity and context.equity.prediction_quality == PredictionQuality.UNKNOWN else 0.6
            )
            return _apply_constraints_and_decide(
                context,
                policy_id=self.policy_id,
                equity=equity_w,
                fixed_income=fi_w,
                cash=cash_w,
                reason_codes=tuple(reasons or ("equity_excess_clears_hurdle",)),
                explanation_ru=explanation,
                status=status,
                confidence=confidence,
                limitations=tuple(limitations),
            )

        # Equity premium insufficient or unknown → shrink equity.
        equity_w = 0.0
        reasons.append("equity_expected_excess_below_required_premium")
        if fi_ok:
            fi_w = min(context.constraints.max_fixed_income, 1.0 - context.constraints.min_cash)
            cash_w = 1.0 - fi_w
            explanation = (
                "Kraken уменьшил долю акций, потому что ожидаемая премия над ключевой ставкой "
                "недостаточна для текущего research-гейта. Капитал смещён в Fixed Income "
                "(с оговоркой о кредитном риске) и денежную альтернативу."
            )
        else:
            fi_w = 0.0
            cash_w = 1.0
            explanation = (
                "Kraken уменьшил долю акций: ожидаемая премия над ключевой ставкой недостаточна. "
                "Надёжного Fixed Income sleeve нет (unsupported / unknown credit / weak data) — "
                "капитал остаётся в денежной альтернативе относительно CBR hurdle."
            )
            reasons.append("fixed_income_unavailable_fallback_cash")

        return _apply_constraints_and_decide(
            context,
            policy_id=self.policy_id,
            equity=equity_w,
            fixed_income=fi_w,
            cash=cash_w,
            reason_codes=tuple(dict.fromkeys(reasons)),
            explanation_ru=explanation,
            status=AllocationStatus.RESEARCH_ONLY,
            confidence=0.55,
            limitations=tuple(limitations),
        )


def _equity_clears_gate(context: AllocationContext) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    eq = context.equity
    if eq is None:
        reasons.append("insufficient_data:equity_opportunity")
        return False, reasons
    if eq.prediction_quality is PredictionQuality.UNKNOWN:
        reasons.append("prediction_quality_unknown")
    if eq.expected_excess_return is None:
        reasons.append("insufficient_data:equity_expected_excess_return")
        return False, reasons
    if eq.expected_excess_return < context.required_equity_premium:
        reasons.append("equity_excess_below_premium")
        return False, reasons
    reasons.append("equity_excess_clears_hurdle")
    return True, reasons


def _fixed_income_usable(context: AllocationContext) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    fi = context.fixed_income
    if fi is None:
        reasons.append("insufficient_data:fixed_income_opportunity")
        return False, reasons
    if fi.data_quality in {"NOT_READY", "MISSING"}:
        reasons.append("fixed_income_data_not_ready")
        return False, reasons
    if context.constraints.require_supported_bonds_for_fi:
        ratio = fi.supported_ratio
        if ratio is None or ratio <= 0:
            reasons.append("no_supported_bonds")
            return False, reasons
    if fi.credit_quality == "UNKNOWN" and (fi.supported_ratio or 0) > 0:
        # Still usable for research sleeve, but flagged — corporate UNKNOWN is not "safe".
        reasons.append("credit_quality_unknown_research_only")
    reasons.append("fixed_income_sleeve_available")
    return True, reasons


def _apply_constraints_and_decide(
    context: AllocationContext,
    *,
    policy_id: str,
    equity: float,
    fixed_income: float,
    cash: float,
    reason_codes: tuple[str, ...],
    explanation_ru: str,
    status: AllocationStatus,
    confidence: float | None,
    limitations: tuple[str, ...],
) -> AllocationDecision:
    equity = min(equity, context.constraints.max_equity_weight)
    fixed_income = min(fixed_income, context.constraints.max_fixed_income)
    cash = max(cash, context.constraints.min_cash)
    fixed_income = max(fixed_income, context.constraints.min_fixed_income)
    total = equity + fixed_income + cash
    if total <= 0:
        equity, fixed_income, cash = 0.0, 0.0, 1.0
    else:
        equity, fixed_income, cash = equity / total, fixed_income / total, cash / total
    # Re-enforce min_cash after normalize if possible.
    if cash < context.constraints.min_cash:
        need = context.constraints.min_cash - cash
        take = min(need, equity)
        equity -= take
        cash += take
        need = context.constraints.min_cash - cash
        if need > 0:
            take = min(need, fixed_income)
            fixed_income -= take
            cash += take
    return _decision(
        policy_id=policy_id,
        equity=equity,
        fixed_income=fixed_income,
        cash=cash,
        reason_codes=reason_codes,
        explanation_ru=explanation_ru,
        status=status,
        confidence=confidence,
        limitations=limitations,
    )


POLICIES: dict[str, AssetAllocationPolicy] = {
    PolicyId.STATIC_100_EQUITY.value: STATIC_100_EQUITY,
    PolicyId.STATIC_100_FIXED_INCOME.value: STATIC_100_FIXED_INCOME,
    PolicyId.STATIC_100_CASH.value: STATIC_100_CASH,
    PolicyId.CBR_HURDLE_GATE_V0.value: CbrHurdleGatePolicyV0(),
}


def get_policy(policy_id: str) -> AssetAllocationPolicy:
    try:
        return POLICIES[policy_id]
    except KeyError as exc:
        raise KeyError(f"Unknown allocation policy: {policy_id}") from exc


@dataclass(frozen=True, slots=True)
class AllocationResearchRun:
    """Contract only — no mass historical backtest in V0."""

    run_id: str | None
    policy_id: str
    as_of_from: date | None
    as_of_to: date | None
    status: str  # CONTRACT_ONLY | NOT_EXECUTED
    note: str = "Allocation Research Run is a foundation contract. " "Mass historical backtest is out of scope for V0."


@dataclass(frozen=True, slots=True)
class EconomicVerdictView:
    """Portfolio-level economic framing — not a magic score."""

    portfolio_return: float | None
    cbr_hurdle_return: float | None
    imoex_return: float | None
    max_drawdown: float | None
    risk_note: str
    question_ru: str = "Оправдал ли результат риск?"
    answer_ru: str = (
        "В V0 вердикт исследовательский: сравнивайте доходность с CBR hurdle и IMOEX "
        "явно, без скрытого investment_score."
    )


BOND_SAFETY_REMINDER_RU = (
    "Облигация не всегда является безопасным активом. " "Корпоративные облигации несут кредитный риск."
)

REASON_CODE_RU: dict[str, str] = {
    "equity_excess_clears_hurdle": "Премия акций над hurdle достаточна (research gate)",
    "equity_expected_excess_below_required_premium": "Ожидаемая премия акций ниже требуемой",
    "equity_excess_below_premium": "Excess return ниже premium",
    "prediction_quality_unknown": "Качество прогноза UNKNOWN (нет доказанной калибровки)",
    "insufficient_data:equity_opportunity": "Нет данных Equity Opportunity",
    "insufficient_data:equity_expected_excess_return": "Нет expected excess return по акциям",
    "insufficient_data:cbr_hurdle": "Нет ключевой ставки ЦБ",
    "insufficient_data:fixed_income_opportunity": "Нет данных Fixed Income Opportunity",
    "fixed_income_data_not_ready": "Данные облигаций не готовы",
    "no_supported_bonds": "Нет SUPPORTED облигаций для sleeve",
    "credit_quality_unknown_research_only": "Кредитное качество UNKNOWN — research only",
    "fixed_income_sleeve_available": "Fixed Income sleeve доступен для research",
    "fixed_income_unavailable_fallback_cash": "FI недоступен — fallback в cash",
    "stale_prices": "Устаревшие цены",
}
