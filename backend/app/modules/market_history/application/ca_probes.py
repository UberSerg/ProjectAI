"""Corporate-action fingerprints for external price semantics.

A mechanical split is the cleanest discriminator between RAW and back-adjusted
history: RAW prices show the full price step at the effective date, adjusted
series do not. The probes here only read; they never rewrite candles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.market_history.domain.types import (
    CA_PROBE_TOLERANCE,
    CA_PROBE_WINDOW,
    KNOWN_CA_PROBES,
    MOEX_CANDLE_SOURCE,
    MOEX_CANDLE_TIMEFRAME,
    CaProbeVerdict,
    CorporateActionProbe,
)

_EXTERNAL_WINDOW_SQL = text(
    """
    (
        SELECT trade_date, close
        FROM market.external_candles_daily
        WHERE source_id = :source_id AND source_symbol = :symbol
          AND reject_reason IS NULL AND close > 0 AND trade_date < :event_date
        ORDER BY trade_date DESC
        LIMIT :window
    )
    UNION ALL
    (
        SELECT trade_date, close
        FROM market.external_candles_daily
        WHERE source_id = :source_id AND source_symbol = :symbol
          AND reject_reason IS NULL AND close > 0 AND trade_date >= :event_date
        ORDER BY trade_date ASC
        LIMIT :window
    )
    """
)

_MOEX_WINDOW_SQL = text(
    """
    SELECT (c.timestamp AT TIME ZONE 'UTC')::date AS trade_date, c.close
    FROM market.candles c
    JOIN market.instruments i ON i.id = c.instrument_id
    WHERE i.symbol = :symbol
      AND c.timeframe = :timeframe AND c.source = :source
      AND c.close > 0
      AND (c.timestamp AT TIME ZONE 'UTC')::date >= :event_date
    ORDER BY c.timestamp ASC
    LIMIT :window
    """
)


@dataclass(frozen=True, slots=True)
class CaProbeOutcome:
    symbol: str
    event_date: date
    label: str
    expected_price_divisor: float
    observed_ratio: float | None
    verdict: CaProbeVerdict
    confidence: str
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "event_date": self.event_date.isoformat(),
            "label": self.label,
            "expected_price_divisor": self.expected_price_divisor,
            "observed_ratio": self.observed_ratio,
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "detail": self.detail,
        }


def classify_probe(
    *,
    observed_ratio: float | None,
    price_divisor: float,
    moex_post_event_close: float | None = None,
    external_post_event_close: float | None = None,
) -> tuple[CaProbeVerdict, str, dict[str, Any]]:
    """Turn the observed before/after close ratio into a semantics verdict.

    ``observed_ratio`` is ``mean_close_before / mean_close_after``. For RAW data
    it should equal the price divisor implied by the action.
    """
    detail: dict[str, Any] = {"moex_reference": moex_post_event_close is not None}
    if observed_ratio is None or observed_ratio <= 0:
        detail["reason"] = "insufficient_observations"
        return CaProbeVerdict.UNKNOWN, "NONE", detail

    if abs(observed_ratio / price_divisor - 1.0) <= CA_PROBE_TOLERANCE:
        detail["reason"] = "price_step_matches_action"
        return CaProbeVerdict.RAW, "HIGH", detail

    if abs(observed_ratio - 1.0) > CA_PROBE_TOLERANCE:
        detail["reason"] = "price_step_matches_neither_raw_nor_adjusted"
        return CaProbeVerdict.UNKNOWN, "LOW", detail

    # No price step at a known mechanical event: the series is adjusted. Which
    # side was rescaled can only be told by comparing the post-event level with
    # canonical RAW MOEX.
    if moex_post_event_close is not None and external_post_event_close is not None:
        detail["moex_post_event_close"] = moex_post_event_close
        detail["external_post_event_close"] = external_post_event_close
        level_ratio = external_post_event_close / moex_post_event_close
        detail["post_event_level_ratio"] = round(level_ratio, 8)
        if abs(level_ratio - 1.0) <= CA_PROBE_TOLERANCE:
            detail["reason"] = "no_step_and_post_event_matches_raw"
            return CaProbeVerdict.PRE_ADJUSTED, "HIGH", detail
        if abs(level_ratio / price_divisor - 1.0) <= CA_PROBE_TOLERANCE:
            detail["reason"] = "no_step_and_post_event_kept_pre_event_scale"
            return CaProbeVerdict.POST_ADJUSTED, "HIGH", detail
        detail["reason"] = "no_step_but_level_matches_no_known_scale"
        return CaProbeVerdict.UNKNOWN, "LOW", detail

    detail["reason"] = "no_step_at_known_action_without_raw_reference"
    return CaProbeVerdict.PRE_ADJUSTED, "LOW", detail


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def probe_symbol(
    session: Session, source_id: int, probe: CorporateActionProbe
) -> CaProbeOutcome:
    rows = session.execute(
        _EXTERNAL_WINDOW_SQL,
        {
            "source_id": source_id,
            "symbol": probe.symbol,
            "event_date": probe.event_date,
            "window": CA_PROBE_WINDOW,
        },
    ).all()

    before = [float(close) for trade_date, close in rows if trade_date < probe.event_date]
    after = [float(close) for trade_date, close in rows if trade_date >= probe.event_date]
    mean_before = _mean(before)
    mean_after = _mean(after)
    observed_ratio = (
        mean_before / mean_after
        if mean_before is not None and mean_after not in (None, 0.0)
        else None
    )

    moex_after: float | None = None
    if observed_ratio is not None:
        moex_rows = session.execute(
            _MOEX_WINDOW_SQL,
            {
                "symbol": probe.symbol,
                "timeframe": MOEX_CANDLE_TIMEFRAME,
                "source": MOEX_CANDLE_SOURCE,
                "event_date": probe.event_date,
                "window": CA_PROBE_WINDOW,
            },
        ).all()
        moex_after = _mean([float(close) for _trade_date, close in moex_rows])

    verdict, confidence, detail = classify_probe(
        observed_ratio=observed_ratio,
        price_divisor=probe.price_divisor,
        moex_post_event_close=moex_after,
        external_post_event_close=mean_after,
    )
    detail.update(
        {
            "observations_before": len(before),
            "observations_after": len(after),
            "mean_close_before": mean_before,
            "mean_close_after": mean_after,
        }
    )
    return CaProbeOutcome(
        symbol=probe.symbol,
        event_date=probe.event_date,
        label=probe.label,
        expected_price_divisor=probe.price_divisor,
        observed_ratio=None if observed_ratio is None else round(observed_ratio, 8),
        verdict=verdict,
        confidence=confidence,
        detail=detail,
    )


def run_ca_probes(
    session: Session,
    source_id: int,
    probes: tuple[CorporateActionProbe, ...] = KNOWN_CA_PROBES,
) -> list[CaProbeOutcome]:
    return [probe_symbol(session, source_id, probe) for probe in probes]
