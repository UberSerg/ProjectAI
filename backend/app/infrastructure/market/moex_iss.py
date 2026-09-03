"""MOEX ISS history provider."""

from __future__ import annotations

import json
from dataclasses import dataclass
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
from app.modules.market.application.split_events import (
    SOURCE_MOEX,
    SplitEventDraft,
    SplitParseResult,
    classify_split_factor,
    split_adjustment_factor,
)


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

    def fetch_security_boards(self, secid: str) -> tuple[list[MoexBoardWindow], bytes]:
        """Official ISS security boards: history_from/till, listed_from/till, is_primary, is_traded."""
        url = f"{self.base_url}/iss/securities/{secid}.json"
        response = self.client.get(url, params={"iss.meta": "off"})
        return parse_moex_security_boards(response.json()), response.content

    def fetch_stock_splits(self) -> tuple[SplitParseResult, tuple[bytes, ...]]:
        """Official ISS stock splits. Fields: tradedate, secid, before, after. No known_at."""
        url = f"{self.base_url}/iss/statistics/engines/stock/splits.json"
        accepted: list[SplitEventDraft] = []
        rejected = 0
        received = 0
        raw_payloads: list[bytes] = []
        start = 0
        while True:
            response = self.client.get(
                url,
                params={"start": start, "iss.meta": "off"},
            )
            raw_payloads.append(response.content)
            payload = response.json()
            page = parse_moex_splits(payload)
            accepted.extend(page.accepted)
            rejected += page.rejected
            received += page.received
            row_count = len((payload.get("splits") or {}).get("data") or [])
            if row_count < 100:
                break
            start += 100
        return SplitParseResult(tuple(accepted), rejected, received), tuple(raw_payloads)


def parse_moex_splits(payload: dict[str, Any]) -> SplitParseResult:
    """Parse ISS /iss/statistics/engines/stock/splits.json. Rejects invalid before/after."""
    block = payload.get("splits") or {}
    columns = block.get("columns") or []
    accepted: list[SplitEventDraft] = []
    rejected = 0
    rows = block.get("data") or []
    for values in rows:
        row = dict(zip(columns, values, strict=False))
        parsed = _split_row_to_draft(row)
        if parsed is None:
            rejected += 1
            continue
        accepted.append(parsed)
    return SplitParseResult(tuple(accepted), rejected, len(rows))


def _split_row_to_draft(row: dict[str, Any]) -> SplitEventDraft | None:
    secid = str(row.get("secid") or "").strip()
    trade_date = row.get("tradedate")
    before = _decimal(row.get("before"))
    after = _decimal(row.get("after"))
    if not secid or not trade_date:
        return None
    if before is None or after is None or before <= 0 or after <= 0:
        return None
    try:
        effective = date.fromisoformat(str(trade_date)[:10])
    except ValueError:
        return None
    factor = split_adjustment_factor(before, after)
    event_type = classify_split_factor(factor)
    if event_type is None:
        return None
    return SplitEventDraft(
        secid=secid,
        effective_date=effective,
        split_before=before,
        split_after=after,
        adjustment_factor=factor,
        source=SOURCE_MOEX,
        event_type=event_type,
        known_at=None,
        raw={
            "tradedate": str(trade_date),
            "secid": secid,
            "before": str(before),
            "after": str(after),
        },
    )


@dataclass(frozen=True, slots=True)
class MoexBoardWindow:
    secid: str
    board: str
    market: str
    history_from: date | None
    history_till: date | None
    listed_from: date | None
    listed_till: date | None
    is_primary: bool
    is_traded: bool


def parse_moex_security_boards(payload: dict[str, Any]) -> list[MoexBoardWindow]:
    """Parse /iss/securities/{SECID}.json boards block. Does not invent dates."""
    description_secid = _description_secid(payload)
    block = payload.get("boards") or {}
    columns = block.get("columns") or []
    result: list[MoexBoardWindow] = []
    for values in block.get("data") or []:
        row = dict(zip(columns, values, strict=False))
        board = str(row.get("boardid") or "").strip()
        if not board:
            continue
        result.append(
            MoexBoardWindow(
                secid=str(row.get("secid") or description_secid or "").strip(),
                board=board,
                market=str(row.get("market") or "").strip(),
                history_from=_as_date(row.get("history_from")),
                history_till=_as_date(row.get("history_till")),
                listed_from=_as_date(row.get("listed_from")),
                listed_till=_as_date(row.get("listed_till")),
                is_primary=bool(row.get("is_primary")),
                is_traded=bool(row.get("is_traded")),
            )
        )
    return result


def _description_secid(payload: dict[str, Any]) -> str:
    block = payload.get("description") or {}
    columns = block.get("columns") or []
    for values in block.get("data") or []:
        row = dict(zip(columns, values, strict=False))
        if str(row.get("name") or "") == "SECID":
            return str(row.get("value") or "").strip()
    return ""


def _as_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None

