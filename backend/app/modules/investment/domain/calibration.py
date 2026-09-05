"""Equity opportunity calibration V0 — read-only analysis of historical forward outcomes.

No retraining. No look-ahead: only EVALUATED outcomes with realized returns already known.
Does not conclude 'model is bad' from a single metric.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CalibrationStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    WEAK = "WEAK"
    ADEQUATE_FOR_RESEARCH = "ADEQUATE_FOR_RESEARCH"


# Predicted return buckets (decimal returns, not percent points).
BUCKET_EDGES: tuple[tuple[str, float | None, float | None], ...] = (
    ("lt_0", None, 0.0),
    ("0_2pct", 0.0, 0.02),
    ("2_5pct", 0.02, 0.05),
    ("5_10pct", 0.05, 0.10),
    ("gt_10pct", 0.10, None),
)


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    name: str
    n: int
    mean_predicted: float | None
    mean_realized: float | None
    hit_rate: float | None  # share with realized > 0 when predicted > 0, else realized < 0
    mean_error: float | None  # realized - predicted


@dataclass(frozen=True, slots=True)
class EquityOpportunityCalibration:
    sample_size: int
    bias: float | None  # mean(realized - predicted)
    mae: float | None
    hit_rate: float | None
    buckets: tuple[CalibrationBucket, ...]
    calibration_status: CalibrationStatus
    uncertainty_note: str
    limitations: tuple[str, ...]
    source: str = "learning.forward_prediction_outcomes"


def _bucket_name(predicted: float) -> str:
    for name, lo, hi in BUCKET_EDGES:
        if lo is None and predicted < (hi or 0):
            return name
        if hi is None and lo is not None and predicted >= lo:
            return name
        if lo is not None and hi is not None and lo <= predicted < hi:
            return name
    return "gt_10pct"


def calibrate_equity_predictions(
    pairs: list[tuple[float, float]],
    *,
    min_adequate: int = 50,
    min_weak: int = 10,
) -> EquityOpportunityCalibration:
    """Calibrate from (predicted, realized) pairs already matured — no future leakage."""
    limitations = [
        "Uses only EVALUATED forward outcomes (realized already known)",
        "RANKING_SCORE predictions must not be treated as percent returns",
        "Single metric alone does not prove the model is good or bad",
        "No model retraining in this layer",
    ]
    if not pairs:
        return EquityOpportunityCalibration(
            sample_size=0,
            bias=None,
            mae=None,
            hit_rate=None,
            buckets=(),
            calibration_status=CalibrationStatus.INSUFFICIENT_SAMPLE,
            uncertainty_note="Нет зрелых predicted/realized пар — доверие к прогнозу UNKNOWN.",
            limitations=tuple(limitations),
        )

    errors = [r - p for p, r in pairs]
    abs_errors = [abs(e) for e in errors]
    dirs = [1.0 if (p >= 0) == (r >= 0) else 0.0 for p, r in pairs]
    bias = sum(errors) / len(errors)
    mae = sum(abs_errors) / len(abs_errors)
    hit = sum(dirs) / len(dirs)

    grouped: dict[str, list[tuple[float, float]]] = {name: [] for name, _, _ in BUCKET_EDGES}
    for p, r in pairs:
        grouped[_bucket_name(p)].append((p, r))

    buckets: list[CalibrationBucket] = []
    for name, _, _ in BUCKET_EDGES:
        rows = grouped[name]
        if not rows:
            buckets.append(
                CalibrationBucket(name, 0, None, None, None, None)
            )
            continue
        preds = [p for p, _ in rows]
        reals = [r for _, r in rows]
        errs = [r - p for p, r in rows]
        hit_b = sum(1.0 if (p >= 0) == (r >= 0) else 0.0 for p, r in rows) / len(rows)
        buckets.append(
            CalibrationBucket(
                name=name,
                n=len(rows),
                mean_predicted=sum(preds) / len(preds),
                mean_realized=sum(reals) / len(reals),
                hit_rate=hit_b,
                mean_error=sum(errs) / len(errs),
            )
        )

    n = len(pairs)
    if n < min_weak:
        status = CalibrationStatus.INSUFFICIENT_SAMPLE
        note = f"Мало наблюдений (n={n}) — confidence остаётся UNKNOWN."
    elif n < min_adequate:
        status = CalibrationStatus.WEAK
        note = (
            f"Выборка ограничена (n={n}). Есть сигналы калибровки, но недостаточно "
            "для сильного доверия — не выдаём fake confidence."
        )
    else:
        status = CalibrationStatus.ADEQUATE_FOR_RESEARCH
        note = (
            f"Выборка n={n} достаточна для research-калибровки. "
            "Это не доказательство боевой точности и не разрешение real money."
        )

    return EquityOpportunityCalibration(
        sample_size=n,
        bias=bias,
        mae=mae,
        hit_rate=hit,
        buckets=tuple(buckets),
        calibration_status=status,
        uncertainty_note=note,
        limitations=tuple(limitations),
    )
