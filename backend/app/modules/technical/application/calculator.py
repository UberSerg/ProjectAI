"""Pure TechnicalFeatureCalculator — SMA/EMA/RSI Wilder/ATR Wilder (no I/O)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from app.modules.technical.technical_config import TECHNICAL_DAILY_V1


@dataclass(slots=True)
class OhlcObservation:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    source_updated_at: Any | None = None


@dataclass(slots=True)
class TechnicalFeatureRecord:
    date: date
    sma20: float | None = None
    sma20_distance: float | None = None
    ema20: float | None = None
    ema20_distance: float | None = None
    rsi14: float | None = None
    atr14: float | None = None
    atr14_pct: float | None = None
    has_sufficient_history: bool = False
    is_valid: bool = True
    quality_flags: dict[str, Any] = field(default_factory=dict)


def _safe_float(value: float | None) -> float | None:
    if value is None or (isinstance(value, float) and (np.isnan(value) or np.isinf(value))):
        return None
    return float(value)


def _ohlc_invariant_ok(obs: OhlcObservation) -> bool:
    if obs.open <= 0 or obs.high <= 0 or obs.low <= 0 or obs.close <= 0:
        return False
    if obs.high < obs.low:
        return False
    if obs.high < max(obs.open, obs.close):
        return False
    if obs.low > min(obs.open, obs.close):
        return False
    return True


class TechnicalFeatureCalculator:
    """Backward-looking technical indicators over ordered trading OHLC observations."""

    def __init__(self, parameters: dict[str, Any] | None = None) -> None:
        params = parameters or TECHNICAL_DAILY_V1["parameters"]
        self.sma_window = int(params["sma_window"])
        self.ema_span = int(params["ema_span"])
        self.ema_adjust = bool(params.get("ema_adjust", False))
        self.ema_min_periods = int(params.get("ema_min_periods", self.ema_span))
        self.rsi_period = int(params["rsi_period"])
        self.atr_period = int(params["atr_period"])
        if self.ema_adjust:
            raise ValueError("technical_daily v1 requires ema_adjust=false")

    def calculate(
        self,
        observations: list[OhlcObservation],
        *,
        discontinuity_dates: set[date] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[TechnicalFeatureRecord]:
        if not observations:
            return []

        discontinuity_dates = discontinuity_dates or set()
        closes = np.array([float(o.close) for o in observations], dtype=np.float64)
        highs = np.array([float(o.high) for o in observations], dtype=np.float64)
        lows = np.array([float(o.low) for o in observations], dtype=np.float64)

        sma = self._sma(closes, self.sma_window)
        ema = self._ema_adjust_false(closes, self.ema_span, self.ema_min_periods)
        rsi = self._rsi_wilder(closes, self.rsi_period)
        atr = self._atr_wilder(highs, lows, closes, self.atr_period)

        # Rolling discontinuity: any discontinuity in lookback window affects quality.
        max_lookback = max(self.sma_window, self.ema_min_periods, self.rsi_period + 1, self.atr_period + 1)
        disc_mask = np.array([o.date in discontinuity_dates for o in observations], dtype=bool)

        records: list[TechnicalFeatureRecord] = []
        for i, obs in enumerate(observations):
            obs_date = obs.date
            if date_from and obs_date < date_from:
                continue
            if date_to and obs_date > date_to:
                continue

            flags: dict[str, Any] = {}
            insufficient: list[str] = []

            if not _ohlc_invariant_ok(obs):
                flags["invalid_ohlc"] = True

            sma_v = _safe_float(sma[i]) if i >= self.sma_window - 1 else None
            ema_v = _safe_float(ema[i])
            rsi_v = _safe_float(rsi[i])
            atr_v = _safe_float(atr[i])

            if i < self.sma_window - 1:
                insufficient.append("sma20")
                sma_v = None
            if i < self.ema_min_periods - 1 or ema_v is None:
                insufficient.append("ema20")
                ema_v = None
            if rsi_v is None:
                insufficient.append("rsi14")
            if atr_v is None:
                insufficient.append("atr14")

            sma_dist = None
            if sma_v is not None:
                if sma_v <= 0:
                    flags["sma20_non_positive"] = True
                    sma_dist = None
                else:
                    sma_dist = obs.close / sma_v - 1.0

            ema_dist = None
            if ema_v is not None:
                if ema_v <= 0:
                    flags["ema20_non_positive"] = True
                    ema_dist = None
                else:
                    ema_dist = obs.close / ema_v - 1.0

            atr_pct = None
            if atr_v is not None:
                if obs.close <= 0:
                    flags["close_non_positive"] = True
                else:
                    atr_pct = atr_v / obs.close

            window_start = max(0, i - max_lookback + 1)
            if disc_mask[window_start : i + 1].any():
                flags["price_discontinuity"] = True

            if insufficient:
                flags["insufficient_history"] = insufficient

            critical = bool(flags.get("invalid_ohlc") or flags.get("price_discontinuity"))
            has_core = sma_dist is not None and ema_dist is not None and rsi_v is not None and atr_pct is not None
            is_valid = has_core and not critical and not flags.get("sma20_non_positive") and not flags.get(
                "ema20_non_positive"
            )

            records.append(
                TechnicalFeatureRecord(
                    date=obs_date,
                    sma20=sma_v,
                    sma20_distance=_safe_float(sma_dist),
                    ema20=ema_v,
                    ema20_distance=_safe_float(ema_dist),
                    rsi14=rsi_v,
                    atr14=atr_v,
                    atr14_pct=_safe_float(atr_pct),
                    has_sufficient_history=has_core,
                    is_valid=is_valid,
                    quality_flags=flags,
                )
            )
        return records

    @staticmethod
    def _sma(closes: np.ndarray, window: int) -> np.ndarray:
        out = np.full(len(closes), np.nan, dtype=np.float64)
        if len(closes) < window:
            return out
        csum = np.cumsum(closes)
        out[window - 1] = csum[window - 1] / window
        for i in range(window, len(closes)):
            out[i] = (csum[i] - csum[i - window]) / window
        return out

    @staticmethod
    def _ema_adjust_false(closes: np.ndarray, span: int, min_periods: int) -> np.ndarray:
        """pandas ewm(span=span, adjust=False, min_periods=min_periods) semantics."""
        n = len(closes)
        out = np.full(n, np.nan, dtype=np.float64)
        if n == 0:
            return out
        alpha = 2.0 / (span + 1.0)
        ema = float(closes[0])
        out[0] = ema
        for i in range(1, n):
            ema = (1.0 - alpha) * ema + alpha * float(closes[i])
            out[i] = ema
        if min_periods > 1:
            out[: min_periods - 1] = np.nan
        return out

    @staticmethod
    def _rsi_wilder(closes: np.ndarray, period: int) -> np.ndarray:
        n = len(closes)
        out = np.full(n, np.nan, dtype=np.float64)
        if n < period + 1:
            return out
        deltas = np.diff(closes)
        gains = np.clip(deltas, 0.0, None)
        losses = np.clip(-deltas, 0.0, None)

        avg_gain = float(np.mean(gains[:period]))
        avg_loss = float(np.mean(losses[:period]))

        def _rsi(g: float, loss: float) -> float:
            if loss == 0.0 and g > 0.0:
                return 100.0
            if g == 0.0 and loss > 0.0:
                return 0.0
            if g == 0.0 and loss == 0.0:
                return 50.0
            rs = g / loss
            return 100.0 - (100.0 / (1.0 + rs))

        # First RSI at close index `period` (period deltas from closes[0..period]).
        out[period] = _rsi(avg_gain, avg_loss)
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + float(gains[i])) / period
            avg_loss = (avg_loss * (period - 1) + float(losses[i])) / period
            out[i + 1] = _rsi(avg_gain, avg_loss)
        return out

    @staticmethod
    def _atr_wilder(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> np.ndarray:
        """Wilder ATR: TR[0]=H-L; first ATR at index period-1 = mean(TR[0:period])."""
        n = len(closes)
        out = np.full(n, np.nan, dtype=np.float64)
        if n < period:
            return out
        tr = np.empty(n, dtype=np.float64)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        atr = float(np.mean(tr[:period]))
        out[period - 1] = atr
        for i in range(period, n):
            atr = (atr * (period - 1) + float(tr[i])) / period
            out[i] = atr
        return out
