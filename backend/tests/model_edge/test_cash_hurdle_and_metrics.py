"""Unit tests for Model Edge cash hurdle and diagnostics metrics."""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.model_edge.application.cash_hurdle import (
    cash_hurdle_growth_factor,
    compute_cash_hurdle,
    hurdle_nav,
)
from app.modules.model_edge.application.diagnostics import (
    diagnostics_input_hash,
    enrich_report,
)
from app.modules.model_edge.application.diagnostics_metrics import (
    bottom_contamination,
    entry_exit_churn,
    sample_maturity_label,
    spearman_ic,
    top_bottom_spread,
    top_k_mean_realized,
    top_k_precision_recall,
)
from app.modules.model_edge.domain.types import ActivationWatermark
from datetime import UTC, datetime


def test_cash_hurdle_10pct_one_year() -> None:
    h = compute_cash_hurdle(date(2020, 1, 1), date(2021, 1, 1), annual_rate=0.10)
    assert h.calendar_days == 366  # leap
    assert abs(h.hurdle_return - ((1.1) ** (366 / 365.25) - 1)) < 1e-12


def test_cash_hurdle_zero_rate() -> None:
    h = compute_cash_hurdle(date(2020, 1, 1), date(2025, 1, 1), annual_rate=0.0)
    assert h.hurdle_return == 0.0
    assert h.growth_factor == 1.0


def test_cash_hurdle_partial_year() -> None:
    factor = cash_hurdle_growth_factor(calendar_days=73, annual_rate=0.10)
    assert abs(factor - (1.1 ** (73 / 365.25))) < 1e-12


def test_cash_hurdle_does_not_claim_portfolio_mutation() -> None:
    h = compute_cash_hurdle(date(2017, 2, 1), date(2025, 12, 30))
    assert h.to_dict()["mutates_portfolio_cash"] is False
    assert hurdle_nav(1_000_000, date(2017, 2, 1), date(2025, 12, 30)) > 1_000_000


def test_top_k_precision_deterministic() -> None:
    scores = [0.9, 0.8, 0.7, 0.1, 0.0]
    realized = [0.05, 0.04, 0.01, 0.20, 0.30]  # last two are true winners
    metrics = top_k_precision_recall(scores, realized, share=0.40)
    assert metrics["k"] == 2
    assert metrics["precision"] == 0.0  # pred top2 = idx 0,1; real top2 = 4,3


def test_top_k_recall_and_contamination() -> None:
    scores = [5.0, 4.0, 3.0, 2.0, 1.0]
    realized = [0.10, -0.20, 0.05, 0.01, -0.30]
    assert top_k_mean_realized(scores, realized, share=0.40) is not None
    cont = bottom_contamination(scores, realized, top_share=0.40, bottom_share=0.40)
    assert cont is not None
    assert 0.0 <= cont <= 1.0
    spread = top_bottom_spread(scores, realized, share=0.40)
    assert spread is not None


def test_spearman_perfect() -> None:
    assert spearman_ic([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_rank_churn_and_persistence() -> None:
    prev = {1, 2, 3}
    curr = {2, 3, 4}
    churn = entry_exit_churn(prev, curr)
    assert churn["entered"] == 1
    assert churn["exited"] == 1


def test_activation_watermark_forbids_backfill() -> None:
    wm = ActivationWatermark(
        activated_at=datetime(2026, 9, 5, tzinfo=UTC),
        market_watermark=date(2026, 9, 3),
    )
    assert wm.allows(date(2026, 9, 2)) is False
    assert wm.allows(date(2026, 9, 3)) is False
    assert wm.allows(date(2026, 9, 4)) is True


def test_diagnostics_hash_reproducible() -> None:
    a = diagnostics_input_hash(
        candidate_a_hash="aaa",
        candidate_b_hash="bbb",
        period_from=date(2017, 2, 1),
        period_to=date(2025, 12, 30),
    )
    b = diagnostics_input_hash(
        candidate_a_hash="aaa",
        candidate_b_hash="bbb",
        period_from=date(2017, 2, 1),
        period_to=date(2025, 12, 30),
    )
    assert a == b
    assert len(a) == 64


def test_sample_maturity_labels() -> None:
    assert sample_maturity_label(0) == "TOO_EARLY"
    assert sample_maturity_label(3) == "VERY_FEW"
    assert sample_maturity_label(10) == "PRELIMINARY"
    assert sample_maturity_label(30) == "ACCUMULATING"
    assert sample_maturity_label(50) == "SUBSTANTIAL"


def test_human_conclusion_from_report() -> None:
    report = enrich_report(
        {
            "v0": {"mean_rank_ic": -0.013, "top20": 0.0047},
            "v1": {"mean_rank_ic": -0.0017, "top20": 0.0033},
            "stability": {
                "v0": {"week_to_week_rank_corr": 0.90},
                "v1": {"week_to_week_rank_corr": 0.92},
            },
            "economic_matrix": [
                {"model": "V0", "bps": 0, "beats_hurdle": False},
                {"model": "V1", "bps": 0, "beats_hurdle": False},
            ],
        }
    )
    assert "Rank IC" in report["human_summary"]
    assert "денежной альтернативе" in report["human_summary"]
