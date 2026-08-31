"""HTTP response helpers with explicit UTF-8 charset."""

from __future__ import annotations

from fastapi.responses import JSONResponse


class UTF8JSONResponse(JSONResponse):
    """JSON responses declare charset so Windows clients (PS 5.1) decode correctly."""

    media_type = "application/json; charset=utf-8"
