"""Build MacroSnapshotV1 from local CBR series + MOEX daily candles (PIT)."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.modules.intelligence.contracts.snapshots_domain import MacroSnapshotV1
from app.modules.intelligence.macro.constants import (
    REGIME_AXES,
    STATUS_NOT_AVAILABLE,
    STATUS_PARTIAL,
    STATUS_READY,
)
from app.modules.intelligence.macro.observations import assemble_observations
from app.modules.intelligence.macro.persistence import persist_macro_snapshot
from app.modules.intelligence.macro.regimes import classify_regimes

_READY_VALUE_KEYS = (
    "key_rate",
    "usd_rub",
    "usd_rub_pct_change_20d",
    "imoex_return_20d",
    "imoex_realized_vol_20d",
)


def _has_numeric_value(observations: dict[str, Any], key: str) -> bool:
    raw = observations.get(key)
    if not isinstance(raw, dict):
        return False
    val = raw.get("value")
    return isinstance(val, int | float)


def _market_wide_regime(regimes: dict[str, str]) -> str:
    trend = regimes.get("MARKET_TREND")
    vol = regimes.get("VOLATILITY")
    if trend == "risk-off" or vol == "stress":
        return "ADVERSE"
    if trend == "risk-on" and vol in {"calm", "elevated"}:
        return "SUPPORTIVE"
    if trend in {"neutral", "risk-on", "risk-off"}:
        return "NEUTRAL"
    return "UNKNOWN"


def resolve_status(observations: dict[str, Any]) -> str:
    flags = [_has_numeric_value(observations, k) for k in _READY_VALUE_KEYS]
    if not any(flags):
        return STATUS_NOT_AVAILABLE
    if all(flags):
        return STATUS_READY
    return STATUS_PARTIAL


def build_macro_snapshot(
    session: Session,
    as_of: date,
    *,
    persist: bool = False,
    include_breadth: bool = True,
) -> MacroSnapshotV1:
    """PIT-safe MacroSnapshotV1 for calendar date ``as_of``."""
    observations, limitations, sources, max_known = assemble_observations(
        session,
        as_of,
        include_breadth=include_breadth,
    )
    regimes = {
        k: v for k, v in classify_regimes(observations).items() if k in REGIME_AXES
    }
    # Market-wide advisory label for MacroModelV1 (SUPPORTIVE/NEUTRAL/ADVERSE/UNKNOWN).
    regimes["market"] = _market_wide_regime(regimes)
    status = resolve_status(observations)
    snap = MacroSnapshotV1(
        as_of=as_of,
        known_at=max_known,
        status=status,
        observations=observations,
        regimes=regimes,
        limitations=tuple(dict.fromkeys(limitations)),
        sources=tuple(dict.fromkeys(sources)),
    )
    if persist:
        persist_macro_snapshot(session, snap, commit=False)
    return snap


class MacroRegimeService:
    """Session-backed macro / regime snapshot builder."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def snapshot(
        self,
        as_of: date,
        *,
        persist: bool = False,
        include_breadth: bool = True,
    ) -> MacroSnapshotV1:
        return build_macro_snapshot(
            self.session,
            as_of,
            persist=persist,
            include_breadth=include_breadth,
        )
