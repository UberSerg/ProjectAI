"""Registered Research Lab options (versioned policies — no tunable knobs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG, HOLDOUT_START
from app.modules.simulator.config import (
    CANONICAL_INITIAL_CAPITAL,
    CANONICAL_MAX_SINGLE_WEIGHT,
    POLICY_HYSTERESIS_V1,
    POLICY_NAME,
    RISK_DD_GUARD_V1,
    RISK_NAME,
    V1_DD_NORMAL_GROSS,
    V1_DD_RECOVERY,
    V1_DD_RISK_OFF_GROSS,
    V1_DD_TRIGGER,
    V1_ENTRY_QUANTILE,
    V1_EXIT_QUANTILE,
    V1_MIN_TRADE_WEIGHT_DELTA,
    hysteresis_dd_v1_spec_kwargs,
    hysteresis_v1_spec_kwargs,
)

ALLOWED_RESEARCH_SEGMENT = "DEVELOPMENT_OOS"
PROTECTED_SEGMENT = "FINAL_HOLDOUT"

COST_PRESETS_BPS: tuple[float, ...] = (0.0, 5.0, 10.0, 20.0)
CUSTOM_COST_MIN_BPS = 0.0
CUSTOM_COST_MAX_BPS = 100.0
CAPITAL_MIN = 10_000.0
CAPITAL_MAX = 100_000_000.0

# Quick comparison suite fixed matrix (≤12 configs).
QUICK_SUITE_VARIANTS: tuple[tuple[str, str], ...] = (
    (POLICY_NAME, RISK_NAME),
    (POLICY_HYSTERESIS_V1, RISK_NAME),
    (POLICY_HYSTERESIS_V1, RISK_DD_GUARD_V1),
)


@dataclass(frozen=True, slots=True)
class CandidateOption:
    id: str
    candidate_name: str
    candidate_version: str
    human_name: str
    technical_line: str
    research_verdict: str
    model_type: str
    target_label: str
    eligible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "candidate_name": self.candidate_name,
            "candidate_version": self.candidate_version,
            "human_name": self.human_name,
            "technical_line": self.technical_line,
            "research_verdict": self.research_verdict,
            "model_type": self.model_type,
            "target_label": self.target_label,
            "eligible": self.eligible,
            "help_id": "candidate_model",
        }


@dataclass(frozen=True, slots=True)
class PolicyOption:
    id: str
    human_name: str
    description: str
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "technical_id": self.id,
            "human_name": self.human_name,
            "description": self.description,
            "parameters": self.parameters,
            "help_id": "portfolio_policy",
            "frozen": True,
        }


@dataclass(frozen=True, slots=True)
class RiskOption:
    id: str
    human_name: str
    description: str
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "technical_id": self.id,
            "human_name": self.human_name,
            "description": self.description,
            "parameters": self.parameters,
            "help_id": "risk_policy",
            "frozen": True,
        }


def list_candidates() -> list[CandidateOption]:
    """Future Candidate V1+ append here / via registry — Lab does not hardcode forever."""
    return [
        CandidateOption(
            id=f"{CANDIDATE_V0_CONFIG.candidate_name}/{CANDIDATE_V0_CONFIG.candidate_version}",
            candidate_name=CANDIDATE_V0_CONFIG.candidate_name,
            candidate_version=CANDIDATE_V0_CONFIG.candidate_version,
            human_name="Модель прогнозирования V0",
            technical_line="CatBoostRegressor · 20 trading days",
            research_verdict="MIXED",
            model_type="CatBoostRegressor",
            target_label=CANDIDATE_V0_CONFIG.target,
            eligible=True,
        )
    ]


def list_policies() -> list[PolicyOption]:
    return [
        PolicyOption(
            id=POLICY_NAME,
            human_name="Базовая рейтинговая",
            description=(
                "Каждую неделю выбирает верхние 20% рейтинга модели "
                "и распределяет капитал поровну."
            ),
            parameters={
                "top_quantile": 0.20,
                "rebalance": "weekly_first_trading_day",
                "weighting": "equal_weight",
            },
        ),
        PolicyOption(
            id=POLICY_HYSTERESIS_V1,
            human_name="Рейтинговая с удержанием",
            description=(
                "Новые позиции входят из Top 20%, но существующие сохраняются "
                "до выхода за Top 35%. Это уменьшает лишнюю ротацию портфеля."
            ),
            parameters={
                "entry_quantile": V1_ENTRY_QUANTILE,
                "exit_quantile": V1_EXIT_QUANTILE,
                "min_trade_weight_delta": V1_MIN_TRADE_WEIGHT_DELTA,
                "rebalance": "weekly_first_trading_day",
                "weighting": "equal_weight",
            },
        ),
    ]


def list_risks() -> list[RiskOption]:
    return [
        RiskOption(
            id=RISK_NAME,
            human_name="Базовые ограничения",
            description=(
                "Без плеча, только long, максимальная доля одного инструмента 20%."
            ),
            parameters={
                "long_only": True,
                "max_gross_exposure": 1.0,
                "max_single_weight": CANONICAL_MAX_SINGLE_WEIGHT,
            },
        ),
        RiskOption(
            id=RISK_DD_GUARD_V1,
            human_name="Защита от глубокой просадки",
            description=(
                "При просадке портфеля ниже -20% ограничивает рыночную экспозицию до 50%. "
                "После восстановления выше -10% разрешает вернуть экспозицию до 100%."
            ),
            parameters={
                "dd_trigger": V1_DD_TRIGGER,
                "dd_recovery": V1_DD_RECOVERY,
                "dd_risk_off_gross": V1_DD_RISK_OFF_GROSS,
                "dd_normal_gross": V1_DD_NORMAL_GROSS,
                "base_guardrails": RISK_NAME,
            },
        ),
    ]


def cost_preset_dicts() -> list[dict[str, Any]]:
    labels = {
        0.0: "0 bps — без издержек",
        5.0: "5 bps — низкие условные издержки",
        10.0: "10 bps — умеренные условные издержки",
        20.0: "20 bps — высокие условные издержки",
    }
    return [
        {
            "bps": bps,
            "human_label": labels[bps],
            "preset": True,
            "help_id": "simulation_cost",
        }
        for bps in COST_PRESETS_BPS
    ]


def resolve_policy_risk_kwargs(policy_id: str, risk_id: str) -> dict[str, Any]:
    """Map registered versioned IDs to SimulationSpec kwargs."""
    policy_ids = {p.id for p in list_policies()}
    risk_ids = {r.id for r in list_risks()}
    if policy_id not in policy_ids:
        from app.modules.research_lab.errors import UnknownPolicy

        raise UnknownPolicy(f"Неизвестная портфельная стратегия: {policy_id}")
    if risk_id not in risk_ids:
        from app.modules.research_lab.errors import UnknownRisk

        raise UnknownRisk(f"Неизвестная risk-политика: {risk_id}")

    if policy_id == POLICY_NAME and risk_id == RISK_NAME:
        return {"policy_name": POLICY_NAME, "risk_name": RISK_NAME}
    if policy_id == POLICY_NAME and risk_id == RISK_DD_GUARD_V1:
        return {
            "policy_name": POLICY_NAME,
            "risk_name": RISK_DD_GUARD_V1,
            "dd_trigger": V1_DD_TRIGGER,
            "dd_recovery": V1_DD_RECOVERY,
            "dd_risk_off_gross": V1_DD_RISK_OFF_GROSS,
            "dd_normal_gross": V1_DD_NORMAL_GROSS,
        }
    if policy_id == POLICY_HYSTERESIS_V1 and risk_id == RISK_NAME:
        return hysteresis_v1_spec_kwargs()
    if policy_id == POLICY_HYSTERESIS_V1 and risk_id == RISK_DD_GUARD_V1:
        return hysteresis_dd_v1_spec_kwargs()

    from app.modules.research_lab.errors import UnsupportedPolicyRisk

    raise UnsupportedPolicyRisk(
        f"Комбинация {policy_id} + {risk_id} не поддерживается",
        details={"policy_id": policy_id, "risk_id": risk_id},
    )


def display_name_from_config(
    *,
    policy_id: str,
    risk_id: str,
    commission_bps: float,
    date_from: str | None,
    date_to: str | None,
) -> str:
    policy_map = {p.id: p.human_name for p in list_policies()}
    policy_short = {
        POLICY_NAME: "Baseline",
        POLICY_HYSTERESIS_V1: "Hysteresis",
    }.get(policy_id, policy_map.get(policy_id, policy_id))
    risk_bit = ""
    if risk_id == RISK_DD_GUARD_V1:
        risk_bit = " · DD Guard"
    bps = int(commission_bps) if float(commission_bps).is_integer() else commission_bps
    period = ""
    if date_from and date_to:
        period = f" · {date_from[:4]}–{date_to[:4]}"
    return f"{policy_short}{risk_bit} · {bps} bps{period}"


def holdout_boundary() -> str:
    return HOLDOUT_START.isoformat()


def default_capital() -> float:
    return CANONICAL_INITIAL_CAPITAL
