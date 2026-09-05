"""Portfolio Risk Gate V0 — framework-free protective layer.

Pipeline: Opportunity → Risk Checks → Eligibility → Portfolio Candidate

Does not optimize weights. Does not invent SAFE labels.
Yield alone never approves a position.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class PortfolioRiskGateStatus(StrEnum):
    APPROVED = "APPROVED"
    APPROVED_WITH_WARNINGS = "APPROVED_WITH_WARNINGS"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    BLOCKED = "BLOCKED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# Documented research thresholds — not optimized.
DEFAULT_MAX_SINGLE_POSITION = 0.15
DEFAULT_CONCENTRATION_WARN = 0.12
STALE_DAYS_WARN = 5


@dataclass(frozen=True, slots=True)
class PositionRiskInput:
    symbol: str
    sleeve: str  # EQUITY_ALPHA | FIXED_INCOME | CASH
    target_weight: float
    notional: Decimal | None = None
    credit_status: str | None = None
    liquidity_status: str | None = None
    data_quality: str | None = None
    support_status: str | None = None
    investment_eligibility: str | None = None
    days_since_trade: int | None = None
    expected_yield: float | None = None
    risk_flags: tuple[str, ...] = ()
    blocked: bool = False
    block_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PositionRiskVerdict:
    symbol: str
    sleeve: str
    status: PortfolioRiskGateStatus
    reason_codes: tuple[str, ...]
    explanations_ru: tuple[str, ...]
    warnings_ru: tuple[str, ...]
    allowed_in_portfolio: bool
    target_weight: float


@dataclass(frozen=True, slots=True)
class PortfolioRiskAssessment:
    status: PortfolioRiskGateStatus
    capital: Decimal
    positions: tuple[PositionRiskVerdict, ...]
    approved: tuple[str, ...]
    approved_with_warnings: tuple[str, ...]
    research_only: tuple[str, ...]
    blocked: tuple[str, ...]
    insufficient_data: tuple[str, ...]
    reason_codes: tuple[str, ...]
    explanations_ru: tuple[str, ...]
    warnings_ru: tuple[str, ...]
    limitations: tuple[str, ...]
    summary_ru: str


def _worst(*statuses: PortfolioRiskGateStatus) -> PortfolioRiskGateStatus:
    order = [
        PortfolioRiskGateStatus.BLOCKED,
        PortfolioRiskGateStatus.INSUFFICIENT_DATA,
        PortfolioRiskGateStatus.RESEARCH_ONLY,
        PortfolioRiskGateStatus.APPROVED_WITH_WARNINGS,
        PortfolioRiskGateStatus.APPROVED,
    ]
    for status in order:
        if status in statuses:
            return status
    return PortfolioRiskGateStatus.INSUFFICIENT_DATA


class PortfolioRiskGate:
    """Deterministic portfolio admission checks."""

    def __init__(
        self,
        *,
        max_single_position: float = DEFAULT_MAX_SINGLE_POSITION,
        concentration_warn: float = DEFAULT_CONCENTRATION_WARN,
        allow_unknown_credit_research: bool = True,
    ) -> None:
        self.max_single_position = max_single_position
        self.concentration_warn = concentration_warn
        self.allow_unknown_credit_research = allow_unknown_credit_research

    def assess_position(self, position: PositionRiskInput) -> PositionRiskVerdict:
        reasons: list[str] = []
        explanations: list[str] = []
        warnings: list[str] = []
        statuses: list[PortfolioRiskGateStatus] = []

        if position.blocked:
            reasons.append("instrument_explicitly_blocked")
            explanations.append(
                position.block_reason
                or f"{position.symbol}: инструмент явно заблокирован для портфеля."
            )
            return PositionRiskVerdict(
                symbol=position.symbol,
                sleeve=position.sleeve,
                status=PortfolioRiskGateStatus.BLOCKED,
                reason_codes=tuple(reasons),
                explanations_ru=tuple(explanations),
                warnings_ru=(),
                allowed_in_portfolio=False,
                target_weight=position.target_weight,
            )

        if position.sleeve == "CASH":
            return PositionRiskVerdict(
                symbol=position.symbol,
                sleeve=position.sleeve,
                status=PortfolioRiskGateStatus.APPROVED,
                reason_codes=("cash_sleeve_ok",),
                explanations_ru=("Денежная позиция допускается как буфер ликвидности.",),
                warnings_ru=(),
                allowed_in_portfolio=True,
                target_weight=position.target_weight,
            )

        # Data quality
        dq = (position.data_quality or "").upper()
        if dq in {"", "NOT_READY", "MISSING"}:
            reasons.append("insufficient_data_quality")
            explanations.append(
                f"{position.symbol}: недостаточно данных качества — статус INSUFFICIENT_DATA."
            )
            statuses.append(PortfolioRiskGateStatus.INSUFFICIENT_DATA)
        elif dq == "PARTIAL":
            reasons.append("partial_data_quality")
            warnings.append(f"{position.symbol}: данные частичные — требуется осторожность.")
            statuses.append(PortfolioRiskGateStatus.APPROVED_WITH_WARNINGS)

        # Support / accounting
        support = (position.support_status or "").upper()
        if support == "UNSUPPORTED":
            reasons.append("accounting_unsupported")
            explanations.append(
                f"{position.symbol}: accounting не поддерживается — позиция BLOCKED."
            )
            statuses.append(PortfolioRiskGateStatus.BLOCKED)
        elif support in {"RESEARCH_ONLY", ""} and position.sleeve == "FIXED_INCOME":
            reasons.append("accounting_research_only")
            explanations.append(
                f"{position.symbol}: accounting только research — не silent real portfolio."
            )
            statuses.append(PortfolioRiskGateStatus.RESEARCH_ONLY)

        # Credit
        credit = (position.credit_status or "UNKNOWN").upper()
        if position.sleeve == "FIXED_INCOME":
            if credit in {"UNKNOWN", "NOT_RATED"}:
                reasons.append("credit_unknown")
                warnings.append(
                    f"{position.symbol}: кредитное качество неизвестно — "
                    "высокая доходность не означает покупку."
                )
                if self.allow_unknown_credit_research:
                    statuses.append(PortfolioRiskGateStatus.RESEARCH_ONLY)
                    explanations.append(
                        f"{position.symbol}: credit UNKNOWN → RESEARCH_ONLY "
                        "(не BLOCKED, но и не APPROVED)."
                    )
                else:
                    statuses.append(PortfolioRiskGateStatus.BLOCKED)
                    explanations.append(
                        f"{position.symbol}: credit UNKNOWN запрещён профилем риска."
                    )
            elif credit == "STALE":
                reasons.append("credit_stale")
                warnings.append(f"{position.symbol}: рейтинг устарел.")
                statuses.append(PortfolioRiskGateStatus.APPROVED_WITH_WARNINGS)
            elif credit == "CONFLICT":
                reasons.append("credit_conflict")
                warnings.append(f"{position.symbol}: конфликт рейтингов агентств.")
                statuses.append(PortfolioRiskGateStatus.RESEARCH_ONLY)

        # Liquidity
        liq = (position.liquidity_status or "UNKNOWN").upper()
        if liq == "LOW":
            reasons.append("liquidity_low")
            explanations.append(
                f"{position.symbol}: низкая ликвидность — сложно выйти по ожидаемой цене."
            )
            statuses.append(PortfolioRiskGateStatus.BLOCKED)
        elif liq == "UNKNOWN":
            reasons.append("liquidity_unknown")
            warnings.append(f"{position.symbol}: ликвидность неизвестна.")
            statuses.append(PortfolioRiskGateStatus.APPROVED_WITH_WARNINGS)
        elif liq == "MEDIUM":
            reasons.append("liquidity_medium")
            warnings.append(f"{position.symbol}: ликвидность средняя.")
            statuses.append(PortfolioRiskGateStatus.APPROVED_WITH_WARNINGS)

        if position.days_since_trade is not None and position.days_since_trade > STALE_DAYS_WARN:
            reasons.append("stale_market_data")
            warnings.append(
                f"{position.symbol}: данные торгов устарели ({position.days_since_trade} дн.)."
            )
            statuses.append(PortfolioRiskGateStatus.APPROVED_WITH_WARNINGS)

        # Investment eligibility
        elig = (position.investment_eligibility or "").upper()
        if elig == "BLOCKED":
            reasons.append("investment_eligibility_blocked")
            explanations.append(f"{position.symbol}: investment eligibility = BLOCKED.")
            statuses.append(PortfolioRiskGateStatus.BLOCKED)
        elif elig == "RESEARCH_ONLY":
            reasons.append("investment_eligibility_research_only")
            statuses.append(PortfolioRiskGateStatus.RESEARCH_ONLY)

        # Concentration / position size (single-instrument only; sleeves use risk budget elsewhere)
        is_aggregate_sleeve = position.symbol.endswith("_SLEEVE") or position.sleeve == "CASH"
        if not is_aggregate_sleeve and position.target_weight > self.max_single_position + 1e-12:
            reasons.append("concentration_exceeds_max_single_position")
            explanations.append(
                f"{position.symbol}: доля {position.target_weight:.0%} превышает "
                f"лимит позиции {self.max_single_position:.0%} — BLOCKED."
            )
            statuses.append(PortfolioRiskGateStatus.BLOCKED)
        elif not is_aggregate_sleeve and position.target_weight >= self.concentration_warn:
            reasons.append("concentration_near_limit")
            warnings.append(
                f"{position.symbol}: концентрация {position.target_weight:.0%} "
                "близка к лимиту — предупреждение."
            )
            statuses.append(PortfolioRiskGateStatus.APPROVED_WITH_WARNINGS)
        elif is_aggregate_sleeve and position.target_weight > self.max_single_position:
            reasons.append("sleeve_weight_above_single_name_cap")
            warnings.append(
                f"{position.symbol}: вес sleeve {position.target_weight:.0%} выше "
                f"лимита одной бумаги {self.max_single_position:.0%} — нужна диверсификация внутри sleeve."
            )
            statuses.append(PortfolioRiskGateStatus.APPROVED_WITH_WARNINGS)

        # Yield alone never approves
        if position.expected_yield is not None and position.expected_yield >= 0.15:
            if credit in {"UNKNOWN", "NOT_RATED", ""} or liq in {"LOW", "UNKNOWN"}:
                reasons.append("high_yield_without_risk_clearance")
                explanations.append(
                    f"{position.symbol}: доходность {position.expected_yield:.0%} "
                    "не очищена risk gate (credit/liquidity)."
                )
                if PortfolioRiskGateStatus.APPROVED not in statuses:
                    statuses.append(PortfolioRiskGateStatus.RESEARCH_ONLY)

        if position.risk_flags:
            for flag in position.risk_flags:
                if flag in {"CREDIT_UNKNOWN", "LOW_LIQUIDITY", "NO_RATING"}:
                    reasons.append(f"risk_flag:{flag}")

        if not statuses:
            statuses.append(PortfolioRiskGateStatus.APPROVED)
            explanations.append(f"{position.symbol}: проверки риска пройдены для research candidate.")

        status = _worst(*statuses)
        allowed = status in {
            PortfolioRiskGateStatus.APPROVED,
            PortfolioRiskGateStatus.APPROVED_WITH_WARNINGS,
            PortfolioRiskGateStatus.RESEARCH_ONLY,
        }
        # RESEARCH_ONLY is allowed as research candidate, not real-money approve.
        if status is PortfolioRiskGateStatus.RESEARCH_ONLY:
            explanations.append(
                f"{position.symbol}: допускается только как research candidate, не real money."
            )

        return PositionRiskVerdict(
            symbol=position.symbol,
            sleeve=position.sleeve,
            status=status,
            reason_codes=tuple(dict.fromkeys(reasons)),
            explanations_ru=tuple(dict.fromkeys(explanations)),
            warnings_ru=tuple(dict.fromkeys(warnings)),
            allowed_in_portfolio=allowed and status is not PortfolioRiskGateStatus.BLOCKED,
            target_weight=position.target_weight,
        )

    def assess_portfolio(
        self,
        *,
        capital: Decimal,
        positions: list[PositionRiskInput],
    ) -> PortfolioRiskAssessment:
        verdicts = tuple(self.assess_position(p) for p in positions)
        if not verdicts:
            return PortfolioRiskAssessment(
                status=PortfolioRiskGateStatus.INSUFFICIENT_DATA,
                capital=capital,
                positions=(),
                approved=(),
                approved_with_warnings=(),
                research_only=(),
                blocked=(),
                insufficient_data=(),
                reason_codes=("no_positions",),
                explanations_ru=("Нет позиций для проверки риска.",),
                warnings_ru=(),
                limitations=_limitations(),
                summary_ru="Недостаточно данных: нет кандидатов портфеля.",
            )

        buckets = {
            PortfolioRiskGateStatus.APPROVED: [],
            PortfolioRiskGateStatus.APPROVED_WITH_WARNINGS: [],
            PortfolioRiskGateStatus.RESEARCH_ONLY: [],
            PortfolioRiskGateStatus.BLOCKED: [],
            PortfolioRiskGateStatus.INSUFFICIENT_DATA: [],
        }
        reasons: list[str] = []
        explanations: list[str] = []
        warnings: list[str] = []
        for v in verdicts:
            buckets[v.status].append(v.symbol)
            reasons.extend(v.reason_codes)
            explanations.extend(v.explanations_ru)
            warnings.extend(v.warnings_ru)

        status = _worst(*(v.status for v in verdicts))
        summary = {
            PortfolioRiskGateStatus.APPROVED: "Портфель-кандидат допущен risk gate.",
            PortfolioRiskGateStatus.APPROVED_WITH_WARNINGS: (
                "Портфель допущен с предупреждениями — проверьте credit/liquidity/concentration."
            ),
            PortfolioRiskGateStatus.RESEARCH_ONLY: (
                "Портфель только research: есть UNKNOWN credit или research eligibility."
            ),
            PortfolioRiskGateStatus.BLOCKED: (
                "Есть заблокированные позиции — портфель не может быть silent-approved."
            ),
            PortfolioRiskGateStatus.INSUFFICIENT_DATA: (
                "Недостаточно данных для допуска портфеля."
            ),
        }[status]

        return PortfolioRiskAssessment(
            status=status,
            capital=capital,
            positions=verdicts,
            approved=tuple(buckets[PortfolioRiskGateStatus.APPROVED]),
            approved_with_warnings=tuple(buckets[PortfolioRiskGateStatus.APPROVED_WITH_WARNINGS]),
            research_only=tuple(buckets[PortfolioRiskGateStatus.RESEARCH_ONLY]),
            blocked=tuple(buckets[PortfolioRiskGateStatus.BLOCKED]),
            insufficient_data=tuple(buckets[PortfolioRiskGateStatus.INSUFFICIENT_DATA]),
            reason_codes=tuple(dict.fromkeys(reasons)),
            explanations_ru=tuple(dict.fromkeys(explanations)),
            warnings_ru=tuple(dict.fromkeys(warnings)),
            limitations=_limitations(),
            summary_ru=summary,
        )


def _limitations() -> tuple[str, ...]:
    return (
        "Portfolio Risk Gate V0 — research protective layer",
        "No ML / no optimization / no broker / no real money",
        "Yield alone never approves a position",
        "UNKNOWN credit is a warning path (RESEARCH_ONLY), not fake SAFE",
    )
