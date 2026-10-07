"""MOEX ISS interval candles (free /candles.json) — additive to daily history provider.

Does not replace board marketdata quotes (moex_intraday.py).
Does not ingest ticks or order book.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.domain.ports.market_data import CandleBar, ProviderFetchResult
from app.infrastructure.market.http_client import MarketHttpClient

MSK = ZoneInfo("Europe/Moscow")

# Official ISS candle interval codes observed on TQBR (2026-10 audit).
# interval=15 returns empty — do not invent a 15m series.
MOEX_INTERVAL_CODES: dict[str, int] = {
    "1m": 1,
    "10m": 10,
    "60m": 60,
    "1d": 24,
}

CANDLES_PAGE_SIZE = 500
SOURCE_MOEX = "MOEX"


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        text = str(value).replace(",", ".")
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def parse_moex_begin_msk(value: Any) -> datetime | None:
    """Parse ISS candles.begin as Moscow local wall time → aware datetime."""
    if value in (None, ""):
        return None
    raw = str(value).strip()
    try:
        if "T" in raw:
            naive = datetime.fromisoformat(raw)
        else:
            naive = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if naive.tzinfo is not None:
        return naive.astimezone(MSK)
    return naive.replace(tzinfo=MSK)


def parse_moex_interval_candles(payload: dict[str, Any]) -> list[CandleBar]:
    """Parse /candles.json block. Timestamp = bar begin in Europe/Moscow."""
    block = payload.get("candles") or {}
    columns = block.get("columns") or []
    if not columns:
        return []
    result: list[CandleBar] = []
    for values in block.get("data") or []:
        row = dict(zip(columns, values, strict=False))
        close = _decimal(row.get("close"))
        begin = parse_moex_begin_msk(row.get("begin"))
        if close is None or begin is None:
            continue
        open_ = _decimal(row.get("open"))
        high = _decimal(row.get("high"))
        low = _decimal(row.get("low"))
        volume = _decimal(row.get("volume"))
        # Keep RUB turnover in metadata via CandleBar.volume = share/lot volume only.
        # value (turnover) is available in raw payload for VWAP at feature layer.
        result.append(
            CandleBar(
                timestamp=begin.astimezone(UTC),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
        )
    return result


def parse_moex_interval_candle_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse candles including turnover `value` for VWAP features."""
    block = payload.get("candles") or {}
    columns = block.get("columns") or []
    rows: list[dict[str, Any]] = []
    for values in block.get("data") or []:
        row = dict(zip(columns, values, strict=False))
        begin = parse_moex_begin_msk(row.get("begin"))
        close = _decimal(row.get("close"))
        if begin is None or close is None:
            continue
        rows.append(
            {
                "timestamp": begin.astimezone(UTC),
                "begin_msk": begin,
                "open": _decimal(row.get("open")),
                "high": _decimal(row.get("high")),
                "low": _decimal(row.get("low")),
                "close": close,
                "volume": _decimal(row.get("volume")),
                "value": _decimal(row.get("value")),
                "end_msk": parse_moex_begin_msk(row.get("end")),
            }
        )
    return rows


class MoexIntervalCandlesProvider:
    """Fetch free ISS interval OHLC candles for a board/SECID."""

    source = SOURCE_MOEX

    def __init__(
        self,
        client: MarketHttpClient | None = None,
        base_url: str | None = None,
    ) -> None:
        self.client = client or MarketHttpClient()
        self.base_url = (base_url or get_settings().moex_base_url).rstrip("/")

    def fetch_interval_candles(
        self,
        external_id: str,
        start_date: date,
        end_date: date,
        *,
        board: str = "TQBR",
        interval: str = "60m",
        market: str = "shares",
    ) -> ProviderFetchResult:
        code = MOEX_INTERVAL_CODES.get(interval)
        if code is None:
            raise ValueError(
                f"Unsupported interval {interval!r}; known: {sorted(MOEX_INTERVAL_CODES)}"
            )
        url = (
            f"{self.base_url}/iss/engines/stock/markets/{market}"
            f"/boards/{board}/securities/{external_id}/candles.json"
        )
        bars: list[CandleBar] = []
        raw_payloads: list[bytes] = []
        start = 0
        while True:
            response = self.client.get(
                url,
                params={
                    "from": start_date.isoformat(),
                    "till": end_date.isoformat(),
                    "interval": code,
                    "start": start,
                    "iss.meta": "off",
                },
            )
            raw_payloads.append(response.content)
            payload = response.json()
            page = parse_moex_interval_candles(payload)
            bars.extend(page)
            row_count = len((payload.get("candles") or {}).get("data") or [])
            if row_count < CANDLES_PAGE_SIZE:
                break
            start += CANDLES_PAGE_SIZE
        return ProviderFetchResult(
            source=self.source,
            records=tuple(bars),
            raw_payloads=tuple(raw_payloads),
            metadata={
                "external_id": external_id,
                "board": board,
                "market": market,
                "interval": interval,
                "moex_interval_code": code,
            },
        )

    def fetch_interval_candle_rows(
        self,
        external_id: str,
        start_date: date,
        end_date: date,
        *,
        board: str = "TQBR",
        interval: str = "60m",
        market: str = "shares",
    ) -> tuple[list[dict[str, Any]], tuple[bytes, ...]]:
        """Like fetch_interval_candles but retains turnover `value` for VWAP."""
        code = MOEX_INTERVAL_CODES.get(interval)
        if code is None:
            raise ValueError(
                f"Unsupported interval {interval!r}; known: {sorted(MOEX_INTERVAL_CODES)}"
            )
        url = (
            f"{self.base_url}/iss/engines/stock/markets/{market}"
            f"/boards/{board}/securities/{external_id}/candles.json"
        )
        rows: list[dict[str, Any]] = []
        raw_payloads: list[bytes] = []
        start = 0
        while True:
            response = self.client.get(
                url,
                params={
                    "from": start_date.isoformat(),
                    "till": end_date.isoformat(),
                    "interval": code,
                    "start": start,
                    "iss.meta": "off",
                },
            )
            raw_payloads.append(response.content)
            payload = response.json()
            page = parse_moex_interval_candle_rows(payload)
            rows.extend(page)
            row_count = len((payload.get("candles") or {}).get("data") or [])
            if row_count < CANDLES_PAGE_SIZE:
                break
            start += CANDLES_PAGE_SIZE
        return rows, tuple(raw_payloads)

    @staticmethod
    def parse(payload: bytes | str | dict[str, Any]) -> list[CandleBar]:
        if isinstance(payload, bytes):
            payload = json.loads(payload)
        elif isinstance(payload, str):
            payload = json.loads(payload)
        return parse_moex_interval_candles(payload)
