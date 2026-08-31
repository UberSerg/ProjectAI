"""Daily series feature calculator (sparse macro/rate series)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd


@dataclass(slots=True)
class SeriesObservation:
    date: date
    value: float


@dataclass(slots=True)
class SeriesFeatureRecord:
    date: date
    value: float | None
    previous_value: float | None = None
    absolute_change: float | None = None
    pct_change: float | None = None
    days_since_change: int | None = None
    is_valid: bool = True
    quality_flags: dict[str, Any] = field(default_factory=dict)


def calculate_series_features(
    observations: list[SeriesObservation],
    *,
    allow_pct_change: bool = True,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[SeriesFeatureRecord]:
    if not observations:
        return []

    df = pd.DataFrame({"date": [o.date for o in observations], "value": [float(o.value) for o in observations]})
    df = df.sort_values("date").reset_index(drop=True)
    df["previous_value"] = df["value"].shift(1)
    df["absolute_change"] = df["value"] - df["previous_value"]

    if allow_pct_change:
        with np.errstate(divide="ignore", invalid="ignore"):
            df["pct_change"] = np.where(
                df["previous_value"].notna() & (df["previous_value"] != 0),
                df["value"] / df["previous_value"] - 1.0,
                np.nan,
            )
    else:
        df["pct_change"] = np.nan

    last_change_idx = 0
    days_since: list[int | None] = []
    for idx, row in df.iterrows():
        if idx == 0:
            # No prior observation — days_since_change is undefined (NULL), not 0.
            days_since.append(None)
            continue
        if row["value"] != df.at[idx - 1, "value"]:
            last_change_idx = idx
        prev_date = df.at[last_change_idx, "date"]
        days_since.append(int((row["date"] - prev_date).days))
    # object dtype keeps None as None (float column would coerce to NaN).
    df["days_since_change"] = pd.Series(days_since, dtype="object")

    records: list[SeriesFeatureRecord] = []
    for _, row in df.iterrows():
        obs_date: date = row["date"]
        if date_from and obs_date < date_from:
            continue
        if date_to and obs_date > date_to:
            continue
        val = float(row["value"]) if pd.notna(row["value"]) else None
        prev = float(row["previous_value"]) if pd.notna(row["previous_value"]) else None
        abs_chg = float(row["absolute_change"]) if pd.notna(row["absolute_change"]) else None
        pct = float(row["pct_change"]) if pd.notna(row.get("pct_change")) else None
        dsc_raw = row["days_since_change"]
        # Missing → NULL. Never coerce NaN/None to 0.
        if dsc_raw is None or (isinstance(dsc_raw, float) and np.isnan(dsc_raw)) or pd.isna(dsc_raw):
            dsc = None
        else:
            dsc = int(dsc_raw)
        records.append(
            SeriesFeatureRecord(
                date=obs_date,
                value=val,
                previous_value=prev,
                absolute_change=abs_chg,
                pct_change=pct,
                days_since_change=dsc,
                is_valid=val is not None,
                quality_flags={},
            )
        )
    return records
