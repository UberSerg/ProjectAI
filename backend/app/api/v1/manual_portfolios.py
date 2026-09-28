"""Legacy Manual Portfolio routes — retired for Multi-Portfolio V2.

Product surface moved to ``/personal-portfolios/{id}/...``.
This module remains registered only to return explicit 410 Gone for /primary.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()

_GONE = {
    "code": "PRIMARY_RETIRED",
    "message": (
        "Singleton /manual-portfolios/primary retired. "
        "Use /personal-portfolios and /personal-portfolios/{portfolio_id}/..."
    ),
}


@router.api_route("/primary", methods=["GET", "PUT", "POST", "PATCH", "DELETE"])
@router.api_route("/primary/{path:path}", methods=["GET", "PUT", "POST", "PATCH", "DELETE"])
def primary_retired(path: str | None = None) -> dict[str, Any]:
    raise HTTPException(status_code=410, detail=_GONE)
