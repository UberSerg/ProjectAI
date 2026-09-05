"""Equity opportunity calibration V0 — thin adapter over Prediction Calibration V1.

Keeps Risk & Opportunity Engine imports stable while buckets/confidence live in prediction.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.prediction.domain.calibration_v1 import (
    BUCKET_EDGES,
    CalibrationStatus,
    calibrate_expected_return,
)


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    name: str
    n: int
    mean_predicted: float | None
    mean_realized: float | None
    hit_rate: float | None
    mean_error: float | None


@dataclass(frozen=True, slots=True)
class EquityOpportunityCalibration:
    sample_size: int
    bias: float | None
    mae: float | None
    hit_rate: float | None
    buckets: tuple[CalibrationBucket, ...]
    calibration_status: CalibrationStatus
    uncertainty_note: str
    limitations: tuple[str, ...]
    source: str = "learning.forward_prediction_outcomes"


def calibrate_equity_predictions(
    pairs: list[tuple[float, float]],
    *,
    min_adequate: int = 50,
    min_weak: int = 10,
) -> EquityOpportunityCalibration:
    cal = calibrate_expected_return(pairs, min_adequate=min_adequate, min_weak=min_weak)
    buckets = tuple(
        CalibrationBucket(
            name=b.bucket_name,
            n=b.sample_count,
            mean_predicted=b.average_prediction,
            mean_realized=b.average_realized_return,
            hit_rate=b.win_rate,
            mean_error=b.bias,
        )
        for b in cal.buckets
    )
    return EquityOpportunityCalibration(
        sample_size=cal.sample_count,
        bias=cal.bias,
        mae=cal.mae,
        hit_rate=cal.direction_accuracy,
        buckets=buckets,
        calibration_status=cal.calibration_status,
        uncertainty_note=cal.uncertainty_note,
        limitations=cal.limitations,
        source=cal.source,
    )


__all__ = [
    "BUCKET_EDGES",
    "CalibrationBucket",
    "CalibrationStatus",
    "EquityOpportunityCalibration",
    "calibrate_equity_predictions",
]
