"""Fundamentals refresh.

Industrial FNS snapshots stay on-read. Bank/FI metrics are fetched only when
``live_fetch`` is true, then stored. A later GET reads that row and does not
call CBR.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session


def refresh_fundamentals(session: Session, ctx: dict[str, Any]) -> dict[str, Any]:
    instrument_ids = [int(item) for item in (ctx.get("instrument_ids") or [])]
    if ctx.get("dry_run") or not ctx.get("live_fetch"):
        return {
            "status": "SUCCESS",
            "changed": False,
            "reason": "FNS_SNAPSHOTS_ON_READ",
            "bank_live_fetch": False,
            "instrument_ids": instrument_ids,
        }

    as_of = _as_of(ctx.get("as_of"))
    observed_at = datetime.now(UTC)
    persisted: list[dict[str, Any]] = []
    for instrument_id in instrument_ids:
        outcome = _persist_bank_if_applicable(
            session,
            instrument_id=instrument_id,
            as_of=as_of,
            observed_at=observed_at,
        )
        if outcome is not None:
            persisted.append(outcome)
    return {
        "status": "SUCCESS" if persisted else "NO_CHANGES",
        "changed": bool(persisted),
        "reason": "BANK_CBR_OBSERVED" if persisted else "NO_BANK_INSTRUMENTS",
        "bank_live_fetch": True,
        "observed_at": observed_at.isoformat(),
        "instrument_ids": instrument_ids,
        "banks": persisted,
    }


def _as_of(raw: Any) -> date:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if raw:
        return date.fromisoformat(str(raw)[:10])
    return datetime.now(UTC).date()


def _persist_bank_if_applicable(
    session: Session,
    *,
    instrument_id: int,
    as_of: date,
    observed_at: datetime,
) -> dict[str, Any] | None:
    from app.infrastructure.market.models import Instrument
    from app.modules.intelligence.banks.classification import is_bank_fi_secid
    from app.modules.intelligence.banks.metrics import INDUSTRIAL_RATIO_CODES
    from app.modules.intelligence.banks.service import build_bank_fi_fundamental_snapshot
    from app.modules.intelligence.banks.snapshot import assert_no_industrial_fallback
    from app.modules.intelligence.fundamentals.persistence import persist_fundamental_snapshot

    instrument = session.get(Instrument, instrument_id)
    if instrument is None or not is_bank_fi_secid(instrument.symbol):
        return None
    snapshot = build_bank_fi_fundamental_snapshot(
        secid=instrument.symbol,
        instrument_id=instrument_id,
        as_of=as_of,
        known_at=observed_at,
        load_cbr_soap_live=True,
    )
    if snapshot.known_at == snapshot.period_end:
        raise RuntimeError("bank known_at must be the observation time, not period_end")
    assert_no_industrial_fallback(snapshot)
    industrial = set(snapshot.metrics) & INDUSTRIAL_RATIO_CODES
    if industrial:
        raise RuntimeError(f"industrial ratios on bank snapshot: {sorted(industrial)}")
    stored = persist_fundamental_snapshot(session, snapshot)
    return {
        "symbol": instrument.symbol,
        "instrument_id": instrument_id,
        "issuer_kind": snapshot.issuer_kind,
        "status": snapshot.status,
        "known_at": observed_at.isoformat(),
        "period_end": snapshot.period_end.isoformat() if snapshot.period_end else None,
        "provider": snapshot.provider,
        "metric_codes": sorted(snapshot.metrics),
        "persisted": stored.get("persisted"),
    }
