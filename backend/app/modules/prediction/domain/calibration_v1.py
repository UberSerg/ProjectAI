"""Prediction Calibration V1 — framework-free domain.

Shows how often predicted expected returns match realized outcomes.
Does not retrain models. Only matured EVALUATED pairs (no future leakage).
RANKING_SCORE must never be calibrated as percent return.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from statistics import median


class CalibrationStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    WEAK = "WEAK"
    ADEQUATE_FOR_RESEARCH = "ADEQUATE_FOR_RESEARCH"


class PredictionSemantic(StrEnum):
    EXPECTED_RETURN = "EXPECTED_RETURN"
    RANKING_SCORE = "RANKING_SCORE"


# Versioned bucket edges for EXPECTED_RETURN calibration — do not change historically.
BUCKET_SPEC_VERSION = "expected_return_buckets_v1"
BUCKET_EDGES: tuple[tuple[str, float | None, float | None], ...] = (
    ("lt_0", None, 0.0),
    ("0_2pct", 0.0, 0.02),
    ("2_5pct", 0.02, 0.05),
    ("5_10pct", 0.05, 0.10),
    ("gt_10pct", 0.10, None),
)


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    bucket_name: str
    prediction_min: float | None
    prediction_max: float | None
    sample_count: int
    average_prediction: float | None
    average_realized_return: float | None
    median_realized_return: float | None
    error: float | None  # mean abs(predicted - realized)
    bias: float | None  # mean(realized - predicted)
    win_rate: float | None  # direction hit within bucket


@dataclass(frozen=True, slots=True)
class PredictionCalibration:
    candidate: str
    model_version: str
    prediction_period: str
    sample_count: int
    pending_count: int
    coverage: float | None  # evaluated / (evaluated + pending)
    calibration_status: CalibrationStatus
    prediction_semantic: str
    bias: float | None
    mae: float | None
    direction_accuracy: float | None
    buckets: tuple[CalibrationBucket, ...]
    bucket_spec_version: str
    uncertainty_note: str
    limitations: tuple[str, ...]
    created_at: datetime
    source: str = "learning.forward_prediction_outcomes"


@dataclass(frozen=True, slots=True)
class RankingCalibration:
    """Separate ranking quality — never treated as expected-return calibration."""

    candidate: str
    model_version: str
    sample_count: int
    pending_count: int
    coverage: float | None
    mean_spearman_rank_ic: float | None
    mean_top20_realized: float | None
    mean_bottom20_realized: float | None
    mean_top_minus_bottom: float | None
    rank_bucket_realized: tuple[dict[str, float | int | None], ...]
    calibration_status: CalibrationStatus
    uncertainty_note: str
    limitations: tuple[str, ...]
    created_at: datetime
    prediction_semantic: str = PredictionSemantic.RANKING_SCORE.value


def bucket_name_for_prediction(predicted: float) -> str:
    for name, lo, hi in BUCKET_EDGES:
        if lo is None and predicted < (hi or 0):
            return name
        if hi is None and lo is not None and predicted >= lo:
            return name
        if lo is not None and hi is not None and lo <= predicted < hi:
            return name
    return "gt_10pct"


def _direction_hit(predicted: float, realized: float) -> float:
    return 1.0 if (predicted >= 0) == (realized >= 0) else 0.0


def calibrate_expected_return(
    pairs: list[tuple[float, float]],
    *,
    candidate: str = "prediction_ml_candidate",
    model_version: str = "v0",
    prediction_period: str = "forward_20d",
    pending_count: int = 0,
    min_adequate: int = 50,
    min_weak: int = 10,
) -> PredictionCalibration:
    """Calibrate EXPECTED_RETURN from matured (predicted, realized) pairs only."""
    now = datetime.now(UTC)
    limitations = (
        "Uses only EVALUATED outcomes after 20 trading observations",
        "Pending / immature predictions are excluded (no look-ahead)",
        "RANKING_SCORE must not use these return buckets",
        "Single metric alone does not prove the model is good or bad",
        "No model retraining in this layer",
        f"Bucket edges frozen as {BUCKET_SPEC_VERSION}",
    )
    total_known = len(pairs) + max(0, pending_count)
    coverage = (len(pairs) / total_known) if total_known else None

    empty_buckets = tuple(
        CalibrationBucket(name, lo, hi, 0, None, None, None, None, None, None)
        for name, lo, hi in BUCKET_EDGES
    )
    if not pairs:
        return PredictionCalibration(
            candidate=candidate,
            model_version=model_version,
            prediction_period=prediction_period,
            sample_count=0,
            pending_count=pending_count,
            coverage=coverage,
            calibration_status=CalibrationStatus.INSUFFICIENT_SAMPLE,
            prediction_semantic=PredictionSemantic.EXPECTED_RETURN.value,
            bias=None,
            mae=None,
            direction_accuracy=None,
            buckets=empty_buckets,
            bucket_spec_version=BUCKET_SPEC_VERSION,
            uncertainty_note="Нет зрелых predicted/realized пар — доверие к прогнозу UNKNOWN.",
            limitations=limitations,
            created_at=now,
        )

    errors = [r - p for p, r in pairs]
    abs_errors = [abs(e) for e in errors]
    dirs = [_direction_hit(p, r) for p, r in pairs]
    bias = sum(errors) / len(errors)
    mae = sum(abs_errors) / len(abs_errors)
    hit = sum(dirs) / len(dirs)

    grouped: dict[str, list[tuple[float, float]]] = {name: [] for name, _, _ in BUCKET_EDGES}
    for p, r in pairs:
        grouped[bucket_name_for_prediction(p)].append((p, r))

    buckets: list[CalibrationBucket] = []
    for name, lo, hi in BUCKET_EDGES:
        rows = grouped[name]
        if not rows:
            buckets.append(CalibrationBucket(name, lo, hi, 0, None, None, None, None, None, None))
            continue
        preds = [p for p, _ in rows]
        reals = [r for _, r in rows]
        errs = [r - p for p, r in rows]
        buckets.append(
            CalibrationBucket(
                bucket_name=name,
                prediction_min=lo,
                prediction_max=hi,
                sample_count=len(rows),
                average_prediction=sum(preds) / len(preds),
                average_realized_return=sum(reals) / len(reals),
                median_realized_return=float(median(reals)),
                error=sum(abs(e) for e in errs) / len(errs),
                bias=sum(errs) / len(errs),
                win_rate=sum(_direction_hit(p, r) for p, r in rows) / len(rows),
            )
        )

    n = len(pairs)
    if n < min_weak:
        status = CalibrationStatus.INSUFFICIENT_SAMPLE
        note = f"Мало зрелых наблюдений (n={n}) — confidence остаётся UNKNOWN."
    elif n < min_adequate:
        status = CalibrationStatus.WEAK
        note = (
            f"Выборка ограничена (n={n}). Есть сигналы калибровки, но недостаточно "
            "для сильного доверия — не выдаём fake HIGH confidence."
        )
    else:
        status = CalibrationStatus.ADEQUATE_FOR_RESEARCH
        note = (
            f"Выборка n={n} достаточна для research-калибровки. "
            "Это не доказательство боевой точности и не разрешение real money."
        )

    return PredictionCalibration(
        candidate=candidate,
        model_version=model_version,
        prediction_period=prediction_period,
        sample_count=n,
        pending_count=pending_count,
        coverage=coverage,
        calibration_status=status,
        prediction_semantic=PredictionSemantic.EXPECTED_RETURN.value,
        bias=bias,
        mae=mae,
        direction_accuracy=hit,
        buckets=tuple(buckets),
        bucket_spec_version=BUCKET_SPEC_VERSION,
        uncertainty_note=note,
        limitations=limitations,
        created_at=now,
    )


def calibrate_ranking_quality(
    *,
    candidate: str = "prediction_ml_candidate",
    model_version: str = "v1_ranker",
    sample_count: int,
    pending_count: int = 0,
    spearman_values: list[float],
    top20_realized: list[float],
    bottom20_realized: list[float],
    rank_pairs: list[tuple[float, float]] | None = None,
    min_weak: int = 10,
    min_adequate: int = 50,
) -> RankingCalibration:
    """Ranking quality only — never MAE/direction on RANKING_SCORE as return %."""
    now = datetime.now(UTC)
    limitations = (
        "RANKING_SCORE is not expected return percent",
        "Uses rank IC / top-quantile realized quality, not return MAE",
        "No look-ahead: only matured realized returns",
        "No automatic winner vs Candidate V0",
    )
    total = sample_count + max(0, pending_count)
    coverage = (sample_count / total) if total else None

    def _mean(xs: list[float]) -> float | None:
        return sum(xs) / len(xs) if xs else None

    top_m = _mean(top20_realized)
    bot_m = _mean(bottom20_realized)
    spread = (top_m - bot_m) if top_m is not None and bot_m is not None else None

    rank_buckets: list[dict[str, float | int | None]] = []
    if rank_pairs:
        scores = sorted(p for p, _ in rank_pairs)
        if scores:
            q20 = scores[max(0, int(0.2 * len(scores)) - 1)]
            q80 = scores[min(len(scores) - 1, int(0.8 * len(scores)))]
            groups = {
                "bottom20_score": [(p, r) for p, r in rank_pairs if p <= q20],
                "mid_score": [(p, r) for p, r in rank_pairs if q20 < p < q80],
                "top20_score": [(p, r) for p, r in rank_pairs if p >= q80],
            }
            for name, rows in groups.items():
                reals = [r for _, r in rows]
                rank_buckets.append(
                    {
                        "bucket_name": name,
                        "sample_count": len(rows),
                        "average_realized_return": (sum(reals) / len(reals)) if reals else None,
                    }
                )

    if sample_count < min_weak:
        status = CalibrationStatus.INSUFFICIENT_SAMPLE
        note = f"Мало зрелых ranking outcomes (n={sample_count}) — ranking confidence UNKNOWN."
    elif sample_count < min_adequate:
        status = CalibrationStatus.WEAK
        note = f"Ranking sample n={sample_count} — research-only quality signals."
    else:
        status = CalibrationStatus.ADEQUATE_FOR_RESEARCH
        note = f"Ranking sample n={sample_count} достаточна для research rank quality."

    return RankingCalibration(
        candidate=candidate,
        model_version=model_version,
        sample_count=sample_count,
        pending_count=pending_count,
        coverage=coverage,
        mean_spearman_rank_ic=_mean(spearman_values),
        mean_top20_realized=top_m,
        mean_bottom20_realized=bot_m,
        mean_top_minus_bottom=spread,
        rank_bucket_realized=tuple(rank_buckets),
        calibration_status=status,
        uncertainty_note=note,
        limitations=limitations,
        created_at=now,
    )
