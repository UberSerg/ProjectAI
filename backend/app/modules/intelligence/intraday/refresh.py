"""Intraday refresh. Live MOEX only when ctx['live_fetch'] is true."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def refresh_market_intraday(session: Session, ctx: dict[str, Any]) -> dict[str, Any]:
    if ctx.get("dry_run") or not ctx.get("live_fetch"):
        return {"status": "SKIPPED", "reason": "LIVE_FETCH_DISABLED", "changed": False}
    from app.modules.intelligence.intraday.application.service import smoke_live

    symbols = list(ctx.get("symbols") or ["SBER", "LKOH", "MGNT"])
    try:
        result = smoke_live(session, symbols, lookback_days=5)
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAILED", "reason": "INTRADAY_REFRESH_ERROR", "error": str(exc)[:500]}
    mode = result.get("mode") if isinstance(result, dict) else None
    return {"status": "SUCCESS", "changed": True, "details": {"mode": mode}}
