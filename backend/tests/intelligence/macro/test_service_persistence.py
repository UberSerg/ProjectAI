"""Macro snapshot service + persistence against transactional core_db."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.intelligence.contracts.snapshots_domain import MacroSnapshotV1
from app.modules.intelligence.macro import (
    MacroRegimeService,
    build_macro_snapshot,
    macro_snapshots_schema_ready,
    persist_macro_snapshot,
)
from app.modules.intelligence.macro.constants import (
    REGIME_AXES,
    STATUS_NOT_AVAILABLE,
    STATUS_PARTIAL,
    STATUS_READY,
)
from app.modules.intelligence.macro.service import resolve_status


def test_resolve_status_rules() -> None:
    assert resolve_status({}) == STATUS_NOT_AVAILABLE
    assert (
        resolve_status({"key_rate": {"value": 14.0}}) == STATUS_PARTIAL
    )
    ready = {
        "key_rate": {"value": 14.0},
        "usd_rub": {"value": 90.0},
        "usd_rub_pct_change_20d": {"value": 0.01},
        "imoex_return_20d": {"value": 0.02},
        "imoex_realized_vol_20d": {"value": 0.01},
    }
    assert resolve_status(ready) == STATUS_READY


def test_macro_snapshot_contract_roundtrip() -> None:
    snap = MacroSnapshotV1(
        as_of=date(2026, 9, 29),
        known_at=date(2026, 9, 29),
        status=STATUS_PARTIAL,
        observations={"policy_version": "macro_regime_thresholds_v1"},
        regimes={"RATE": "easing"},
        limitations=("x",),
        sources=("CBR:KEY_RATE",),
    )
    d = snap.to_dict()
    assert d["schema"] == "MacroSnapshotV1"
    assert d["as_of"] == "2026-09-29"
    assert d["regimes"]["RATE"] == "easing"


def test_build_macro_snapshot_real_local_data(core_db: Session) -> None:
    as_of = date(2026, 9, 29)
    snap = build_macro_snapshot(core_db, as_of, persist=False, include_breadth=True)
    assert snap.schema == "MacroSnapshotV1"
    assert snap.as_of == as_of
    assert snap.status in {STATUS_READY, STATUS_PARTIAL, STATUS_NOT_AVAILABLE}
    assert set(REGIME_AXES).issubset(snap.regimes.keys())
    assert snap.regimes["RATE"] in {"easing", "neutral", "tightening", "unknown"}
    assert snap.regimes["MARKET_TREND"] in {"risk-on", "neutral", "risk-off", "unknown"}
    assert snap.regimes["VOLATILITY"] in {"calm", "elevated", "stress", "unknown"}
    assert snap.regimes["FX"] in {"strengthening", "stable", "weakening", "unknown"}
    assert snap.observations.get("gov_yield_curve") is None
    assert snap.observations.get("short_long_spread") is None
    assert any("yield_curve" in lim.lower() or "YTM" in lim for lim in snap.limitations)
    if snap.status == STATUS_NOT_AVAILABLE or snap.known_at is None:
        pytest.skip("local warehouse has no CBR/MOEX series for as_of (CI empty DB)")
    # PIT: known_at must not exceed as_of
    known = snap.known_at if isinstance(snap.known_at, date) else snap.known_at.date()
    assert known <= as_of
    # Core series should be present on this as_of in the local warehouse
    assert snap.observations.get("key_rate") is not None
    assert snap.observations.get("usd_rub") is not None
    assert snap.observations.get("imoex_return_20d") is not None


def test_persist_macro_snapshot_upsert(core_db: Session) -> None:
    if not macro_snapshots_schema_ready(core_db):
        pytest.skip("intelligence.macro_snapshots schema not ready")
    as_of = date(2026, 9, 28)
    # Persistence must work even when warehouse series are absent (CI).
    snap = MacroSnapshotV1(
        as_of=as_of,
        known_at=as_of,
        status=STATUS_PARTIAL,
        observations={"key_rate": {"value": 16.0, "as_of": as_of.isoformat()}},
        regimes={
            "RATE": "neutral",
            "MARKET_TREND": "unknown",
            "VOLATILITY": "unknown",
            "FX": "unknown",
            "market": "UNKNOWN",
        },
        limitations=("ci_fixture",),
        sources=("TEST",),
    )
    result = persist_macro_snapshot(core_db, snap, commit=False)
    assert result.get("persisted") is True
    # Idempotent upsert
    result2 = persist_macro_snapshot(core_db, snap, commit=False)
    assert result2.get("persisted") is True
    row = core_db.execute(
        text(
            "SELECT status, snapshot_hash, regimes->>'RATE' AS rate "
            "FROM intelligence.macro_snapshots WHERE as_of = :as_of"
        ),
        {"as_of": as_of},
    ).mappings().first()
    assert row is not None
    assert row["status"] == snap.status
    assert row["snapshot_hash"]
    assert row["rate"] == snap.regimes.get("RATE")
    # Service path still callable; skip warehouse assertions when empty.
    svc_snap = MacroRegimeService(core_db).snapshot(as_of, persist=False, include_breadth=False)
    assert svc_snap.schema == "MacroSnapshotV1"
