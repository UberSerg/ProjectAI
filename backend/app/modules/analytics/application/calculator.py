"""Pure deterministic daily feature calculator (no I/O)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.modules.analytics.feature_config import BASIC_DAILY_V1, RETURN_COLUMNS


@dataclass(slots=True)
class CandleObservation:
    date: date
    close: float
    volume: float | None
    source_updated_at: Any | None = None


@dataclass(slots=True)
class InstrumentFeatureRecord:
    date: date
    close: float | None
    volume: float | None
    return_1d: float | None = None
    return_2d: float | None = None
    return_3d: float | None = None
    return_5d: float | None = None
    return_10d: float | None = None
    return_20d: float | None = None
    log_return_1d: float | None = None
    volatility_5d: float | None = None
    volatility_20d: float | None = None
    drawdown_20d: float | None = None
    volume_change_1d: float | None = None
    volume_zscore_20d: float | None = None
    has_sufficient_history: bool = False
    is_valid: bool = True
    quality_flags: dict[str, Any] = field(default_factory=dict)
    source_updated_at: Any | None = None


def _safe_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return float(value)


class DailyFeatureCalculator:
    """Backward-looking feature calculator over ordered trading observations."""

    def __init__(self, parameters: dict[str, Any] | None = None) -> None:
        params = parameters or BASIC_DAILY_V1["parameters"]
        self.return_windows: list[int] = list(params["return_windows"])
        self.volatility_windows: list[int] = list(params["volatility_windows"])
        self.drawdown_window: int = int(params["drawdown_window"])
        self.volume_zscore_window: int = int(params["volume_zscore_window"])
        self.volatility_ddof: int = int(params["volatility_ddof"])
        self.max_lookback: int = max(
            max(self.return_windows, default=0),
            max(self.volatility_windows, default=0),
            self.drawdown_window,
            self.volume_zscore_window,
        )

    def calculate(
        self,
        observations: list[CandleObservation],
        *,
        discontinuity_dates: set[date] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[InstrumentFeatureRecord]:
        if not observations:
            return []

        discontinuity_dates = discontinuity_dates or set()
        df = pd.DataFrame(
            {
                "date": [obs.date for obs in observations],
                "close": [float(obs.close) for obs in observations],
                "volume": [obs.volume for obs in observations],
                "source_updated_at": [obs.source_updated_at for obs in observations],
            }
        ).sort_values("date").reset_index(drop=True)

        close = df["close"]
        volume = pd.to_numeric(df["volume"], errors="coerce")

        for window in self.return_windows:
            col = f"return_{window}d"
            df[col] = close / close.shift(window) - 1.0

        prev_close = close.shift(1)
        valid_log = (close > 0) & (prev_close > 0)
        df["log_return_1d"] = np.where(valid_log, np.log(close / prev_close), np.nan)

        log_ret = df["log_return_1d"]
        for window in self.volatility_windows:
            col = f"volatility_{window}d"
            df[col] = log_ret.rolling(window=window, min_periods=window).std(ddof=self.volatility_ddof)

        rolling_max = close.rolling(window=self.drawdown_window, min_periods=self.drawdown_window).max()
        df["drawdown_20d"] = close / rolling_max - 1.0

        prev_volume = volume.shift(1)
        with np.errstate(divide="ignore", invalid="ignore"):
            df["volume_change_1d"] = np.where(
                prev_volume.notna() & (prev_volume != 0) & volume.notna(),
                volume / prev_volume - 1.0,
                np.nan,
            )

        baseline = volume.shift(1).rolling(
            window=self.volume_zscore_window,
            min_periods=self.volume_zscore_window,
        )
        baseline_mean = baseline.mean()
        baseline_std = baseline.std(ddof=self.volatility_ddof)
        with np.errstate(divide="ignore", invalid="ignore"):
            df["volume_zscore_20d"] = np.where(
                baseline_std.notna() & (baseline_std != 0) & volume.notna(),
                (volume - baseline_mean) / baseline_std,
                np.nan,
            )

        records: list[InstrumentFeatureRecord] = []
        for idx, row in df.iterrows():
            obs_date: date = row["date"]
            if date_from and obs_date < date_from:
                continue
            if date_to and obs_date > date_to:
                continue

            insufficient: list[str] = []
            for window in self.return_windows:
                col = f"return_{window}d"
                if idx < window:
                    insufficient.append(col)
            if idx < 1:
                insufficient.append("log_return_1d")
            for window in self.volatility_windows:
                if idx < window:
                    insufficient.append(f"volatility_{window}d")
            if idx < self.drawdown_window - 1:
                insufficient.append("drawdown_20d")
            if idx < 1:
                insufficient.append("volume_change_1d")
            if idx < self.volume_zscore_window:
                insufficient.append("volume_zscore_20d")

            quality_flags: dict[str, Any] = {}
            if insufficient:
                quality_flags["insufficient_history"] = sorted(set(insufficient))

            close_val = _safe_float(row["close"])
            if close_val is not None and close_val <= 0:
                quality_flags["invalid_close"] = True

            prev_close_val = _safe_float(prev_close.iloc[idx]) if idx > 0 else None
            if prev_close_val is not None and prev_close_val <= 0:
                quality_flags["invalid_prior_close"] = True

            affected_returns: list[str] = []
            if obs_date in discontinuity_dates:
                quality_flags["price_discontinuity"] = True
                affected_returns.extend(list(RETURN_COLUMNS))
            if idx > 0:
                prev_date = df.at[idx - 1, "date"]
                if prev_date in discontinuity_dates:
                    quality_flags["price_discontinuity"] = True
                    affected_returns.extend(["return_1d", "log_return_1d", "volume_change_1d"])
            if affected_returns:
                quality_flags["affected_features"] = sorted(set(affected_returns))

            has_history = idx >= 1
            is_valid = "invalid_close" not in quality_flags

            rec = InstrumentFeatureRecord(
                date=obs_date,
                close=close_val,
                volume=_safe_float(row["volume"]),
                return_1d=_safe_float(row.get("return_1d")),
                return_2d=_safe_float(row.get("return_2d")),
                return_3d=_safe_float(row.get("return_3d")),
                return_5d=_safe_float(row.get("return_5d")),
                return_10d=_safe_float(row.get("return_10d")),
                return_20d=_safe_float(row.get("return_20d")),
                log_return_1d=_safe_float(row.get("log_return_1d")),
                volatility_5d=_safe_float(row.get("volatility_5d")),
                volatility_20d=_safe_float(row.get("volatility_20d")),
                drawdown_20d=_safe_float(row.get("drawdown_20d")),
                volume_change_1d=_safe_float(row.get("volume_change_1d")),
                volume_zscore_20d=_safe_float(row.get("volume_zscore_20d")),
                has_sufficient_history=has_history,
                is_valid=is_valid,
                quality_flags=quality_flags,
                source_updated_at=row.get("source_updated_at"),
            )
            records.append(rec)

        return records
