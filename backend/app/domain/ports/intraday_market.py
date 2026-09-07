"""Intraday market quotes port — ephemeral observations, not durable candles."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class QuoteFreshness(StrEnum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    STALE = "STALE"
    SESSION_NOT_STARTED = "SESSION_NOT_STARTED"
    NO_TRADES = "NO_TRADES"
    MARKET_CLOSED = "MARKET_CLOSED"
    UNAVAILABLE = "UNAVAILABLE"


class MarketSessionStatus(StrEnum):
    PREOPEN = "PREOPEN"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    NON_TRADING_DAY = "NON_TRADING_DAY"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True, frozen=True)
class IntradayQuote:
    """Point-in-time quote observation for open execution / live valuation.

    Must never be written into market.candles. instrument_id is optional so
    provider-level rows can exist before universe join.
    """

    secid: str
    board: str
    trading_date: date | None
    observed_at: datetime
    source_timestamp: datetime | None
    market_status: MarketSessionStatus
    open_price: float | None
    last_price: float | None
    bid: float | None
    ask: float | None
    previous_close: float | None
    volume: float | None
    source: str
    freshness: QuoteFreshness
    quality: str
    instrument_id: int | None = None


class IntradayMarketPort(ABC):
    """Fetch live/delayed board quotes. Not used by Dataset/Prediction training."""

    @abstractmethod
    def fetch_quotes(
        self,
        secids_by_board: dict[str, list[str]],
        *,
        observed_at: datetime | None = None,
    ) -> list[IntradayQuote]:
        """Batch-fetch quotes keyed by board → SECID list.

        Missing securities are omitted (no invented defaults).
        """
        raise NotImplementedError
