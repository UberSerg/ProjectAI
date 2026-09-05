"""Prediction Confidence Engine V1 — deterministic rules, not optimized.

Maps calibration evidence → ConfidenceAssessment.
Never invents HIGH without strict evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.modules.prediction.domain.calibration_v1 import (
    CalibrationStatus,
    PredictionCalibration,
    RankingCalibration,
)


class ConfidenceLevel(StrEnum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# Documented thresholds — not historically optimized.
MIN_SAMPLE_UNKNOWN = 10
MIN_SAMPLE_MEDIUM = 50
MIN_SAMPLE_HIGH = 200
MAX_MAE_MEDIUM = 0.05
MAX_ABS_BIAS_MEDIUM = 0.03
MIN_DIRECTION_MEDIUM = 0.50
MAX_MAE_HIGH = 0.025
MAX_ABS_BIAS_HIGH = 0.015
MIN_DIRECTION_HIGH = 0.55


@dataclass(frozen=True, slots=True)
class ConfidenceAssessment:
    confidence_level: ConfidenceLevel
    confidence_status: str  # READY | RESEARCH_ONLY | INSUFFICIENT_DATA
    reason_codes: tuple[str, ...]
    reason_ru: str
    limitations: tuple[str, ...]
    sample_size: int
    calibration_status: str


@dataclass(frozen=True, slots=True)
class ConfidenceInputs:
    calibration: PredictionCalibration | None
    data_quality_ok: bool = True
    model_status: str = "RESEARCH"  # RESEARCH | FROZEN | UNKNOWN


class PredictionConfidenceEngine:
    """Deterministic confidence from calibration evidence."""

    def assess(self, inputs: ConfidenceInputs) -> ConfidenceAssessment:
        cal = inputs.calibration
        limitations = [
            "Confidence is not probability of profit",
            "Thresholds are documented research rules, not optimized",
            "HIGH requires strict evidence and is rare by design",
            "No broker / real-money authorization",
        ]
        if cal is None:
            return ConfidenceAssessment(
                confidence_level=ConfidenceLevel.UNKNOWN,
                confidence_status="INSUFFICIENT_DATA",
                reason_codes=("missing_calibration",),
                reason_ru="Нет истории калибровки — уверенность UNKNOWN.",
                limitations=tuple(limitations),
                sample_size=0,
                calibration_status=CalibrationStatus.UNKNOWN.value,
            )

        limitations = list(limitations) + list(cal.limitations)
        reasons: list[str] = []
        n = cal.sample_count
        status = cal.calibration_status

        if not inputs.data_quality_ok:
            reasons.append("data_quality_weak")
            return ConfidenceAssessment(
                confidence_level=ConfidenceLevel.UNKNOWN,
                confidence_status="INSUFFICIENT_DATA",
                reason_codes=tuple(reasons + ["confidence_unknown_data_quality"]),
                reason_ru="Качество данных недостаточно — confidence UNKNOWN.",
                limitations=tuple(limitations),
                sample_size=n,
                calibration_status=status.value,
            )

        if n < MIN_SAMPLE_UNKNOWN or status in {
            CalibrationStatus.UNKNOWN,
            CalibrationStatus.INSUFFICIENT_SAMPLE,
        }:
            reasons.extend(["insufficient_sample", "no_calibration_history"])
            return ConfidenceAssessment(
                confidence_level=ConfidenceLevel.UNKNOWN,
                confidence_status="INSUFFICIENT_DATA",
                reason_codes=tuple(dict.fromkeys(reasons)),
                reason_ru=(
                    f"Недостаточно зрелых прогнозов (n={n}). "
                    "Пока нельзя честно оценить, насколько часто сбываются ожидания модели."
                ),
                limitations=tuple(limitations),
                sample_size=n,
                calibration_status=status.value,
            )

        mae = cal.mae
        bias = cal.bias
        direction = cal.direction_accuracy
        abs_bias = abs(bias) if bias is not None else None

        # HIGH — strict only
        if (
            n >= MIN_SAMPLE_HIGH
            and status is CalibrationStatus.ADEQUATE_FOR_RESEARCH
            and mae is not None
            and mae <= MAX_MAE_HIGH
            and abs_bias is not None
            and abs_bias <= MAX_ABS_BIAS_HIGH
            and direction is not None
            and direction >= MIN_DIRECTION_HIGH
            and inputs.model_status in {"RESEARCH", "FROZEN"}
        ):
            reasons.append("strict_high_criteria_met")
            return ConfidenceAssessment(
                confidence_level=ConfidenceLevel.HIGH,
                confidence_status="RESEARCH_ONLY",
                reason_codes=tuple(reasons),
                reason_ru=(
                    "Строгие research-критерии выполнены: большая выборка, низкая ошибка "
                    "и умеренный bias. Это всё ещё не разрешение real money."
                ),
                limitations=tuple(limitations),
                sample_size=n,
                calibration_status=status.value,
            )

        # MEDIUM
        if (
            n >= MIN_SAMPLE_MEDIUM
            and status is CalibrationStatus.ADEQUATE_FOR_RESEARCH
            and mae is not None
            and mae <= MAX_MAE_MEDIUM
            and abs_bias is not None
            and abs_bias <= MAX_ABS_BIAS_MEDIUM
            and direction is not None
            and direction >= MIN_DIRECTION_MEDIUM
        ):
            reasons.append("adequate_sample_stable_calibration")
            if bias is not None and bias < -0.01:
                reasons.append("negative_bias_model_overestimates")
            elif bias is not None and bias > 0.01:
                reasons.append("positive_bias_model_underestimates")
            return ConfidenceAssessment(
                confidence_level=ConfidenceLevel.MEDIUM,
                confidence_status="RESEARCH_ONLY",
                reason_codes=tuple(reasons),
                reason_ru=(
                    f"Достаточная выборка (n={n}) и относительно стабильная калибровка. "
                    "Доверие среднее — прогноз всё ещё не гарантия."
                ),
                limitations=tuple(limitations),
                sample_size=n,
                calibration_status=status.value,
            )

        # LOW — some data but weak / high error
        reasons.append("sample_present_but_weak_or_noisy")
        if mae is not None and mae > MAX_MAE_MEDIUM:
            reasons.append("high_prediction_error")
        if abs_bias is not None and abs_bias > MAX_ABS_BIAS_MEDIUM:
            reasons.append("elevated_bias")
        if status is CalibrationStatus.WEAK:
            reasons.append("calibration_status_weak")
        return ConfidenceAssessment(
            confidence_level=ConfidenceLevel.LOW,
            confidence_status="RESEARCH_ONLY",
            reason_codes=tuple(dict.fromkeys(reasons)),
            reason_ru=(
                f"Есть зрелые исходы (n={n}), но ошибка/bias/стабильность не позволяют "
                "поднять доверие выше LOW. Если прогнозы систематически выше реальности, "
                "Kraken уменьшает доверие к ним."
            ),
            limitations=tuple(limitations),
            sample_size=n,
            calibration_status=status.value,
        )

    def assess_ranking(self, ranking: RankingCalibration | None) -> ConfidenceAssessment:
        """Separate ranking confidence — never reuse return MAE rules on scores."""
        limitations = (
            "Ranking confidence ≠ expected-return confidence",
            "No automatic winner selection vs V0",
        )
        if ranking is None or ranking.sample_count < MIN_SAMPLE_UNKNOWN:
            n = 0 if ranking is None else ranking.sample_count
            return ConfidenceAssessment(
                confidence_level=ConfidenceLevel.UNKNOWN,
                confidence_status="INSUFFICIENT_DATA",
                reason_codes=("insufficient_ranking_sample",),
                reason_ru="Мало зрелых ranking outcomes — ranking confidence UNKNOWN.",
                limitations=limitations,
                sample_size=n,
                calibration_status=(
                    CalibrationStatus.INSUFFICIENT_SAMPLE.value
                    if ranking is None
                    else ranking.calibration_status.value
                ),
            )
        if ranking.calibration_status is CalibrationStatus.ADEQUATE_FOR_RESEARCH:
            return ConfidenceAssessment(
                confidence_level=ConfidenceLevel.MEDIUM,
                confidence_status="RESEARCH_ONLY",
                reason_codes=("ranking_sample_adequate_research",),
                reason_ru="Достаточная ranking-выборка для research quality (не return %).",
                limitations=limitations + tuple(ranking.limitations),
                sample_size=ranking.sample_count,
                calibration_status=ranking.calibration_status.value,
            )
        return ConfidenceAssessment(
            confidence_level=ConfidenceLevel.LOW,
            confidence_status="RESEARCH_ONLY",
            reason_codes=("ranking_sample_weak",),
            reason_ru="Ranking quality сигналов мало — доверие LOW.",
            limitations=limitations + tuple(ranking.limitations),
            sample_size=ranking.sample_count,
            calibration_status=ranking.calibration_status.value,
        )
