"""MOEX ISS history provider."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.config import get_settings
from app.domain.ports.market_data import (
    CandleBar,
    MarketDataProvider,
    ProviderFetchResult,
)
from app.infrastructure.market.http_client import MarketHttpClient


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def parse_moex_history(payload: dict[str, Any]) -> list[CandleBar]:
    history = payload.get("history") or {}
    columns = history.get("columns") or []
    result: list[CandleBar] = []
    for values in history.get("data") or []:
        row = dict(zip(columns, values, strict=False))
        close = _decimal(row.get("LEGALCLOSEPRICE")) or _decimal(row.get("CLOSE"))
        trade_date = row.get("TRADEDATE")
        if close is None or not trade_date:
            continue
        result.append(
            CandleBar(
                timestamp=datetime.combine(
                    date.fromisoformat(str(trade_date)), datetime.min.time(), UTC
                ),
                open=_decimal(row.get("OPEN")),
                high=_decimal(row.get("HIGH")),
                low=_decimal(row.get("LOW")),
                close=close,
                volume=_decimal(row.get("VOLUME")),
            )
        )
    return result


class MoexIssProvider(MarketDataProvider):
    source = "MOEX"

    def __init__(self, client: MarketHttpClient | None = None, base_url: str | None = None) -> None:
        self.client = client or MarketHttpClient()
        self.base_url = (base_url or get_settings().moex_base_url).rstrip("/")

    def fetch_daily_candles(
        self, external_id: str, start_date: date, end_date: date, *, board: str = "TQBR"
    ) -> ProviderFetchResult:
        # Index history boards include SNDX (IMOEX/RGBI) and RTSI (RTS Index).
        index_boards = {"SNDX", "RTSI"}
        market = "index" if board in index_boards else "shares"
        url = (
            f"{self.base_url}/iss/history/engines/stock/markets/{market}"
            f"/boards/{board}/securities/{external_id}.json"
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
                    "start": start,
                    "iss.meta": "off",
                    "history.columns": (
                        "TRADEDATE,OPEN,HIGH,LOW,CLOSE,LEGALCLOSEPRICE,VOLUME"
                    ),
                },
            )
            raw_payloads.append(response.content)
            payload = response.json()
            page = parse_moex_history(payload)
            bars.extend(page)
            row_count = len((payload.get("history") or {}).get("data") or [])
            if row_count < 100:
                break
            start += 100
        return ProviderFetchResult(
            source=self.source,
            records=tuple(bars),
            raw_payloads=tuple(raw_payloads),
            metadata={"external_id": external_id, "board": board},
        )

    def fetch_series(
        self, external_id: str, start_date: date, end_date: date
    ) -> ProviderFetchResult:
        result = self.fetch_daily_candles(
            external_id, start_date, end_date, board="SNDX"
        )
        return ProviderFetchResult(
            source=result.source,
            records=result.records,
            raw_payloads=result.raw_payloads,
            metadata=result.metadata,
        )

    @staticmethod
    def parse(payload: bytes | str | dict[str, Any]) -> list[CandleBar]:
        if isinstance(payload, bytes):
            payload = json.loads(payload)
        elif isinstance(payload, str):
            payload = json.loads(payload)
        return parse_moex_history(payload)
