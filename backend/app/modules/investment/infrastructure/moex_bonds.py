"""Bounded MOEX ISS bond audit + bondization cashflow client.
Only fields actually returned by ISS are preserved.
Uses ``trust_env=False`` by default so a broken local SOCKS proxy cannot block audits.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.infrastructure.market.http_client import MarketHttpClient

BOARDS = ("TQOB", "TQCB")
SOURCE_BOARD = "MOEX_ISS"
SOURCE_BONDIZATION = "MOEX_ISS_BONDIZATION"

class MoexBondClient:
    def __init__(
        self,
        client: MarketHttpClient | httpx.Client | None = None,
        base_url: str = "https://iss.moex.com/iss",
        *,
        auto_close: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._auto_close = auto_close
        if isinstance(client, MarketHttpClient):
            self._http: MarketHttpClient | httpx.Client = client
            self._owns = False
        elif client is not None:
            self._http = client
            self._owns = False
        else:
            self._http = httpx.Client(
                timeout=60.0,
                follow_redirects=True,
                trust_env=False,
                headers={"User-Agent": "ProjectAI-FixedIncomeCashflowV1/1.0"},
            )
            self._owns = True
    def close(self) -> None:
        if self._owns and isinstance(self._http, httpx.Client):
            self._http.close()
    def __enter__(self) -> MoexBondClient:
        return self
    def __exit__(self, *args: object) -> None:
        self.close()
    def audit(self, *, limit: int = 20) -> dict[str, Any]:
        bounded_limit = max(1, min(limit, 100))
        try:
            return {
                "boards": [
                    {
                        "board": board,
                        "rows": self._fetch_board(board, bounded_limit),
                    }
                    for board in BOARDS
                ],
                "bounded_limit": bounded_limit,
                "semantics": "OBSERVED_FIELDS_ONLY",
            }
        finally:
            if self._auto_close:
                self.close()
    def fetch_board_rows(self, board: str, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._fetch_board(board, max(1, min(limit, 100)))
    def fetch_bondization(self, secid: str) -> dict[str, list[dict[str, Any]]]:
        """Current-state coupon / amortization / offer schedule for one security.
        Endpoint: ``/iss/securities/{secid}/bondization.json``
        known_at quality: CURRENT_STATE_ONLY (no publication timestamp).
        """
        coupons = self._paginate_block(secid, "coupons")
        amortizations = self._paginate_block(secid, "amortizations")
        offers = self._paginate_block(secid, "offers")
        return {
            "coupons": coupons,
            "amortizations": amortizations,
            "offers": offers,
        }
    def _paginate_block(self, secid: str, block: str) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        start = 0
        page_size = 100
        while True:
            payload = self._get_json(
                f"/securities/{secid}/bondization.json",
                {
                    "iss.meta": "off",
                    "iss.only": block,
                    f"{block}.start": start,
                    f"{block}.limit": page_size,
                },
            )
            page = _observed_rows(payload, block)
            if not page:
                break
            collected.extend(page)
            if len(page) < page_size:
                break
            start += len(page)
            if start > 2000:
                break
        return collected
    def _fetch_board(self, board: str, limit: int) -> list[dict[str, Any]]:
        url = f"{self.base_url}/engines/stock/markets/bonds/boards/{board}/securities.json"
        params = {
            "iss.meta": "off",
            "iss.only": "securities,marketdata",
            "securities.limit": limit,
            "marketdata.limit": limit,
        }
        payload = self._get_json_url(url, params)
        return _observed_rows(payload, "securities")[:limit]
    def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._get_json_url(f"{self.base_url}{path}", params)
    def _get_json_url(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self._http, MarketHttpClient):
            response = self._http.get(url, params=params)
        else:
            response = self._http.get(url, params=params)
            response.raise_for_status()
        return response.json()

def _observed_rows(payload: dict[str, Any], block: str) -> list[dict[str, Any]]:
    table = payload.get(block) or {}
    columns = table.get("columns") or []
    data = table.get("data") or []
    return [
        {str(column): value for column, value in zip(columns, row, strict=False)}
        for row in data
    ]
