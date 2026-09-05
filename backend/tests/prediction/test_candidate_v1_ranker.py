"""Candidate V1 Ranker unit tests (no HOLDOUT selection)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.domain.ports.portfolio import PortfolioPolicyInput, PredictionSignal
from app.modules.prediction.application.relevance import (
    assert_best_gets_highest_relevance,
    cross_sectional_percentile_relevance,
    group_id_codes,
)
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG, FEATURE_NAMES
from app.modules.prediction.candidate_v1_config import CANDIDATE_V1_RANKER_CONFIG
from app.modules.simulator.application.policy import RankLongOnlyV0Policy


def test_v1_feature_contract_matches_v0() -> None:
    cfg = CANDIDATE_V1_RANKER_CONFIG
    cfg.assert_feature_contract()
    assert len(cfg.feature_names) == 90
    assert cfg.feature_names == tuple(FEATURE_NAMES)
    assert cfg.required_values_hash == CANDIDATE_V0_CONFIG.required_values_hash
    assert cfg.evaluate_final_holdout is False
    assert cfg.prediction_semantic == "RANKING_SCORE"
    assert cfg.config_hash() == cfg.config_hash()


def test_relevance_best_worst_and_ties() -> None:
    frame = pd.DataFrame(
        {
            "as_of_date": [date(2024, 1, 2)] * 4,
            "instrument_id": [1, 2, 3, 4],
            "y": [0.1, 0.05, 0.05, -0.2],
        }
    )
    out = cross_sectional_percentile_relevance(frame)
    assert_best_gets_highest_relevance(out)
    assert float(out.loc[out["instrument_id"] == 1, "relevance"].iloc[0]) == 1.0
    assert float(out.loc[out["instrument_id"] == 4, "relevance"].iloc[0]) == 0.0
    # ties average
    tied = out.loc[out["instrument_id"].isin([2, 3]), "relevance"].tolist()
    assert tied[0] == tied[1]


def test_group_ids_same_date() -> None:
    s = pd.Series([date(2024, 1, 2), date(2024, 1, 2), date(2024, 1, 3)])
    g = group_id_codes(s)
    assert g[0] == g[1]
    assert g[0] != g[2]


def test_prediction_signal_score_semantic() -> None:
    v0 = PredictionSignal(1, "A", date(2024, 1, 2), 0.05)
    assert v0.score == 0.05
    assert not v0.is_ranking_score
    v1 = PredictionSignal(
        1,
        "A",
        date(2024, 1, 2),
        0.0,
        prediction_semantic="RANKING_SCORE",
        prediction_score=1.37,
    )
    assert v1.score == 1.37
    assert v1.is_ranking_score


def test_policy_ranks_by_score_not_return_field() -> None:
    day = date(2024, 1, 2)
    signals = [
        PredictionSignal(1, "A", day, 0.0, prediction_semantic="RANKING_SCORE", prediction_score=0.1),
        PredictionSignal(2, "B", day, 0.0, prediction_semantic="RANKING_SCORE", prediction_score=0.9),
        PredictionSignal(3, "C", day, 0.0, prediction_semantic="RANKING_SCORE", prediction_score=0.5),
        PredictionSignal(4, "D", day, 0.0, prediction_semantic="RANKING_SCORE", prediction_score=0.2),
        PredictionSignal(5, "E", day, 0.0, prediction_semantic="RANKING_SCORE", prediction_score=0.3),
    ]
    out = RankLongOnlyV0Policy().decide(PortfolioPolicyInput(prediction_signals=tuple(signals)))
    assert out.decisions[0].ticker == "B"
    assert out.decisions[0].metadata["prediction_semantic"] == "RANKING_SCORE"
    assert "predicted_return_20d" not in out.decisions[0].metadata


def test_v1_config_hash_stable() -> None:
    a = CANDIDATE_V1_RANKER_CONFIG.config_hash()
    b = CANDIDATE_V1_RANKER_CONFIG.config_hash()
    assert a == b
    assert len(a) == 64


def test_lab_catalog_v1_semantics() -> None:
    from app.modules.research_lab.catalog import list_candidates

    options = list_candidates()
    by_version = {c.candidate_version: c for c in options}
    assert "v0" in by_version
    assert by_version["v0"].prediction_semantic == "EXPECTED_RETURN"
    assert by_version["v0"].output_label == "Прогноз изменения цены"
    assert "v1_ranker" in by_version
    v1 = by_version["v1_ranker"]
    assert v1.prediction_semantic == "RANKING_SCORE"
    assert v1.output_label == "Рейтинговый балл"
    payload = v1.to_dict()
    assert payload["prediction_semantic"] == "RANKING_SCORE"
    assert payload["output_label"] == "Рейтинговый балл"
