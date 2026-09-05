"""Bounded MOEX ISS bond audit client.

Only fields actually returned by ISS are preserved. Interpretation is deliberately
deferred to the application classifier when semantics are incomplete.

Uses ``trust_env=False`` by default so a broken local SOCKS proxy cannot block audits.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.infrastructure.market.http_client import MarketHttpClient

BOARDS = ("TQOB", "TQCB")


class MoexBondClient:
    def __init__(
        self,
        client: MarketHttpClient | httpx.Client | None = None,
        base_url: str = "https://iss.moex.com/iss",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        if isinstance(client, MarketHttpClient):
            self._http: MarketHttpClient | httpx.Client = client
            self._owns = False
        elif client is not None:
            self._http = client
            self._owns = False
        else:
            self._http = httpx.Client(
                timeout=30.0,
                follow_redirects=True,
                trust_env=False,
                headers={"User-Agent": "ProjectAI-InvestmentFoundationV0/1.0"},
            )
            self._owns = True

    def close(self) -> None:
        if self._owns and isinstance(self._http, httpx.Client):
            self._http.close()

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
            self.close()

    def _fetch_board(self, board: str, limit: int) -> list[dict[str, Any]]:
        url = f"{self.base_url}/engines/stock/markets/bonds/boards/{board}/securities.json"
        params = {
            "iss.meta": "off",
            "iss.only": "securities,marketdata",
            "securities.limit": limit,
            "marketdata.limit": limit,
        }
        if isinstance(self._http, MarketHttpClient):
            response = self._http.get(url, params=params)
        else:
            response = self._http.get(url, params=params)
            response.raise_for_status()
        payload = response.json()
        return _observed_rows(payload, "securities")[:limit]


def _observed_rows(payload: dict[str, Any], block: str) -> list[dict[str, Any]]:
    table = payload.get(block) or {}
    columns = table.get("columns") or []
    data = table.get("data") or []
    return [
        {str(column): value for column, value in zip(columns, row, strict=False)}
        for row in data
    ]
