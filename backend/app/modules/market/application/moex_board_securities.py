"""Fetch MOEX ISS securities lists for Instrument Master boards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import get_settings
from app.infrastructure.market.http_client import MarketHttpClient

SHARE_BOARDS = ("TQBR", "TQTF", "SMAL")
BOND_BOARDS = ("TQOB", "TQCB")
DEFAULT_BOARDS: tuple[tuple[str, str], ...] = (
    ("shares", "TQBR"),
    ("shares", "TQTF"),
    ("shares", "SMAL"),
    ("bonds", "TQOB"),
    ("bonds", "TQCB"),
)


@dataclass(frozen=True, slots=True)
class MoexSecurityRow:
    secid: str
    board: str
    market: str
    name: str | None
    isin: str | None
    lotsize: int | None
    sec_type: str | None
    is_traded: bool | None
    currency: str | None
    raw: dict[str, Any]


class BoardSecuritiesPort(Protocol):
    def fetch_board_securities(self, market: str, board: str) -> list[MoexSecurityRow]: ...


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def parse_board_securities_payload(
    payload: dict[str, Any], *, market: str, board: str
) -> list[MoexSecurityRow]:
    block = payload.get("securities") or {}
    columns = block.get("columns") or []
    rows: list[MoexSecurityRow] = []
    for values in block.get("data") or []:
        row = dict(zip(columns, values, strict=False))
        secid = str(row.get("SECID") or "").strip().upper()
        if not secid:
            continue
        traded_raw = row.get("STATUS") or row.get("IS_TRADED") or row.get("TRADINGSTATUS")
        is_traded: bool | None
        if traded_raw in (None, ""):
            is_traded = True
        elif str(traded_raw).upper() in {"N", "0", "FALSE", "SUSPENDED"}:
            is_traded = False
        else:
            is_traded = True
        currency = row.get("FACEUNIT") or row.get("CURRENCYID") or row.get("FACEVALUECURRENCY")
        if currency == "SUR":
            currency = "RUB"
        rows.append(
            MoexSecurityRow(
                secid=secid,
                board=board.upper(),
                market=market.lower(),
                name=(str(row.get("SHORTNAME") or row.get("SECNAME") or "").strip() or None),
                isin=(str(row.get("ISIN") or "").strip() or None),
                lotsize=_int_or_none(row.get("LOTSIZE")),
                sec_type=(str(row.get("SECTYPE") or row.get("TYPE") or "").strip() or None),
                is_traded=is_traded,
                currency=(str(currency).strip() if currency not in (None, "") else "RUB"),
                raw=row,
            )
        )
    return rows


class MoexBoardSecuritiesClient:
    """Paginated ISS board securities lists (shares + bonds)."""

    def __init__(
        self,
        client: MarketHttpClient | None = None,
        base_url: str | None = None,
    ) -> None:
        self.client = client or MarketHttpClient()
        self.base_url = (base_url or get_settings().moex_base_url).rstrip("/")

    def fetch_board_securities(self, market: str, board: str) -> list[MoexSecurityRow]:
        market_u = market.lower()
        board_u = board.upper()
        url = (
            f"{self.base_url}/iss/engines/stock/markets/{market_u}"
            f"/boards/{board_u}/securities.json"
        )
        collected: list[MoexSecurityRow] = []
        start = 0
        while True:
            response = self.client.get(
                url,
                params={
                    "iss.meta": "off",
                    "iss.only": "securities",
                    "securities.start": start,
                    "securities.columns": (
                        "SECID,SHORTNAME,SECNAME,ISIN,LOTSIZE,SECTYPE,STATUS,"
                        "FACEUNIT,CURRENCYID,TYPENAME"
                    ),
                },
            )
            payload = response.json()
            page = parse_board_securities_payload(payload, market=market_u, board=board_u)
            if not page:
                break
            collected.extend(page)
            if len(page) < 100:
                break
            start += len(page)
            if start > 50_000:
                break
        return collected
