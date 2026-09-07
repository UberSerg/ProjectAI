"""Resolve equity LOTSIZE from MOEX instrument sources with provenance.

Never invents lot_size=1. Missing / invalid LOTSIZE stays unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.infrastructure.market.models import Instrument, InstrumentSource
from app.infrastructure.market.moex_iss import MoexIssProvider

PREFERRED_EQUITY_BOARDS = ("TQBR", "TQTF", "SMAL")
LOTSIZE_META_KEY = "LOTSIZE"
LOTSIZE_PROVENANCE_KEY = "lotsize_provenance"


@dataclass(frozen=True, slots=True)
class EquityLotResolution:
    instrument_id: int
    symbol: str
    lot_size: int | None
    board: str | None
    external_id: str | None
    source: str
    status: str  # OK | MISSING_SOURCE | UNKNOWN_LOTSIZE | FETCH_FAILED
    provenance: dict[str, Any]


def resolve_equity_lot_sizes(
    session: Session,
    instruments: list[Instrument],
    *,
    fetch_missing: bool = True,
    moex: MoexIssProvider | None = None,
) -> dict[int, EquityLotResolution]:
    """Map instrument_id → LOTSIZE resolution. Persist newly fetched values into source_metadata."""
    if not instruments:
        return {}

    ids = [int(i.id) for i in instruments]
    sources = list(
        session.scalars(
            select(InstrumentSource).where(
                InstrumentSource.instrument_id.in_(ids),
                InstrumentSource.source == "MOEX",
            )
        )
    )
    by_instrument: dict[int, list[InstrumentSource]] = {}
    for src in sources:
        by_instrument.setdefault(int(src.instrument_id), []).append(src)

    provider = moex
    out: dict[int, EquityLotResolution] = {}
    for instrument in instruments:
        iid = int(instrument.id)
        chosen = _pick_source(by_instrument.get(iid) or [])
        if chosen is None:
            out[iid] = EquityLotResolution(
                instrument_id=iid,
                symbol=instrument.symbol,
                lot_size=None,
                board=None,
                external_id=None,
                source="MOEX",
                status="MISSING_SOURCE",
                provenance={"reason": "no_moex_instrument_source"},
            )
            continue

        meta = dict(chosen.source_metadata or {})
        cached = _lot_from_meta(meta)
        if cached is not None:
            out[iid] = EquityLotResolution(
                instrument_id=iid,
                symbol=instrument.symbol,
                lot_size=cached,
                board=chosen.board,
                external_id=chosen.external_id,
                source="MOEX",
                status="OK",
                provenance=_cached_provenance(meta, chosen),
            )
            continue

        if not fetch_missing:
            out[iid] = EquityLotResolution(
                instrument_id=iid,
                symbol=instrument.symbol,
                lot_size=None,
                board=chosen.board,
                external_id=chosen.external_id,
                source="MOEX",
                status="UNKNOWN_LOTSIZE",
                provenance={
                    "reason": "lotsize_not_in_source_metadata",
                    "board": chosen.board,
                    "external_id": chosen.external_id,
                },
            )
            continue

        if provider is None:
            provider = MoexIssProvider()
        board = (chosen.board or "TQBR").strip() or "TQBR"
        external_id = (chosen.external_id or instrument.symbol).strip()
        try:
            lot, _raw = provider.fetch_share_lot_size(external_id, board=board)
        except Exception as exc:  # noqa: BLE001 — network/provider; keep candidate honest
            out[iid] = EquityLotResolution(
                instrument_id=iid,
                symbol=instrument.symbol,
                lot_size=None,
                board=board,
                external_id=external_id,
                source="MOEX",
                status="FETCH_FAILED",
                provenance={
                    "reason": "moex_lotsize_fetch_failed",
                    "error": type(exc).__name__,
                    "board": board,
                    "external_id": external_id,
                },
            )
            continue

        if lot is None:
            out[iid] = EquityLotResolution(
                instrument_id=iid,
                symbol=instrument.symbol,
                lot_size=None,
                board=board,
                external_id=external_id,
                source="MOEX",
                status="UNKNOWN_LOTSIZE",
                provenance={
                    "reason": "moex_lotsize_absent",
                    "board": board,
                    "external_id": external_id,
                    "endpoint": (
                        "/iss/engines/stock/markets/shares"
                        f"/boards/{board}/securities/{external_id}.json"
                    ),
                },
            )
            continue

        fetched_at = datetime.now(UTC).isoformat()
        provenance = {
            "field": "LOTSIZE",
            "source": "MOEX_ISS",
            "board": board,
            "external_id": external_id,
            "endpoint": (
                "/iss/engines/stock/markets/shares"
                f"/boards/{board}/securities/{external_id}.json"
            ),
            "fetched_at": fetched_at,
            "value": lot,
        }
        meta[LOTSIZE_META_KEY] = lot
        meta[LOTSIZE_PROVENANCE_KEY] = provenance
        chosen.source_metadata = meta
        flag_modified(chosen, "source_metadata")
        out[iid] = EquityLotResolution(
            instrument_id=iid,
            symbol=instrument.symbol,
            lot_size=lot,
            board=board,
            external_id=external_id,
            source="MOEX",
            status="OK",
            provenance=provenance,
        )

    return out


def _pick_source(sources: list[InstrumentSource]) -> InstrumentSource | None:
    if not sources:
        return None
    by_board = {str(s.board or "").upper(): s for s in sources}
    for board in PREFERRED_EQUITY_BOARDS:
        if board in by_board:
            return by_board[board]
    # Prefer sources that already carry LOTSIZE.
    for src in sources:
        if _lot_from_meta(src.source_metadata or {}) is not None:
            return src
    return sources[0]


def _lot_from_meta(meta: dict[str, Any]) -> int | None:
    raw = meta.get(LOTSIZE_META_KEY)
    if raw in (None, ""):
        return None
    try:
        lot = int(raw)
    except (TypeError, ValueError):
        return None
    return lot if lot > 0 else None


def _cached_provenance(meta: dict[str, Any], src: InstrumentSource) -> dict[str, Any]:
    existing = meta.get(LOTSIZE_PROVENANCE_KEY)
    if isinstance(existing, dict) and existing:
        return dict(existing)
    return {
        "field": "LOTSIZE",
        "source": "MOEX_ISS",
        "board": src.board,
        "external_id": src.external_id,
        "origin": "instrument_sources.source_metadata",
        "value": meta.get(LOTSIZE_META_KEY),
    }
