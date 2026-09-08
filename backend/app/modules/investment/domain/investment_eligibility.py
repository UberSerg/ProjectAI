"""Investment eligibility V0 — accounting quality vs investment quality.

Accounting = can we compute price/coupons/cashflows.
Investment = is the instrument suitable for a defensive sleeve.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.modules.investment.domain.credit_quality import CreditQualityAssessment, CreditStatus, RiskFlag
from app.modules.investment.domain.liquidity import LiquidityAssessment, LiquidityStatus


class EligibilityStatus(StrEnum):
    REAL_PORTFOLIO_CANDIDATE = "REAL_PORTFOLIO_CANDIDATE"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class InvestmentEligibilityAssessment:
    instrument_id: int
    eligible: bool
    status: EligibilityStatus
    accounting_supported: bool
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    risk_flags: tuple[str, ...]


def assess_investment_eligibility(
    *,
    instrument_id: int,
    support_status: str,
    credit: CreditQualityAssessment,
    liquidity: LiquidityAssessment,
    bond_type: str,
) -> InvestmentEligibilityAssessment:
    reasons: list[str] = []
    warnings: list[str] = []
    flags = list(credit.risk_flags) + list(liquidity.risk_flags)

    accounting_ok = support_status == "SUPPORTED"
    if not accounting_ok:
        reasons.append("accounting_not_supported")
        flags.append(RiskFlag.ACCOUNTING_UNSUPPORTED.value)

    # Government debt is a category, not a CRA rating — accounting may be OK for research.
    is_gov = credit.credit_status is CreditStatus.GOVERNMENT_RUSSIAN_FEDERAL
    credit_ok = is_gov or credit.credit_status in {
        CreditStatus.AVAILABLE,
        CreditStatus.CURRENT_RATING_AVAILABLE,
    }
    if is_gov:
        reasons.append("government_debt_category")
        warnings.append(
            "ОФЗ / госдолг РФ — категория суверенного долга, не корпоративный рейтинг агентства."
        )
    elif credit.credit_status is CreditStatus.SOURCE_NOT_READY:
        reasons.append("credit_source_not_ready")
        warnings.append(
            "Источник кредитных рейтингов недоступен (требуется коммерческий доступ) — "
            "это не то же самое, что «рейтинг не найден»."
        )
    elif credit.credit_status in {
        CreditStatus.UNKNOWN,
        CreditStatus.NOT_RATED,
        CreditStatus.NO_RATING_FOUND,
    }:
        reasons.append("credit_unknown_or_not_rated")
        warnings.append(
            "Кредитное качество неизвестно — высокая доходность может отражать высокий риск."
        )
    elif credit.credit_status is CreditStatus.STALE:
        reasons.append("credit_rating_stale")
        warnings.append("Рейтинг устарел — требуется проверка свежести.")
    elif credit.credit_status is CreditStatus.CONFLICT:
        reasons.append("credit_rating_conflict")
        warnings.append("Конфликт рейтингов агентств — без mapping не сравниваем.")
    elif credit.credit_status is CreditStatus.MAPPING_FAILED:
        reasons.append("credit_mapping_failed")
        warnings.append("Не удалось сопоставить рейтинг с инструментом.")

    if bond_type == "Corporate" and not credit_ok and not is_gov:
        warnings.append(
            "Корпоративная облигация без подтверждённого рейтинга не годится для silent real portfolio."
        )

    liq_ok = liquidity.liquidity_status in {LiquidityStatus.GOOD, LiquidityStatus.MEDIUM}
    if liquidity.liquidity_status is LiquidityStatus.LOW:
        reasons.append("liquidity_low")
        warnings.append("Низкая ликвидность — выход из позиции может быть затруднён.")
    elif liquidity.liquidity_status is LiquidityStatus.UNKNOWN:
        reasons.append("liquidity_unknown")
        warnings.append("Ликвидность неизвестна — нет достаточных данных о торгах.")

    # Never auto-promote to real portfolio without credit AVAILABLE.
    if accounting_ok and credit_ok and liq_ok:
        status = EligibilityStatus.REAL_PORTFOLIO_CANDIDATE
        eligible = True
    elif support_status in {"SUPPORTED", "RESEARCH_ONLY"}:
        status = EligibilityStatus.RESEARCH_ONLY
        eligible = False
        reasons.append("research_only_investment_quality")
    else:
        status = EligibilityStatus.BLOCKED
        eligible = False
        reasons.append("blocked_unsupported_or_unsafe")

    return InvestmentEligibilityAssessment(
        instrument_id=instrument_id,
        eligible=eligible,
        status=status,
        accounting_supported=accounting_ok,
        reason_codes=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
        risk_flags=tuple(dict.fromkeys(flags)),
    )
