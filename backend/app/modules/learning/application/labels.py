"""Forward return label calculator — market observations only, no Technical/Relations.

V1: raw close(t+N)/close(t)-1; unexplained discontinuity in (t, t+N] invalidates.
V2 mechanical: same observation basis, but closes are put on a share basis using
H4A SPLIT/REVERSE_SPLIT factors realized by the target date. Known mechanical CA
dates do not invalidate; unexplained discontinuities still do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.modules.learning.application.contracts import DatasetLabelsV1
from app.modules.market.application.mechanical_adjustment import (
    MechanicalAction,
    actions_as_of,
    adjust_price,
    cumulative_factor,
)


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
        mechanical_actions: list[MechanicalAction] | None = None,
        price_basis: str = "raw",
    ) -> LabelResult:
        discontinuity_dates = discontinuity_dates or set()
        mechanical_actions = mechanical_actions or []
        mechanical_mode = price_basis == "mechanical_adjusted"
        mechanical_event_dates = {action.event_date for action in mechanical_actions}
        # Unexplained jumps still invalidate; known SPLIT/REVERSE_SPLIT dates do not in V2.
        invalidating_discontinuities = (
            discontinuity_dates - mechanical_event_dates if mechanical_mode else discontinuity_dates
        )

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
        close_t_raw = ordered[idx].close
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
            if window_dates & invalidating_discontinuities:
                if hasattr(labels, attr):
                    setattr(labels, attr, None)
                label_valid[key] = False
                label_flags[f"price_discontinuity_in_target_window_{key}"] = True
                continue

            close_t = close_t_raw
            close_target = target.close
            if mechanical_mode:
                # Outcome construction: CA realized by target may normalize both ends.
                # A CA after as_of but <= target is allowed for Y and must NOT enter X.
                realized = actions_as_of(mechanical_actions, target.date)
                close_t_adj = adjust_price(close_t_raw, cumulative_factor(realized, as_of))
                close_target_adj = adjust_price(target.close, cumulative_factor(realized, target.date))
                if close_t_adj is None or close_target_adj is None:
                    if hasattr(labels, attr):
                        setattr(labels, attr, None)
                    label_valid[key] = False
                    label_flags[f"mechanical_adjust_failed_{key}"] = True
                    continue
                close_t = close_t_adj
                close_target = close_target_adj
                if window_dates & mechanical_event_dates:
                    label_flags[f"mechanical_ca_normalized_{key}"] = True

            if close_t <= 0 or close_target <= 0:
                if hasattr(labels, attr):
                    setattr(labels, attr, None)
                label_valid[key] = False
                label_flags[f"non_positive_close_{key}"] = True
                continue
            fwd = close_target / close_t - 1.0
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
