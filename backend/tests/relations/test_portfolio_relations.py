"""Unit tests for Portfolio Relations Visualization V1 aggregation."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.modules.relations.application.portfolio_relations import (
    MAX_PORTFOLIO_SYMBOLS,
    build_portfolio_relations_matrix,
)


def _input(symbol: str, *, active: bool = True):
    return SimpleNamespace(
        id=uuid4(),
        code=f"instrument:{symbol}:log_return_1d",
        is_active=active,
        display_name=f"{symbol} log_return_1d",
    )


def test_empty_symbols() -> None:
    session = MagicMock()
    out = build_portfolio_relations_matrix(session, symbols=[])
    assert out["summary"]["status"] == "NO_SYMBOLS"
    assert out["cells"] == []


def test_too_many_symbols_bounded() -> None:
    session = MagicMock()
    symbols = [f"S{i}" for i in range(MAX_PORTFOLIO_SYMBOLS + 1)]
    out = build_portfolio_relations_matrix(session, symbols=symbols)
    assert out["summary"]["status"] == "TOO_MANY_SYMBOLS"
    assert "error" in out


def test_matrix_symmetric_diagonal_and_missing(monkeypatch) -> None:
    from app.modules.relations.application import portfolio_relations as pr

    a = _input("SBER")
    b = _input("GAZP")
    # BOND1 intentionally absent from inputs_by_code

    inputs = {a.code: a, b.code: b}

    monkeypatch.setattr(pr, "load_relation_inputs_by_codes", lambda _s, _c: inputs)

    rel_set = SimpleNamespace(id=uuid4(), code="basic_relations", version=1, is_active=True)

    lo, hi = (a.id, b.id) if a.id < b.id else (b.id, a.id)
    snap = SimpleNamespace(
        input_a_id=lo,
        input_b_id=hi,
        pearson=0.82,
        spearman=0.80,
        is_valid=True,
        sample_count=58,
        coverage_ratio=0.97,
        as_of_date=date(2026, 9, 5),
        quality_flags={},
    )

    session = MagicMock()
    session.scalar.return_value = rel_set
    session.scalars.return_value = [snap]

    out = build_portfolio_relations_matrix(
        session, symbols=["SBER", "GAZP", "BOND1", "CASH"]
    )

    assert out["symbols"] == ["SBER", "GAZP", "BOND1"]
    assert out["metric"]["window_observations"] == 60
    assert out["metric"]["name"] == "pearson"

    by_pair = {(c["symbol_a"], c["symbol_b"]): c for c in out["cells"]}
    assert by_pair[("SBER", "SBER")]["pearson"] == 1.0
    assert by_pair[("SBER", "SBER")]["status"] == "DIAGONAL"

    ab = by_pair[("SBER", "GAZP")]
    assert ab["pearson"] == 0.82
    assert ab["status"] == "OK"
    assert ab["sample_count"] == 58

    # reverse order cell not duplicated as separate unordered key — only combinations
    assert ("GAZP", "SBER") not in by_pair

    unsupported = by_pair[("SBER", "BOND1")]
    assert unsupported["pearson"] is None
    assert unsupported["status"] == "UNSUPPORTED_PAIR"
    assert "N/A" not in (unsupported["reason_ru"] or "")  # reason text, UI shows N/A

    assert out["summary"]["available_pair_count"] == 1
    assert out["summary"]["unavailable_pair_count"] == 2  # SBER-BOND1, GAZP-BOND1
    assert out["summary"]["strongest_positive"]["pearson"] == 0.82
    assert out["summary"]["high_positive_pair_count"] == 1


def test_insufficient_observations_not_zero(monkeypatch) -> None:
    from app.modules.relations.application import portfolio_relations as pr

    a = _input("SBER")
    b = _input("GAZP")
    monkeypatch.setattr(
        pr, "load_relation_inputs_by_codes", lambda _s, _c: {a.code: a, b.code: b}
    )
    rel_set = SimpleNamespace(id=uuid4(), code="basic_relations", version=1, is_active=True)
    lo, hi = (a.id, b.id) if a.id < b.id else (b.id, a.id)
    snap = SimpleNamespace(
        input_a_id=lo,
        input_b_id=hi,
        pearson=None,
        spearman=None,
        is_valid=False,
        sample_count=5,
        coverage_ratio=0.2,
        as_of_date=date(2026, 9, 1),
        quality_flags={"insufficient_samples": True},
    )
    session = MagicMock()
    session.scalar.return_value = rel_set
    session.scalars.return_value = [snap]

    out = build_portfolio_relations_matrix(session, symbols=["SBER", "GAZP"])
    cell = next(c for c in out["cells"] if c["symbol_a"] != c["symbol_b"])
    assert cell["pearson"] is None
    assert cell["status"] == "INSUFFICIENT_DATA"
    assert cell["pearson"] != 0
    assert out["summary"]["available_pair_count"] == 0


def test_cash_and_duplicates_stripped(monkeypatch) -> None:
    from app.modules.relations.application import portfolio_relations as pr

    a = _input("SBER")
    monkeypatch.setattr(pr, "load_relation_inputs_by_codes", lambda _s, _c: {a.code: a})
    rel_set = SimpleNamespace(id=uuid4(), code="basic_relations", version=1, is_active=True)
    session = MagicMock()
    session.scalar.return_value = rel_set
    session.scalars.return_value = []

    out = build_portfolio_relations_matrix(
        session, symbols=["sber", "SBER", "CASH", "equity_sleeve"]
    )
    assert out["symbols"] == ["SBER"]
    assert len([c for c in out["cells"] if c["status"] == "DIAGONAL"]) == 1
