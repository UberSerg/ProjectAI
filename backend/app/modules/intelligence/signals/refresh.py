"""Refresh hooks for BUILD_SNAPSHOTS / RUN_MODELS stages."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session


def refresh_build_snapshots(session: Session, ctx: dict[str, Any]) -> dict[str, Any]:
    as_of = ctx.get("as_of")
    ids = list(ctx.get("instrument_ids") or [])
    return {
        "status": "SUCCESS",
        "changed": False,
        "reason": "SNAPSHOTS_COMPUTED_ON_READ",
        "instrument_ids": ids,
        "as_of": str(as_of) if as_of else None,
    }


def refresh_run_models(session: Session, ctx: dict[str, Any]) -> dict[str, Any]:
    from app.modules.intelligence.signals.collect import collect_instrument_signals

    as_of_raw = ctx.get("as_of")
    try:
        as_of = date.fromisoformat(str(as_of_raw)[:10]) if as_of_raw else date.today()
    except ValueError:
        as_of = date.today()
    ids = [int(i) for i in (ctx.get("instrument_ids") or [])]
    ran = 0
    for iid in ids[:20]:
        collect_instrument_signals(instrument_id=iid, as_of=as_of, session=session)
        ran += 1
    return {
        "status": "SUCCESS" if ran or not ids else "NO_CHANGES",
        "changed": False,
        "models_ran": ran,
        "reason": "INDEPENDENT_MODELS_ON_DEMAND",
    }
