"""Unit tests for External Deep History V0 parser / identity / semantics."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.modules.market_history.application.audit import audit_file, classify_split_like
from app.modules.market_history.application.ca_probes import classify_probe
from app.modules.market_history.application.identity import classify_symbol, classify_symbols
from app.modules.market_history.application.reconcile import (
    classify_price_semantic,
    classify_reconciliation,
)
from app.modules.market_history.domain.types import (
    CaProbeVerdict,
    MatchStatus,
    PriceSemantic,
    ReconciliationStatus,
)
from app.modules.market_history.infrastructure.parser import (
    file_fingerprint,
    iter_rows,
    parse_record,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "external_deep_history"
SAMPLE = FIXTURES / "sample_daily.csv"


def test_parser_projects_ohlcv_and_rejects_invalid() -> None:
    rows = list(iter_rows(SAMPLE))
    assert len(rows) >= 10
    valid = [r for r, _ in rows if hasattr(r, "is_valid") and r.is_valid]
    rejected = [r for r, _ in rows if hasattr(r, "is_valid") and not r.is_valid]
    assert any(r.source_symbol == "SBER" for r in valid)
    assert any(r.reject_reason for r in rejected)


def test_parser_invalid_ohlc_and_negative_volume() -> None:
    bad_ohlc = parse_record(
        {
            "ticker": "X",
            "begin": "2015-01-01",
            "open": "10",
            "high": "9",
            "low": "8",
            "close": "9",
            "volume": "1",
            "value": "1",
        }
    )
    assert not bad_ohlc.is_valid  # type: ignore[union-attr]
    assert bad_ohlc.reject_reason == "OHLC_INCONSISTENT"  # type: ignore[union-attr]

    neg = parse_record(
        {
            "ticker": "X",
            "begin": "2015-01-01",
            "open": "10",
            "high": "11",
            "low": "9",
            "close": "10",
            "volume": "-1",
            "value": "1",
        }
    )
    assert neg.reject_reason == "NEGATIVE_VOLUME"  # type: ignore[union-attr]


def test_file_hash_deterministic() -> None:
    a = file_fingerprint(SAMPLE)
    b = file_fingerprint(SAMPLE)
    assert a.sha256 == b.sha256
    assert a.file_name == "sample_daily.csv"


def test_audit_balances_and_flags_jumps_without_invalidating() -> None:
    result = audit_file(SAMPLE)
    assert result.balances()
    assert result.total_rows == result.valid_rows + result.rejected_rows + result.malformed_rows
    # jumps are diagnostic only — they do not auto-reject
    assert "JUMP" not in result.reject_counts


def test_identity_exact_match_no_alias_guessing() -> None:
    cohort = {"SBER": "equity", "YDEX": "equity", "T": "equity", "IMOEX": "index"}
    assert classify_symbol("SBER", cohort).match_status is MatchStatus.EXACT_CURRENT_MATCH
    yndx = classify_symbol("YNDX", cohort)
    assert yndx.match_status is MatchStatus.UNKNOWN_HISTORICAL_SYMBOL
    assert yndx.project_symbol is None
    tcsg = classify_symbol("TCSG", cohort)
    assert tcsg.match_status is MatchStatus.UNKNOWN_HISTORICAL_SYMBOL
    t = classify_symbol("T", cohort)
    assert t.match_status is MatchStatus.EXACT_CURRENT_MATCH
    assert t.project_symbol == "T"
    assert classify_symbol("IMOEX", cohort).match_status is MatchStatus.INDEX_OR_NON_EQUITY

    classified = classify_symbols(["YNDX", "YDEX", "TCSG", "T"], cohort)
    assert classified["YNDX"].project_symbol is None
    assert classified["YDEX"].project_symbol == "YDEX"
    assert classified["TCSG"].project_symbol is None
    assert classified["T"].project_symbol == "T"


def test_classify_reconciliation_and_mixed_semantic() -> None:
    from app.modules.market_history.application.ca_probes import CaProbeOutcome
    from app.modules.market_history.application.reconcile import SymbolReconciliation

    assert (
        classify_reconciliation(overlap_rows=100, close_rel_med=0.0, close_rel_p95=0.0)
        is ReconciliationStatus.MATCH
    )
    assert (
        classify_reconciliation(overlap_rows=100, close_rel_med=0.99, close_rel_p95=0.99)
        is ReconciliationStatus.LIKELY_ADJUSTED
    )

    symbols = [
        SymbolReconciliation("SBER", "SBER", 100, 90, 0.0, 0.001, 0.002, 0.0, ReconciliationStatus.MATCH),
        SymbolReconciliation(
            "GMKN", "GMKN", 100, 1, 0.99, 0.99, 0.99, 0.0, ReconciliationStatus.LIKELY_ADJUSTED
        ),
    ]
    probes = [
        CaProbeOutcome(
            "GMKN",
            date(2024, 4, 8),
            "split",
            100.0,
            1.0,
            CaProbeVerdict.POST_ADJUSTED,
            "high",
            {},
        )
    ]
    semantic, evidence = classify_price_semantic(symbols, probes)
    assert semantic is PriceSemantic.MIXED
    assert evidence["symbols_matching"] == 1
    assert evidence["symbols_likely_adjusted"] == 1


def test_ca_probe_raw_vs_adjusted() -> None:
    # RAW: before/after ratio ≈ divisor (price drops by factor)
    verdict, _, _ = classify_probe(observed_ratio=100.0, price_divisor=100.0)
    assert verdict is CaProbeVerdict.RAW
    # continuous series → adjusted
    verdict2, _, _ = classify_probe(observed_ratio=1.01, price_divisor=100.0)
    assert verdict2 in {CaProbeVerdict.PRE_ADJUSTED, CaProbeVerdict.POST_ADJUSTED, CaProbeVerdict.UNKNOWN}


def test_split_like_jump_classifier() -> None:
    assert classify_split_like(0.1) == 10.0
    assert classify_split_like(100.0) == pytest.approx(0.01)
