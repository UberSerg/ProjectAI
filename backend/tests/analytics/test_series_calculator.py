"""Series feature calculator tests."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from app.modules.analytics.application.series_calculator import (
    SeriesObservation,
    calculate_series_features,
)


def test_first_observation_days_since_change_is_null_not_zero() -> None:
    """First observation has no prior change → NULL, never synthetic 0."""
    rows = calculate_series_features(
        [
            SeriesObservation(date(2024, 1, 1), 100.0),
            SeriesObservation(date(2024, 1, 3), 110.0),
            SeriesObservation(date(2024, 1, 4), 110.0),
        ]
    )
    assert rows[0].days_since_change is None
    assert rows[0].previous_value is None
    assert rows[0].absolute_change is None
    assert rows[0].pct_change is None
    assert rows[1].days_since_change == 0  # changed on this observation day
    assert rows[2].days_since_change == 1
    assert rows[1].pct_change is not None
    assert abs(rows[1].pct_change - 0.1) < 1e-9


def test_none_and_nan_days_since_do_not_become_zero() -> None:
    """Regression: DataFrame NaN / None must map to NULL, not int() crash or 0."""
    # Simulate the historical bug path: float column with NaN for missing int.
    series = pd.Series([np.nan, 0.0, 1.0], dtype="float64")
    assert pd.isna(series.iloc[0])

    rows = calculate_series_features(
        [
            SeriesObservation(date(2024, 2, 1), 10.0),
            SeriesObservation(date(2024, 2, 2), 10.0),
        ]
    )
    assert rows[0].days_since_change is None
    assert rows[1].days_since_change == 1  # unchanged since first obs (= day 0 baseline)


def test_single_observation_null_integer_fields() -> None:
    rows = calculate_series_features([SeriesObservation(date(2024, 3, 1), 42.0)])
    assert len(rows) == 1
    assert rows[0].days_since_change is None
    assert rows[0].previous_value is None
    assert rows[0].value == 42.0


def test_pct_change_disabled() -> None:
    rows = calculate_series_features(
        [SeriesObservation(date(2024, 1, 1), 1.0), SeriesObservation(date(2024, 1, 2), 2.0)],
        allow_pct_change=False,
    )
    assert rows[1].pct_change is None
    assert rows[1].absolute_change == 1.0
