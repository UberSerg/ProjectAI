"""Bank / FI path must not emit industrial ratios (Agent C owns banks)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import SUPPORT_BANK
from app.modules.intelligence.fundamentals.constants import (
    ISSUER_KIND_BANK_FI,
    STATUS_NOT_AVAILABLE,
)
from app.modules.intelligence.fundamentals.service import (
    build_fundamental_snapshot,
    resolve_issuer_kind,
)


def test_resolve_issuer_kind_bank_by_secid() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(symbol="SBER")
    mapping = SimpleNamespace(external_secid="SBER", mapping_status="MAPPED")
    session.scalar.return_value = mapping
    issuer = SimpleNamespace(metadata_={})
    kind, limits = resolve_issuer_kind(session, 1, issuer)
    assert kind == ISSUER_KIND_BANK_FI
    assert limits


def test_resolve_issuer_kind_bank_by_fns_meta() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(symbol="XYZ")
    session.scalar.return_value = SimpleNamespace(external_secid="XYZ")
    issuer = SimpleNamespace(metadata_={"fns": {"support_status": SUPPORT_BANK}})
    kind, _limits = resolve_issuer_kind(session, 2, issuer)
    assert kind == ISSUER_KIND_BANK_FI


def test_bank_snapshot_not_available(monkeypatch) -> None:
    session = MagicMock()

    monkeypatch.setattr(
        "app.modules.intelligence.fundamentals.service.fundamentals_schema_ready",
        lambda _s: True,
    )
    monkeypatch.setattr(
        "app.modules.intelligence.fundamentals.service.pit.resolve_issuer_for_instrument",
        lambda *_a, **_k: SimpleNamespace(issuer_id=99, basis="CURRENT_ONLY"),
    )
    monkeypatch.setattr(
        "app.modules.intelligence.fundamentals.service.resolve_issuer_kind",
        lambda *_a, **_k: (ISSUER_KIND_BANK_FI, ("BANK_FI industrial RAS ratios unsupported",)),
    )

    snap = build_fundamental_snapshot(session, instrument_id=1, as_of=date(2025, 6, 1))
    assert snap.issuer_kind == ISSUER_KIND_BANK_FI
    assert snap.status == STATUS_NOT_AVAILABLE
    assert snap.metrics.get("derived") in (None, {})
    assert "industrial_ratios" in snap.missing_metrics
    assert any("Agent C" in lim or "BANK_FI" in lim for lim in snap.limitations)
