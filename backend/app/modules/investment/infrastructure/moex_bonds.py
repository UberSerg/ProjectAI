"""Bounded MOEX ISS bond audit client.

Only fields actually returned by ISS are preserved. Interpretation is deliberately
deferred to the application classifier when semantics are incomplete.
"""

from __future__ import annotations

from typing import Any

from app.infrastructure.market.http_client import MarketHttpClient

BOARDS = ("TQOB", "TQCB")


class MoexBondClient:
    def __init__(
        self,
        client: MarketHttpClient | None = None,
        base_url: str = "https://iss.moex.com/iss",
    ) -> None:
        self.client = client or MarketHttpClient()
        self.base_url = base_url.rstrip("/")

    def audit(self, *, limit: int = 20) -> dict[str, Any]:
        bounded_limit = max(1, min(limit, 100))
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

    def _fetch_board(self, board: str, limit: int) -> list[dict[str, Any]]:
        response = self.client.get(
            f"{self.base_url}/engines/stock/markets/bonds/boards/{board}/securities.json",
            params={
                "iss.meta": "off",
                "iss.only": "securities,marketdata",
                "securities.limit": limit,
                "marketdata.limit": limit,
            },
        )
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
