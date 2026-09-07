"""MOEX ISS intraday marketdata provider (ephemeral quotes only)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from app.core.config import get_settings
from app.domain.ports.intraday_market import (
    IntradayMarketPort,
    IntradayQuote,
    MarketSessionStatus,
    QuoteFreshness,
)
from app.infrastructure.market.http_client import MarketHttpClient

SOURCE = "MOEX_ISS"

# Equity primary; bonds optional for shared board fetch path.
SHARES_MARKET = "shares"
BONDS_MARKET = "bonds"
BOARD_MARKET: dict[str, str] = {
    "TQBR": SHARES_MARKET,
    "TQTF": SHARES_MARKET,
    "SMAL": SHARES_MARKET,
    "TQOB": BONDS_MARKET,
    "TQCB": BONDS_MARKET,
}

MARKETDATA_COLUMNS = (
    "SECID,BOARDID,OPEN,LAST,BID,OFFER,VOLTODAY,NUMTRADES,"
    "UPDATETIME,SYSTIME,STATUS,TIME,TRADINGSTATUS"
)
SECURITIES_COLUMNS = "SECID,BOARDID,PREVPRICE,STATUS,PREVLEGALCLOSEPRICE"


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any, *, trading_date: date | None) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    # SYSTIME often ISO-like; UPDATETIME / TIME often "HH:MM:SS"
    try:
        if "T" in text or "-" in text[:10]:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
    except ValueError:
        pass
    if trading_date is not None and len(text) <= 8 and ":" in text:
        try:
            parts = [int(p) for p in text.split(":")]
            while len(parts) < 3:
                parts.append(0)
            return datetime(
                trading_date.year,
                trading_date.month,
                trading_date.day,
                parts[0],
                parts[1],
                parts[2],
                tzinfo=UTC,
            )
        except (TypeError, ValueError):
            return None
    return None


def _rows_as_dicts(block: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not block:
        return []
    columns = block.get("columns") or []
    out: list[dict[str, Any]] = []
    for values in block.get("data") or []:
        out.append(dict(zip(columns, values, strict=False)))
    return out


def _infer_trading_date(md: dict[str, Any], observed_at: datetime) -> date | None:
    for key in ("SYSTIME", "UPDATETIME", "TIME"):
        dt = _parse_dt(md.get(key), trading_date=None)
        if dt is not None:
            return dt.date()
    # Fallback: observation calendar day in UTC (documented limitation).
    return observed_at.astimezone(UTC).date()


def _map_status(
    *,
    trading_status: Any,
    status: Any,
    open_price: float | None,
    last_price: float | None,
    num_trades: float | None,
) -> tuple[MarketSessionStatus, QuoteFreshness, str]:
    ts = str(trading_status or status or "").strip().upper()
    if ts in {"N", "CLOSED", "заверш".upper()}:
        # Keep CLOSED when we still have an OPEN for fill / valuation.
        freshness = QuoteFreshness.MARKET_CLOSED if open_price is None else QuoteFreshness.DELAYED
        return MarketSessionStatus.CLOSED, freshness, "trading_status_closed"
    if ts in {"B", "C", "PREOPEN", "OPENING"}:
        return (
            MarketSessionStatus.PREOPEN,
            QuoteFreshness.SESSION_NOT_STARTED,
            "preopen",
        )
    if open_price is None and last_price is None and (num_trades is None or num_trades <= 0):
        if ts in {"", "UNKNOWN"}:
            return MarketSessionStatus.UNKNOWN, QuoteFreshness.NO_TRADES, "no_trades"
        return MarketSessionStatus.OPEN, QuoteFreshness.NO_TRADES, "no_trades_yet"
    if open_price is None and (num_trades is None or num_trades <= 0):
        return MarketSessionStatus.OPEN, QuoteFreshness.NO_TRADES, "open_missing"
    return MarketSessionStatus.OPEN, QuoteFreshness.LIVE, "ok"


def parse_board_securities_payload(
    payload: dict[str, Any],
    *,
    board: str,
    wanted: set[str] | None,
    observed_at: datetime,
) -> list[IntradayQuote]:
    """Parse ISS board securities.json into IntradayQuote rows (no invented prices)."""
    marketdata = {str(r.get("SECID")): r for r in _rows_as_dicts(payload.get("marketdata"))}
    securities = {str(r.get("SECID")): r for r in _rows_as_dicts(payload.get("securities"))}
    secids = wanted if wanted is not None else set(marketdata) | set(securities)
    quotes: list[IntradayQuote] = []
    for secid in sorted(secids):
        md = marketdata.get(secid) or {}
        sec = securities.get(secid) or {}
        if not md and not sec:
            continue
        trading_date = _infer_trading_date(md, observed_at)
        open_price = _float(md.get("OPEN"))
        last_price = _float(md.get("LAST"))
        bid = _float(md.get("BID"))
        ask = _float(md.get("OFFER"))
        prev = _float(sec.get("PREVLEGALCLOSEPRICE"))
        if prev is None:
            prev = _float(sec.get("PREVPRICE"))
        volume = _float(md.get("VOLTODAY"))
        num_trades = _float(md.get("NUMTRADES"))
        source_ts = _parse_dt(md.get("SYSTIME"), trading_date=trading_date) or _parse_dt(
            md.get("UPDATETIME"), trading_date=trading_date
        )
        market_status, freshness, quality = _map_status(
            trading_status=md.get("TRADINGSTATUS"),
            status=md.get("STATUS") or sec.get("STATUS"),
            open_price=open_price,
            last_price=last_price,
            num_trades=num_trades,
        )
        quotes.append(
            IntradayQuote(
                secid=secid,
                board=str(md.get("BOARDID") or sec.get("BOARDID") or board),
                trading_date=trading_date,
                observed_at=observed_at,
                source_timestamp=source_ts,
                market_status=market_status,
                open_price=open_price,
                last_price=last_price,
                bid=bid,
                ask=ask,
                previous_close=prev,
                volume=volume,
                source=SOURCE,
                freshness=freshness,
                quality=quality,
            )
        )
    return quotes


class MoexIntradayProvider(IntradayMarketPort):
    """Batch board marketdata from MOEX ISS. Never writes market.candles."""

    def __init__(
        self,
        client: MarketHttpClient | None = None,
        base_url: str | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else float(settings.intraday_http_timeout_seconds)
        )
        self.client = client or MarketHttpClient(timeout=timeout)
        self.base_url = (base_url or settings.moex_base_url).rstrip("/")

    def fetch_quotes(
        self,
        secids_by_board: dict[str, list[str]],
        *,
        observed_at: datetime | None = None,
    ) -> list[IntradayQuote]:
        observed = observed_at or datetime.now(UTC)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        out: list[IntradayQuote] = []
        for board, secids in secids_by_board.items():
            board_u = str(board).upper()
            wanted = {str(s).upper() for s in secids if s}
            if not wanted:
                continue
            market = BOARD_MARKET.get(board_u, SHARES_MARKET)
            url = (
                f"{self.base_url}/iss/engines/stock/markets/{market}"
                f"/boards/{board_u}/securities.json"
            )
            response = self.client.get(
                url,
                params={
                    "iss.meta": "off",
                    "iss.only": "securities,marketdata",
                    "securities.columns": SECURITIES_COLUMNS,
                    "marketdata.columns": MARKETDATA_COLUMNS,
                },
            )
            payload = response.json()
            out.extend(
                parse_board_securities_payload(
                    payload,
                    board=board_u,
                    wanted=wanted,
                    observed_at=observed,
                )
            )
        return out
