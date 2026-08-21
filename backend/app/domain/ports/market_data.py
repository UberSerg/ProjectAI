"""Market data provider port — HTTP adapters live in infrastructure."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any


@dataclass(slots=True, frozen=True)
class CandleBar:
    timestamp: datetime
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    volume: Decimal | None = None


@dataclass(slots=True, frozen=True)
class SeriesPoint:
    timestamp: datetime
    value: Decimal


@dataclass(slots=True, frozen=True)
class ProviderFetchResult:
    source: str
    records: tuple[CandleBar, ...] | tuple[SeriesPoint, ...]
    raw_payloads: tuple[bytes, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class MarketDataProvider(ABC):
    source: str

    @abstractmethod
    def fetch_daily_candles(
        self,
        external_id: str,
        start_date: date,
        end_date: date,
        *,
        board: str = "TQBR",
    ) -> ProviderFetchResult:
        raise NotImplementedError

    @abstractmethod
    def fetch_series(
        self,
        external_id: str,
        start_date: date,
        end_date: date,
    ) -> ProviderFetchResult:
        raise NotImplementedError
