"""Rule-based TechnicalModel implementation (rules_v1) — pure, no I/O."""

from __future__ import annotations

from typing import Any

from app.domain.ports.technical import (
    FactorContributions,
    SignalDirection,
    TechnicalModel,
    TechnicalModelInput,
    TechnicalModelOutput,
    TechnicalQualityContext,
)
from app.modules.technical.technical_config import (
    RULES_V1_CODE,
    RULES_V1_CONFIG,
    RULES_V1_CONFIG_HASH,
    RULES_V1_VERSION,
    config_hash,
)


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class RuleBasedTechnicalModel(TechnicalModel):
    """Heuristic baseline technical state model. Not ML. Not a trade recommendation."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config or RULES_V1_CONFIG)
        self.model_code = RULES_V1_CODE
        self.model_version = RULES_V1_VERSION
        self.config_hash = config_hash(self.config)

    def predict(self, model_input: TechnicalModelInput) -> TechnicalModelOutput:
        cfg = self.config
        feats = model_input.features
        quality = model_input.quality

        trend_parts: list[float] = []
        if feats.sma20_distance is not None:
            trend_parts.append(_clip(feats.sma20_distance / float(cfg["distance_scale"]), -1.0, 1.0))
        if feats.ema20_distance is not None:
            trend_parts.append(_clip(feats.ema20_distance / float(cfg["distance_scale"]), -1.0, 1.0))
        trend_factor = sum(trend_parts) / len(trend_parts) if trend_parts else None

        mom_parts: list[tuple[float, float]] = []
        if feats.return_5d is not None:
            mom_parts.append(
                (
                    float(cfg["momentum_return_5d_weight"]),
                    _clip(feats.return_5d / float(cfg["return_scale"]), -1.0, 1.0),
                )
            )
        if feats.return_20d is not None:
            mom_parts.append(
                (
                    float(cfg["momentum_return_20d_weight"]),
                    _clip(feats.return_20d / float(cfg["return_scale"]), -1.0, 1.0),
                )
            )
        if mom_parts:
            w_sum = sum(w for w, _ in mom_parts)
            momentum_factor = sum(w * v for w, v in mom_parts) / w_sum if w_sum else None
        else:
            momentum_factor = None

        rsi_factor = None
        if feats.rsi14 is not None:
            rsi_factor = _clip(
                (feats.rsi14 - float(cfg["rsi_center"])) / float(cfg["rsi_scale"]),
                -1.0,
                1.0,
            )

        volume_factor: float | None
        if feats.volume_zscore_20d is None or momentum_factor is None:
            volume_factor = None
        elif feats.volume_zscore_20d <= 0:
            volume_factor = 0.0
        else:
            sign = 1.0 if momentum_factor > 0 else (-1.0 if momentum_factor < 0 else 0.0)
            volume_factor = sign * _clip(feats.volume_zscore_20d / float(cfg["volume_scale"]), 0.0, 1.0)

        factors = {
            "trend": trend_factor,
            "momentum": momentum_factor,
            "rsi": rsi_factor,
            "volume": volume_factor,
        }
        weights = {
            "trend": float(cfg["trend_weight"]),
            "momentum": float(cfg["momentum_weight"]),
            "rsi": float(cfg["rsi_weight"]),
            "volume": float(cfg["volume_weight"]),
        }

        available = {k: v for k, v in factors.items() if v is not None}
        required = list(cfg.get("required_factors", ["trend", "momentum", "rsi", "volume"]))
        coverage_ratio = sum(1 for k in required if k in available) / max(len(required), 1)

        critical = bool(quality.critical or quality.quality_flags.get("price_discontinuity"))
        if critical or not quality.is_valid:
            quality_factor = 0.0
            is_valid = False
        elif quality.quality_flags:
            quality_factor = 0.7
            is_valid = True
        else:
            quality_factor = 1.0
            is_valid = True

        if available and sum(weights[k] for k in available) > 0:
            w_sum = sum(weights[k] for k in available)
            score = sum(weights[k] * available[k] for k in available) / w_sum
        else:
            score = 0.0
        score = _clip(score, -1.0, 1.0)

        bullish_th = float(cfg["bullish_threshold"])
        bearish_th = float(cfg["bearish_threshold"])
        if not is_valid:
            direction = SignalDirection.NEUTRAL
        elif score >= bullish_th:
            direction = SignalDirection.BULLISH
        elif score <= bearish_th:
            direction = SignalDirection.BEARISH
        else:
            direction = SignalDirection.NEUTRAL

        agreement = 0.5 + 0.5 * abs(score)
        confidence = _clip(coverage_ratio * agreement * quality_factor, 0.0, 1.0)

        return TechnicalModelOutput(
            instrument_id=model_input.instrument_id,
            ticker=model_input.ticker,
            as_of_date=model_input.as_of_date,
            score=score,
            confidence=confidence,
            direction=direction,
            model_code=self.model_code,
            model_version=self.model_version,
            basic_feature_set_ref=model_input.basic_feature_set_ref,
            technical_feature_set_ref=model_input.technical_feature_set_ref,
            factor_contributions=FactorContributions(
                trend=trend_factor,
                momentum=momentum_factor,
                rsi=rsi_factor,
                volume=volume_factor,
            ),
            is_valid=is_valid,
            quality_summary=TechnicalQualityContext(
                is_valid=is_valid,
                has_sufficient_history=quality.has_sufficient_history and coverage_ratio >= 1.0,
                quality_flags=dict(quality.quality_flags),
                critical=critical,
            ),
            metadata={
                "impl": "rules",
                "config_hash": self.config_hash,
                "coverage_ratio": coverage_ratio,
                "quality_factor": quality_factor,
                "agreement_component": agreement,
            },
        )


# Re-export for infrastructure.ml compatibility
__all__ = ["RuleBasedTechnicalModel", "RULES_V1_CONFIG_HASH"]
