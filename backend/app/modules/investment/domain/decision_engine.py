"""Investment Decision Engine V0 — opportunity + risk → explained allocation.

Does not replace prediction models or Asset Allocation Foundation policies.
No ML, no historical weight optimization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.modules.investment.domain.calibration import CalibrationStatus
from app.modules.investment.domain.policy import (
    BOND_SAFETY_REMINDER_RU,
    AllocationStatus,
    CashOpportunity,
    EquityOpportunity,
    FixedIncomeOpportunity,
    PredictionQuality,
)
from app.modules.investment.domain.risk_budget import RiskBudget


@dataclass(frozen=True, slots=True)
class MarketContext:
    as_of_date: date
    available_capital: Decimal
    cbr_hurdle_annual: float | None
    volatility: float | None = None
    drawdown: float | None = None
    concentration: float | None = None
    liquidity_ok: bool = True
    data_quality_ok: bool = True


@dataclass(frozen=True, slots=True)
class InvestmentDecision:
    profile_id: str
    equity_weight: float
    fixed_income_weight: float
    cash_weight: float
    reason_codes: tuple[str, ...]
    explanations: tuple[str, ...]
    warnings: tuple[str, ...]
    status: AllocationStatus
    why_equity_ru: str
    why_fixed_income_ru: str
    why_cash_ru: str
    limitations: tuple[str, ...]


def _validate(equity: float, fi: float, cash: float) -> tuple[float, float, float]:
    if equity < 0 or fi < 0 or cash < 0:
        raise ValueError("weights must be non-negative")
    total = equity + fi + cash
    if total <= 0:
        return 0.0, 0.0, 1.0
    equity, fi, cash = equity / total, fi / total, cash / total
    if abs(equity + fi + cash - 1.0) > 1e-9:
        raise ValueError("weights must sum to 1")
    return equity, fi, cash


class InvestmentDecisionEngine:
    """Deterministic research decision engine."""

    def decide(
        self,
        *,
        equity: EquityOpportunity | None,
        fixed_income: FixedIncomeOpportunity | None,
        cash: CashOpportunity | None,
        risk_budget: RiskBudget,
        market: MarketContext,
    ) -> InvestmentDecision:
        reasons: list[str] = []
        warnings: list[str] = [BOND_SAFETY_REMINDER_RU]
        limitations = [
            "Research-only Investment Decision Engine V0",
            "No ML / no optimization / no broker",
            *risk_budget.limitations,
        ]

        if market.cbr_hurdle_annual is None and (cash is None or cash.annual_rate is None):
            eq, fi, csh = _validate(0.0, 0.0, 1.0)
            return InvestmentDecision(
                profile_id=risk_budget.profile_id,
                equity_weight=eq,
                fixed_income_weight=fi,
                cash_weight=csh,
                reason_codes=("insufficient_data:cbr_hurdle",),
                explanations=(
                    "Недостаточно данных по ключевой ставке — Kraken не угадывает решение "
                    "и оставляет капитал в денежной позиции.",
                ),
                warnings=tuple(warnings),
                status=AllocationStatus.INSUFFICIENT_DATA,
                why_equity_ru="Нет надёжного контекста hurdle для оценки премии акций.",
                why_fixed_income_ru="Без hurdle сравнение FI неполно.",
                why_cash_ru="Недостаточно подтверждённых возможностей — cash как безопасный default.",
                limitations=tuple(limitations),
            )

        equity_allowed, equity_reasons, why_eq = self._assess_equity(equity, risk_budget, market)
        reasons.extend(equity_reasons)

        fi_allowed, fi_reasons, why_fi = self._assess_fi(fixed_income, risk_budget)
        reasons.extend(fi_reasons)

        if not market.liquidity_ok:
            reasons.append("liquidity_stress")
            warnings.append("Ликвидность ограничена — доля риска снижена.")
            equity_allowed = min(equity_allowed, risk_budget.max_equity_weight * 0.5)

        if market.volatility is not None and risk_budget.max_volatility is not None:
            if market.volatility > risk_budget.max_volatility:
                reasons.append("volatility_above_budget")
                equity_allowed = min(equity_allowed, risk_budget.max_equity_weight * 0.5)
                warnings.append("Волатильность выше risk budget.")

        if market.drawdown is not None and risk_budget.max_drawdown is not None:
            if abs(market.drawdown) > risk_budget.max_drawdown:
                reasons.append("drawdown_above_budget")
                equity_allowed = min(equity_allowed, 0.2)
                warnings.append("Просадка выше допустимой для профиля.")

        if not market.data_quality_ok:
            reasons.append("data_quality_weak")
            warnings.append("Слабое качество данных — больше веса cash.")

        # Target mix under budget.
        equity_w = min(equity_allowed, risk_budget.max_equity_weight)
        cash_w = max(risk_budget.min_cash, 0.0)
        fi_w = 0.0
        remaining = max(0.0, 1.0 - equity_w - cash_w)
        if fi_allowed and remaining > 0:
            fi_w = min(remaining, risk_budget.max_fixed_income)
            remaining -= fi_w
        cash_w += remaining

        # If equity not justified, push to FI then cash.
        if equity_allowed <= 0:
            equity_w = 0.0
            if fi_allowed:
                fi_w = min(1.0 - risk_budget.min_cash, risk_budget.max_fixed_income)
                cash_w = 1.0 - fi_w
            else:
                fi_w = 0.0
                cash_w = 1.0

        equity_w, fi_w, cash_w = _validate(equity_w, fi_w, cash_w)
        # Enforce min_cash after normalize.
        if cash_w < risk_budget.min_cash:
            need = risk_budget.min_cash - cash_w
            take = min(need, equity_w)
            equity_w -= take
            cash_w += take
            need = risk_budget.min_cash - cash_w
            if need > 0:
                take = min(need, fi_w)
                fi_w -= take
                cash_w += take
            equity_w, fi_w, cash_w = _validate(equity_w, fi_w, cash_w)

        why_cash = self._why_cash(equity_w, fi_w, cash_w, equity_allowed, fi_allowed)
        explanations = [
            why_eq,
            why_fi,
            why_cash,
            (
                f"Профиль {risk_budget.profile_id}: max equity "
                f"{risk_budget.max_equity_weight:.0%}, min cash {risk_budget.min_cash:.0%}."
            ),
        ]

        return InvestmentDecision(
            profile_id=risk_budget.profile_id,
            equity_weight=equity_w,
            fixed_income_weight=fi_w,
            cash_weight=cash_w,
            reason_codes=tuple(dict.fromkeys(reasons)),
            explanations=tuple(explanations),
            warnings=tuple(dict.fromkeys(warnings)),
            status=AllocationStatus.RESEARCH_ONLY,
            why_equity_ru=why_eq,
            why_fixed_income_ru=why_fi,
            why_cash_ru=why_cash,
            limitations=tuple(limitations),
        )

    def _assess_equity(
        self,
        equity: EquityOpportunity | None,
        budget: RiskBudget,
        market: MarketContext,
    ) -> tuple[float, list[str], str]:
        reasons: list[str] = []
        if equity is None:
            reasons.append("insufficient_data:equity_opportunity")
            return 0.0, reasons, "Нет данных Equity Opportunity — доля акций не назначается."

        cal = getattr(equity, "calibration_status", None) or "UNKNOWN"
        conf_level = getattr(equity, "confidence_level", None) or "UNKNOWN"
        conf_reason = getattr(equity, "confidence_reason", None) or ""
        sample_size = getattr(equity, "sample_size", None)

        if conf_level == "UNKNOWN" or equity.prediction_quality is PredictionQuality.UNKNOWN or cal in {
            CalibrationStatus.UNKNOWN.value,
            CalibrationStatus.INSUFFICIENT_SAMPLE.value,
            "UNKNOWN",
            "INSUFFICIENT_SAMPLE",
        }:
            reasons.append("equity_confidence_unknown")
            # Still allow growth/balanced to take equity if excess clears — but capped lower.
            confidence_cap = 0.35 if "GROWTH" in budget.profile_id else 0.25
            reasons.append("equity_capped_due_to_insufficient_calibration")
        elif conf_level == "LOW":
            reasons.append("equity_confidence_low")
            confidence_cap = min(budget.max_equity_weight, 0.40)
        elif conf_level == "MEDIUM":
            reasons.append("equity_confidence_medium")
            confidence_cap = min(budget.max_equity_weight, 0.70)
        elif conf_level == "HIGH":
            reasons.append("equity_confidence_high_research_only")
            confidence_cap = budget.max_equity_weight
        else:
            confidence_cap = 0.25

        if equity.confidence is None:
            reasons.append("confidence_unknown")
            # Do not invent numeric confidence.
        if equity.expected_excess_return is None:
            reasons.append("insufficient_data:equity_expected_excess_return")
            return (
                0.0,
                reasons,
                "Недостаточно подтверждённой ожидаемой премии акций над hurdle.",
            )

        if equity.expected_excess_return < budget.required_equity_premium:
            reasons.append("equity_expected_excess_below_required_premium")
            return (
                0.0,
                reasons,
                "Доля акций снижена, потому что ожидаемая премия над ключевой ставкой "
                "недостаточна относительно текущего risk budget.",
            )

        reasons.append("equity_excess_clears_hurdle")
        target = min(budget.max_equity_weight, confidence_cap)
        why = (
            "Equity имеет ожидаемую премию выше hurdle (research input). "
            f"Confidence={conf_level}, калибровка={cal}"
            + (f", sample_size={sample_size}" if sample_size is not None else "")
            + ". "
        )
        if conf_reason:
            why += conf_reason + " "
        if conf_level in {"UNKNOWN", "LOW"}:
            why += (
                f"Историческая калибровка прогноза недостаточна — Equity capped at {target:.0%}."
            )
        return (
            target,
            reasons,
            why.strip(),
        )

    def _assess_fi(
        self,
        fi: FixedIncomeOpportunity | None,
        budget: RiskBudget,
    ) -> tuple[bool, list[str], str]:
        reasons: list[str] = []
        if fi is None:
            reasons.append("insufficient_data:fixed_income_opportunity")
            return False, reasons, "Нет данных Fixed Income Opportunity."

        if fi.data_quality in {"NOT_READY", "MISSING"}:
            reasons.append("fixed_income_data_not_ready")
            return False, reasons, "Данные облигаций не готовы — FI sleeve недоступен."

        support = getattr(fi, "support_status", None)
        ratio = fi.supported_ratio
        if (support and support not in {"SUPPORTED", "MIXED", "RESEARCH_ONLY"}) or (
            ratio is not None and ratio <= 0
        ):
            # If supported_ratio explicitly zero, block.
            if ratio is not None and ratio <= 0:
                reasons.append("no_supported_bonds")
                return (
                    False,
                    reasons,
                    "Нет SUPPORTED облигаций для research sleeve.",
                )

        if budget.max_credit_risk == "NONE" and fi.credit_quality == "UNKNOWN":
            reasons.append("credit_risk_blocked_by_conservative_budget")
            return (
                False,
                reasons,
                "Консервативный risk budget не допускает UNKNOWN credit quality.",
            )

        if fi.credit_quality == "UNKNOWN":
            reasons.append("credit_quality_unknown_research_only")

        reasons.append("fixed_income_sleeve_available")
        yld = fi.expected_yield
        yld_txt = f"{yld:.1%}" if yld is not None else "не наблюдалась"
        return (
            True,
            reasons,
            f"Fixed Income предлагает наблюдаемую доходность ({yld_txt}) как research-альтернативу; "
            "высокая доходность может отражать высокий риск. "
            + BOND_SAFETY_REMINDER_RU,
        )

    def _why_cash(
        self,
        equity_w: float,
        fi_w: float,
        cash_w: float,
        equity_allowed: float,
        fi_allowed: bool,
    ) -> str:
        if cash_w >= 0.5 and equity_allowed <= 0 and not fi_allowed:
            return "Недостаточно подтверждённых возможностей — капитал в денежной альтернативе CBR."
        if cash_w > 0:
            return (
                f"Cash {cash_w:.0%} удерживается как буфер ликвидности / min_cash risk budget "
                "и остаток после целых лотов."
            )
        return "Целевой cash минимален при текущем профиле."
