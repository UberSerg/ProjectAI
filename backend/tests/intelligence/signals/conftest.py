"""Fixtures for independent SignalOutputV1 model adapters."""

from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture
def as_of() -> date:
    return date(2026, 10, 1)


@pytest.fixture
def bullish_technical_features() -> dict:
    return {
        "return_5d": 0.12,
        "return_20d": 0.15,
        "sma20_distance": 0.06,
        "ema20_distance": 0.05,
        "atr14_pct": 0.015,
        "volatility_20d": 0.02,
        "drawdown_20d": -0.02,
        "volume_zscore_20d": 2.5,
        "rsi14": 65.0,
    }


@pytest.fixture
def industrial_fundamental_snapshot(as_of: date) -> dict:
    return {
        "schema": "FundamentalSnapshotV1",
        "instrument_id": 42,
        "as_of": as_of.isoformat(),
        "known_at": "2026-09-15",
        "period_end": "2026-06-30",
        "issuer_kind": "INDUSTRIAL",
        "status": "READY",
        "metrics": {
            "roe": 0.18,
            "roa": 0.09,
            "debt_to_equity": 0.4,
            "revenue_yoy": 0.12,
            "NET_INCOME": 1.0e9,
            "trend": "IMPROVING",
        },
        "missing_metrics": [],
        "limitations": [],
        "provider": "fns_gir_bo",
    }


@pytest.fixture
def structured_events(as_of: date) -> list[dict]:
    return [
        {
            "event_id": "e1",
            "event_type": "earnings_beat",
            "polarity": "POSITIVE",
            "materiality": 0.8,
            "confidence": 0.9,
            "known_at": "2026-09-20",
            "provider": "news",
            "content_hash": "abc",
        },
        {
            "event_id": "e2",
            "event_type": "guidance_cut",
            "polarity": "NEGATIVE",
            "materiality": 0.3,
            "confidence": 0.6,
            "known_at": "2026-09-10",
            "provider": "news",
        },
    ]


@pytest.fixture
def macro_snapshot(as_of: date) -> dict:
    return {
        "schema": "MacroSnapshotV1",
        "as_of": as_of.isoformat(),
        "known_at": as_of.isoformat(),
        "status": "READY",
        "observations": {"key_rate": 16.0},
        "regimes": {"market": "supportive", "sector:energy": "adverse"},
        "limitations": [],
        "sources": ("cbr",),
    }


@pytest.fixture
def ml_provenance() -> dict:
    return {
        "model_id": "experimental_v3_research",
        "model_version": "v3",
        "dataset_spec_version": 3,
        "dataset_run_id": 101,
        "dataset_hash": "deadbeef",
        "experiment_label": "EXPERIMENTAL_V3_RESEARCH",
        "rank_percentile": 0.82,
        "persist_registry": False,
        "candidate_promotion": False,
        "status": "ok",
        "feature_snapshot_hash": "feat123",
        "known_at": "2026-10-01",
    }


@pytest.fixture
def intraday_snapshot(as_of: date) -> dict:
    return {
        "schema": "IntradayFeatureSnapshotV1",
        "instrument_id": 7,
        "as_of": as_of.isoformat(),
        "known_at": as_of.isoformat(),
        "interval": "60m",
        "coverage_status": "READY",
        "bars_used": 24,
        "features": {
            "volume_confirmation": 1.5,
            "close_location": 0.8,
            "gap_return": 0.005,
            "intraday_trend_quality": 0.4,
            "realized_vol_z": 0.5,
        },
        "limitations": [],
    }
