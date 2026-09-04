"""Temporal walk-forward folds with label-target purge."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from app.modules.prediction.candidate_config import CandidateV0Config


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_id: int
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "validation_start": self.validation_start.isoformat(),
            "validation_end": self.validation_end.isoformat(),
        }


def _add_months(d: date, months: int) -> date:
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def build_expanding_folds(
    *,
    data_start: date,
    development_end_exclusive: date,
    config: CandidateV0Config,
) -> list[WalkForwardFold]:
    """Expanding walk-forward on [data_start, development_end_exclusive).

    First validation starts after ``min_train_years`` calendar years from data_start.
    """
    if development_end_exclusive <= data_start:
        return []
    first_val_start = date(data_start.year + config.min_train_years, data_start.month, data_start.day)
    # Align to month start for deterministic half-year windows.
    first_val_start = date(first_val_start.year, first_val_start.month, 1)
    folds: list[WalkForwardFold] = []
    fold_id = 0
    val_start = first_val_start
    while True:
        val_end_exclusive = _add_months(val_start, config.validation_months)
        if val_start >= development_end_exclusive:
            break
        if val_end_exclusive > development_end_exclusive:
            val_end_exclusive = development_end_exclusive
        if val_end_exclusive <= val_start:
            break
        train_end = val_start  # exclusive upper bound for as_of in train selection helpers
        folds.append(
            WalkForwardFold(
                fold_id=fold_id,
                train_start=data_start,
                train_end=train_end,
                validation_start=val_start,
                validation_end=val_end_exclusive,
            )
        )
        fold_id += 1
        val_start = _add_months(val_start, config.step_months)
    return folds


def mask_eligible(frame: pd.DataFrame, config: CandidateV0Config) -> pd.Series:
    return (
        frame["y"].notna()
        & frame["label_valid_20d"].astype(bool)
        & frame["eligible_20d"].astype(bool)
        & frame["target_date_20d"].notna()
    )


def select_train_rows(
    frame: pd.DataFrame,
    *,
    as_of_end_exclusive: date,
    target_must_be_before: date,
    config: CandidateV0Config,
) -> pd.DataFrame:
    """Train rows: as_of < as_of_end_exclusive AND target_date_20d < target_must_be_before."""
    eligible = mask_eligible(frame, config)
    as_of = frame["as_of_date"]
    target = frame["target_date_20d"]
    mask = eligible & (as_of < as_of_end_exclusive) & (target < target_must_be_before)
    return frame.loc[mask].copy()


def select_eval_rows(
    frame: pd.DataFrame,
    *,
    as_of_start: date,
    as_of_end_exclusive: date,
    config: CandidateV0Config,
) -> pd.DataFrame:
    eligible = mask_eligible(frame, config)
    as_of = frame["as_of_date"]
    mask = eligible & (as_of >= as_of_start) & (as_of < as_of_end_exclusive)
    return frame.loc[mask].copy()


def count_purged_at_boundary(
    frame: pd.DataFrame,
    *,
    as_of_end_exclusive: date,
    target_must_be_before: date,
    config: CandidateV0Config,
) -> int:
    """Rows that would be train by as_of but are purged by target_date overlap."""
    eligible = mask_eligible(frame, config)
    as_of = frame["as_of_date"]
    target = frame["target_date_20d"]
    would_train = eligible & (as_of < as_of_end_exclusive)
    purged = would_train & ~(target < target_must_be_before)
    return int(purged.sum())
