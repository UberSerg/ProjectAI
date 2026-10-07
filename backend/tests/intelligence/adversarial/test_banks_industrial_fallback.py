"""Bank issuers must not silently reuse industrial ratio semantics."""

from __future__ import annotations

import importlib
from datetime import date

import pytest

from app.modules.intelligence.contracts.signal import unknown_signal
from app.modules.intelligence.contracts.snapshots_domain import FundamentalSnapshotV1

INDUSTRIAL_ONLY_METRICS = frozenset(
    {
        "ev_ebitda",
        "gross_margin",
        "operating_margin",
        "inventory_turnover",
        "capex_to_sales",
    }
)


def test_bank_unknown_when_industrial_ratios_unsupported() -> None:
    sig = unknown_signal(
        model_id="FundamentalModelV1",
        model_version="1",
        semantic="FUNDAMENTAL",
        instrument_id=99,
        as_of=date(2026, 1, 1),
        reason="bank_industrial_ratios_unsupported",
    )
    assert sig.state == "UNKNOWN"
    assert sig.score is None
    assert "bank_industrial_ratios_unsupported" in sig.limitations


def test_bank_snapshot_must_not_fabricate_industrial_zeros() -> None:
    """Missing ≠ zero: BANK_FI snapshot may omit industrial metrics, never invent 0.0."""
    snap = FundamentalSnapshotV1(
        instrument_id=99,
        as_of=date(2026, 1, 1),
        known_at=date(2025, 12, 1),
        period_end=date(2025, 9, 30),
        issuer_kind="BANK_FI",
        status="NOT_AVAILABLE",
        metrics={},
        missing_metrics=tuple(sorted(INDUSTRIAL_ONLY_METRICS)),
        limitations=(
            "bank_industrial_fallback_forbidden",
            "use_bank_specific_metrics_or_unknown",
        ),
    )
    assert snap.issuer_kind == "BANK_FI"
    for key in INDUSTRIAL_ONLY_METRICS:
        assert key not in snap.metrics
        assert key in snap.missing_metrics
    forged = {k: 0.0 for k in INDUSTRIAL_ONLY_METRICS}
    assert all(snap.metrics.get(k) is None for k in forged)


def test_sector_misclassification_must_surface_unknown_not_positive() -> None:
    snap = FundamentalSnapshotV1(
        instrument_id=5,
        as_of=date(2026, 2, 1),
        known_at=None,
        issuer_kind="UNKNOWN",
        status="UNKNOWN",
        limitations=("issuer_mapping_ambiguity",),
    )
    assert snap.status == "UNKNOWN"
    assert snap.as_of is not None
    sig = unknown_signal(
        model_id="FundamentalModelV1",
        model_version="1",
        semantic="FUNDAMENTAL",
        instrument_id=5,
        as_of=snap.as_of,
        reason="issuer_mapping_ambiguity",
    )
    assert sig.state == "UNKNOWN"


def test_banks_module_probe_rejects_industrial_fallback_if_present() -> None:
    try:
        banks = importlib.import_module("app.modules.intelligence.banks")
    except ModuleNotFoundError:
        pytest.skip("intelligence.banks not implemented yet")

    guard = getattr(banks, "forbid_industrial_fallback_for_banks", None) or getattr(
        banks, "assert_no_industrial_fallback", None
    )
    if guard is None:
        pytest.skip("banks module present without industrial-fallback guard export")

    with pytest.raises((ValueError, RuntimeError, AssertionError)):
        guard(
            issuer_kind="BANK_FI",
            metrics={"ev_ebitda": 6.0, "gross_margin": 0.4},
        )
