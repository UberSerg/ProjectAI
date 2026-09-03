"""Forward return label calculator — market observations only, no Technical/Relations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.modules.learning.application.contracts import DatasetLabelsV1


@dataclass(slots=True)
class PriceObservation:
    date: date
    close: float
    candle_id: int | None = None


@dataclass(slots=True)
class LabelResult:
    labels: DatasetLabelsV1
    label_valid: dict[str, bool]
    label_flags: dict[str, Any]
    close_t_candle_id: int | None
    target_candle_ids: dict[str, int | None]


class ForwardReturnLabelCalculator:
    """forward_return_Nd(t) = close(t+N observations) / close(t) - 1."""

    def __init__(self, horizons: list[int] | None = None) -> None:
        self.horizons = list(horizons or [1, 5, 10, 20])

    def calculate(
        self,
        observations: list[PriceObservation],
        *,
        as_of: date,
        discontinuity_dates: set[date] | None = None,
    ) -> LabelResult:
        discontinuity_dates = discontinuity_dates or set()
        by_date = {o.date: o for o in observations}
        ordered = sorted(observations, key=lambda o: o.date)
        dates = [o.date for o in ordered]
        if as_of not in by_date:
            empty = DatasetLabelsV1()
            return LabelResult(
                labels=empty,
                label_valid={f"{h}d": False for h in self.horizons},
                label_flags={"missing_as_of_close": True},
                close_t_candle_id=None,
                target_candle_ids={},
            )

        idx = dates.index(as_of)
        close_t = ordered[idx].close
        labels = DatasetLabelsV1()
        label_valid: dict[str, bool] = {}
        label_flags: dict[str, Any] = {}
        target_ids: dict[str, int | None] = {}

        for h in self.horizons:
            key = f"{h}d"
            attr = f"forward_return_{h}d"
            date_attr = f"target_date_{h}d"
            target_idx = idx + h
            if target_idx >= len(ordered):
                if hasattr(labels, attr):
                    setattr(labels, attr, None)
                if hasattr(labels, date_attr):
                    setattr(labels, date_attr, None)
                label_valid[key] = False
                label_flags[f"missing_future_{key}"] = True
                target_ids[key] = None
                continue
            target = ordered[target_idx]
            if hasattr(labels, date_attr):
                setattr(labels, date_attr, target.date)
            target_ids[key] = target.candle_id
            # Window (t, t+N] for discontinuity — observations after as_of up to and including target
            window_dates = {d for d in dates[idx + 1 : target_idx + 1]}
            if window_dates & discontinuity_dates:
                if hasattr(labels, attr):
                    setattr(labels, attr, None)
                label_valid[key] = False
                label_flags[f"price_discontinuity_in_target_window_{key}"] = True
                continue
            if close_t <= 0 or target.close <= 0:
                if hasattr(labels, attr):
                    setattr(labels, attr, None)
                label_valid[key] = False
                label_flags[f"non_positive_close_{key}"] = True
                continue
            fwd = target.close / close_t - 1.0
            if hasattr(labels, attr):
                setattr(labels, attr, float(fwd))
            label_valid[key] = True

        return LabelResult(
            labels=labels,
            label_valid=label_valid,
            label_flags=label_flags,
            close_t_candle_id=ordered[idx].candle_id,
            target_candle_ids=target_ids,
        )
