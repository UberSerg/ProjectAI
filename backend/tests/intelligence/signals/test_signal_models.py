"""Focused fixture tests for independent SignalOutputV1 adapters."""

from __future__ import annotations

from datetime import date

from app.modules.intelligence.signals import (
    CrossSectionalMLModelV1,
    EventModelV1,
    FundamentalModelV1,
    IntradayStructureModelV1,
    MacroModelV1,
    TechnicalModelV1,
)


def test_technical_bullish_and_missing_unknown(
    as_of: date, bullish_technical_features: dict
) -> None:
    model = TechnicalModelV1()
    out = model.evaluate(
        instrument_id=1,
        as_of=as_of,
        features=bullish_technical_features,
    )
    assert out.model_id == "TechnicalModelV1"
    assert out.state == "POSITIVE"
    assert out.score is not None and out.score > 0
    assert "order" not in out.model_metadata
    assert out.model_metadata["candidate_promotion"] is False
    assert set(out.model_metadata["factor_contributions"]) >= {
        "trend",
        "momentum",
        "volatility",
        "drawdown",
        "volume",
    }

    missing = model.evaluate(instrument_id=1, as_of=as_of, features=None)
    assert missing.state == "UNKNOWN"
    assert missing.score is None
    assert missing.abstain_reason == "missing_technical_features"

    empty_core = model.evaluate(
        instrument_id=1,
        as_of=as_of,
        features={"atr14_pct": 0.02},  # vol only — no trend/momentum
    )
    assert empty_core.state == "UNKNOWN"
    assert empty_core.score is None


def test_technical_critical_quality_abstains(
    as_of: date, bullish_technical_features: dict
) -> None:
    out = TechnicalModelV1().evaluate(
        instrument_id=1,
        as_of=as_of,
        features=bullish_technical_features,
        quality_flags={"price_discontinuity": True},
    )
    assert out.state == "ABSTAIN"
    assert out.score is None


def test_fundamental_industrial_and_bank_abstain(
    as_of: date, industrial_fundamental_snapshot: dict
) -> None:
    model = FundamentalModelV1()
    out = model.evaluate(
        instrument_id=42,
        as_of=as_of,
        snapshot=industrial_fundamental_snapshot,
    )
    assert out.state == "POSITIVE"
    assert out.score is not None
    assert out.model_metadata["dimensions"]["profitability"] is not None

    bank = dict(industrial_fundamental_snapshot)
    bank["issuer_kind"] = "BANK_FI"
    bank_out = model.evaluate(instrument_id=42, as_of=as_of, snapshot=bank)
    assert bank_out.state == "ABSTAIN"
    assert bank_out.abstain_reason == "bank_industrial_metrics_unsupported"
    assert bank_out.score is None

    empty_metrics = dict(industrial_fundamental_snapshot)
    empty_metrics["metrics"] = {}
    unknown = model.evaluate(instrument_id=42, as_of=as_of, snapshot=empty_metrics)
    assert unknown.state == "UNKNOWN"
    assert unknown.score is None


def test_fundamental_pit_gate(as_of: date, industrial_fundamental_snapshot: dict) -> None:
    snap = dict(industrial_fundamental_snapshot)
    snap["known_at"] = "2026-10-05"
    out = FundamentalModelV1().evaluate(instrument_id=42, as_of=as_of, snapshot=snap)
    assert out.state == "ABSTAIN"
    assert out.abstain_reason == "fundamental_known_at_after_as_of"


def test_event_recency_conflict_and_empty(as_of: date, structured_events: list[dict]) -> None:
    model = EventModelV1()
    out = model.evaluate(instrument_id=3, as_of=as_of, events=structured_events)
    assert out.state in {"POSITIVE", "NEUTRAL", "NEGATIVE"}
    assert out.score is not None
    assert out.model_metadata["events_used"] == 2

    conflict = [
        {
            "event_id": "p",
            "polarity": "POSITIVE",
            "materiality": 0.9,
            "confidence": 0.9,
            "known_at": "2026-09-28",
        },
        {
            "event_id": "n",
            "polarity": "NEGATIVE",
            "materiality": 0.9,
            "confidence": 0.9,
            "known_at": "2026-09-28",
        },
    ]
    c_out = model.evaluate(instrument_id=3, as_of=as_of, events=conflict)
    assert "conflicting_events" in c_out.limitations
    assert abs(c_out.score or 0) < 0.5

    empty = model.evaluate(instrument_id=3, as_of=as_of, events=[])
    assert empty.state == "ABSTAIN"
    assert empty.abstain_reason == "no_valid_events"
    assert empty.score is None

    future_only = model.evaluate(
        instrument_id=3,
        as_of=as_of,
        events=[{"polarity": "POSITIVE", "materiality": 1.0, "confidence": 1.0, "known_at": "2026-10-10"}],
    )
    assert future_only.state == "ABSTAIN"
    assert future_only.score is None


def test_macro_regimes(as_of: date, macro_snapshot: dict) -> None:
    model = MacroModelV1()
    market = model.evaluate(instrument_id=5, as_of=as_of, snapshot=macro_snapshot)
    assert market.state == "POSITIVE"
    assert market.score == 0.45
    assert market.model_metadata["context_scope"] == "market_wide"
    assert "market_wide_context_only" in market.limitations

    sector = model.evaluate(
        instrument_id=5,
        as_of=as_of,
        snapshot=macro_snapshot,
        sector="energy",
        sector_sensitivity_known=True,
    )
    assert sector.state == "NEGATIVE"
    assert sector.model_metadata["context_scope"] == "sector"

    unknown = model.evaluate(
        instrument_id=5,
        as_of=as_of,
        snapshot={"status": "READY", "regimes": {"market": "unknown"}, "known_at": as_of.isoformat()},
    )
    assert unknown.state == "UNKNOWN"
    assert unknown.score is None


def test_cross_sectional_ml_wraps_without_promotion(
    as_of: date, ml_provenance: dict
) -> None:
    model = CrossSectionalMLModelV1()
    out = model.evaluate(instrument_id=9, as_of=as_of, provenance=ml_provenance)
    assert out.state == "POSITIVE"
    assert out.score is not None and out.score > 0
    assert out.model_metadata["persist_registry"] is False
    assert out.model_metadata["candidate_promotion"] is False
    assert "no_candidate_promotion" in out.limitations

    missing = model.evaluate(instrument_id=9, as_of=as_of, provenance=None)
    assert missing.state == "ABSTAIN"
    assert missing.abstain_reason == "research_ml_provenance_unavailable"
    assert missing.score is None

    bad = dict(ml_provenance)
    bad["persist_registry"] = True
    blocked = model.evaluate(instrument_id=9, as_of=as_of, provenance=bad)
    assert blocked.state == "ABSTAIN"
    assert blocked.abstain_reason == "persist_registry_forbidden_for_intelligence"

    incomplete = {"rank_percentile": 0.9}
    incomplete_out = model.evaluate(instrument_id=9, as_of=as_of, provenance=incomplete)
    assert incomplete_out.state == "ABSTAIN"
    assert incomplete_out.abstain_reason.startswith("incomplete_ml_provenance")


def test_intraday_coverage_gate(as_of: date, intraday_snapshot: dict) -> None:
    model = IntradayStructureModelV1()
    out = model.evaluate(instrument_id=7, as_of=as_of, snapshot=intraday_snapshot)
    assert out.state in {"POSITIVE", "NEUTRAL"}
    assert out.score is not None
    assert out.model_metadata["bars_used"] == 24

    no_cov = model.evaluate(
        instrument_id=7,
        as_of=as_of,
        snapshot={**intraday_snapshot, "coverage_status": "NOT_READY"},
    )
    assert no_cov.state == "ABSTAIN"
    assert no_cov.abstain_reason == "no_intraday_coverage"
    assert no_cov.score is None

    none_out = model.evaluate(instrument_id=7, as_of=as_of, snapshot=None)
    assert none_out.state == "ABSTAIN"
    assert none_out.score is None
