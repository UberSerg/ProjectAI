"""OOS guards: no after-result tuning, no registry persist, coverage-gated."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from app.modules.intelligence.research.constants import (
    MODE_INSUFFICIENT_HISTORY,
    MODE_PROSPECTIVE_ONLY,
)
from app.modules.intelligence.research.coverage import PackCoverageRow
from app.modules.intelligence.research.oos import (
    IntelligenceResearchOosError,
    run_pack_chronological_oos,
)
from app.modules.intelligence.research.packs import base_feature_names
from app.modules.intelligence.research.service import evaluate_intelligence_research
from app.modules.research_evidence.oos import STATUS_INSUFFICIENT


def _tiny_frame() -> pd.DataFrame:
    names = base_feature_names()
    row = {name: 0.1 for name in names}
    row["y"] = 0.01
    row["as_of_date"] = date(2024, 1, 2)
    row["instrument_id"] = 1
    return pd.DataFrame([row, {**row, "as_of_date": date(2024, 1, 3)}])


def test_oos_rejects_non_historical_pack_without_force() -> None:
    coverage = PackCoverageRow(
        pack="BASE+INTRADAY",
        evaluation_mode=MODE_INSUFFICIENT_HISTORY,
        earliest_honest_known_at=date(2026, 9, 1),
        historical_eligible=False,
        prospective_only=False,
        domains=("base", "intraday"),
        feature_count=10,
        blockers=("insufficient_history:intraday",),
    )
    out = run_pack_chronological_oos(
        _tiny_frame(),
        pack_name="BASE+INTRADAY",
        pack_coverage=coverage,
    )
    assert out["status"] == STATUS_INSUFFICIENT
    assert out["is_dataset_v5"] is False
    assert out["after_result_tuning"] is False
    assert "insufficient" in out["reason"] or "not_historical" in out["reason"]


def test_oos_rejects_persist_registry() -> None:
    with pytest.raises(Exception, match="persist|registry"):
        run_pack_chronological_oos(
            _tiny_frame(),
            pack_name="BASE",
            persist_registry=True,
        )


def test_oos_requires_base_columns() -> None:
    with pytest.raises(IntelligenceResearchOosError, match="BASE feature"):
        run_pack_chronological_oos(pd.DataFrame({"y": [1.0]}), pack_name="BASE")


def test_oos_missing_additive_returns_insufficient() -> None:
    coverage = PackCoverageRow(
        pack="BASE+MACRO",
        evaluation_mode="HISTORICAL_EVALUABLE",
        earliest_honest_known_at=date(2014, 1, 1),
        historical_eligible=True,
        prospective_only=False,
        domains=("base", "macro"),
        feature_count=10,
    )
    out = run_pack_chronological_oos(
        _tiny_frame(),
        pack_name="BASE+MACRO",
        pack_coverage=coverage,
    )
    assert out["status"] == STATUS_INSUFFICIENT
    assert out["reason"] == "additive_feature_columns_absent"


def test_evaluate_skips_oos_without_frames() -> None:
    result = evaluate_intelligence_research(
        as_of=date(2026, 10, 7),
        run_oos=True,
        frames_by_pack=None,
    )
    assert result["oos"] == {}
    assert result["is_dataset_v5"] is False
    assert "coverage_matrix" in result


def test_evaluate_calls_oos_only_for_historical_packs() -> None:
    fake_oos = {
        "status": "ok",
        "folds": [],
        "is_dataset_v5": False,
        "after_result_tuning": False,
    }
    with patch(
        "app.modules.intelligence.research.service.run_pack_chronological_oos",
        return_value=fake_oos,
    ) as mocked:
        result = evaluate_intelligence_research(
            as_of=date(2026, 10, 7),
            frames_by_pack={
                "BASE": _tiny_frame(),
                "BASE+INTRADAY": _tiny_frame(),
            },
        )
    assert "BASE" in result["oos"]
    assert result["oos_skipped"].get("BASE+INTRADAY") in {
        MODE_INSUFFICIENT_HISTORY,
        "NOT_ELIGIBLE",
        MODE_PROSPECTIVE_ONLY,
    }
    assert mocked.call_count == 1
    assert mocked.call_args.kwargs["pack_name"] == "BASE"
