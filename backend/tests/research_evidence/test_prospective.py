"""Prospective Evidence Bridge V1 — read-only PDM + Forward, no master score."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.modules.memory.domain.decision_memory import (
    ALIGNED,
    HORIZONS,
    LINK_SOURCE_USER_CONFIRMED,
    NOT_ALIGNED,
    OUTCOME_BASELINE_UNAVAILABLE,
    OUTCOME_DATA_UNAVAILABLE,
    OUTCOME_PENDING,
    OUTCOME_READY,
    RETURN_TYPE_PRICE,
)
from app.modules.memory.infrastructure.models import (
    PersonalDecisionAction,
    PersonalDecisionOperationLink,
    PersonalDecisionOutcome,
    PersonalDecisionRecord,
)
from app.modules.prediction.infrastructure.forward_models import ForwardPrediction, ForwardPredictionBatch
from app.modules.prediction.infrastructure.forward_outcome_models import (
    ForwardBatchEvaluation,
    ForwardPredictionOutcome,
)
from app.modules.research_evidence.overview_map import map_prospective_ui
from app.modules.research_evidence.prospective import (
    LINK_NOT_CAUSALITY_NOTE,
    MIN_SAMPLE,
    STATUS_INSUFFICIENT_SAMPLE,
    build_prospective_evidence_v1,
    summarize_forward_predictions,
    summarize_personal_decision_memory,
)

PROSPECTIVE_SRC = (
    Path(__file__).resolve().parents[2] / "app" / "modules" / "research_evidence" / "prospective.py"
)


class _Scalars:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class FakeReadSession:
    """In-memory SELECT-only session. add/commit raise so write paths cannot hide."""

    def __init__(self, **tables: list[object]) -> None:
        self._tables = tables

    def add(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("session.add is forbidden on prospective evidence paths")

    def add_all(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("session.add_all is forbidden on prospective evidence paths")

    def commit(self) -> None:
        raise AssertionError("session.commit is forbidden on prospective evidence paths")

    def flush(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("session.flush is forbidden on prospective evidence paths")

    def delete(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("session.delete is forbidden on prospective evidence paths")

    def merge(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("session.merge is forbidden on prospective evidence paths")

    def scalars(self, stmt: object) -> _Scalars:
        entity = None
        descriptions = getattr(stmt, "column_descriptions", None) or []
        if descriptions:
            entity = descriptions[0].get("entity")
        table = getattr(entity, "__tablename__", None)
        return _Scalars(self._tables.get(table, []))

    def get(self, model: type, ident: object) -> object | None:
        table = getattr(model, "__tablename__", None)
        for row in self._tables.get(table, []):
            if getattr(row, "id", None) == ident:
                return row
        return None


def _record(*, rec_id: int = 1, portfolio_id: int = 7) -> SimpleNamespace:
    return SimpleNamespace(id=rec_id, portfolio_id=portfolio_id)


def _action(
    *,
    action_id: int,
    record_id: int = 1,
    action: str = "CONSIDER_INCREASE",
    instrument_id: int | None = 10,
    symbol: str | None = "SBER",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=action_id,
        decision_record_id=record_id,
        action=action,
        instrument_id=instrument_id,
        symbol=symbol,
    )


def _outcome(
    *,
    action_id: int,
    horizon: int,
    status: str = OUTCOME_READY,
    fwd: str | None = "0.01",
    alignment: str | None = ALIGNED,
) -> SimpleNamespace:
    return SimpleNamespace(
        decision_action_id=action_id,
        horizon_sessions=horizon,
        status=status,
        return_type=RETURN_TYPE_PRICE,
        forward_return=None if fwd is None else Decimal(fwd),
        directional_alignment=alignment,
    )


def _link(*, action_id: int, op_id: int = 99, portfolio_id: int = 7) -> SimpleNamespace:
    return SimpleNamespace(
        decision_action_id=action_id,
        personal_operation_id=op_id,
        portfolio_id=portfolio_id,
        link_source=LINK_SOURCE_USER_CONFIRMED,
        active=True,
    )


def _batch(
    *,
    batch_id: int,
    semantic: str,
    as_of: date = date(2026, 9, 1),
    generated_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=batch_id,
        as_of_date=as_of,
        prediction_semantic=semantic,
        candidate_name="prediction_ml_candidate",
        candidate_version="v0" if semantic == "EXPECTED_RETURN" else "v1_ranker",
        generated_at=generated_at or datetime(2026, 9, 2, tzinfo=UTC),
        completed_at=generated_at or datetime(2026, 9, 2, tzinfo=UTC),
    )


def _pred(
    *,
    pred_id: int,
    batch_id: int,
    semantic: str,
    score: float,
    status: str = "PENDING_OUTCOME",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=pred_id,
        batch_id=batch_id,
        prediction_semantic=semantic,
        predicted_return_20d=score,
        outcome_status=status,
        instrument_id=pred_id,
        ticker=f"T{pred_id}",
        as_of_date=date(2026, 9, 1),
    )


def _fwd_outcome(
    *,
    pred_id: int,
    batch_id: int,
    predicted: float,
    realized: float | None,
    status: str,
) -> SimpleNamespace:
    err = None if realized is None else realized - predicted
    return SimpleNamespace(
        id=pred_id,
        forward_prediction_id=pred_id,
        batch_id=batch_id,
        as_of_date=date(2026, 9, 1),
        instrument_id=pred_id,
        ticker=f"T{pred_id}",
        predicted_return_20d=predicted,
        realized_return_20d=realized,
        prediction_error=err,
        absolute_error=None if err is None else abs(err),
        direction_correct=None if realized is None else (predicted >= 0) == (realized >= 0),
        status=status,
    )


def _evaluation(
    *,
    batch_id: int,
    status: str,
    evaluated_count: int,
    pending_count: int,
    mae: float | None = 0.02,
    rmse: float | None = 0.03,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=batch_id,
        batch_id=batch_id,
        status=status,
        evaluated_count=evaluated_count,
        pending_count=pending_count,
        eligible_count=evaluated_count + pending_count,
        invalid_count=0,
        mean_predicted=0.1,
        mean_realized=0.05,
        mae=mae,
        rmse=rmse,
        directional_accuracy=0.5,
        spearman_rank_ic=0.2,
        top20_realized_mean=0.08,
        bottom20_realized_mean=0.01,
        top_minus_bottom_spread=0.07,
        metrics={},
        evaluated_at=datetime(2026, 9, 20, tzinfo=UTC) if evaluated_count else None,
        horizon_observations=20,
        evaluator_version="forward_outcome_v0",
    )


def test_source_is_select_only_no_memory_or_forward_writers() -> None:
    src = PROSPECTIVE_SRC.read_text(encoding="utf-8")
    forbidden = (
        "capture_decision",
        "refresh_outcomes",
        "confirm_operation_link",
        "evaluate_forward_outcomes",
        "upsert_outcome_row",
        "upsert_batch_evaluation",
        "touch_prediction_outcome_status",
        "session.add",
        ".commit(",
        ".delete(",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
    )
    for token in forbidden:
        assert token not in src, f"prospective.py must not contain write token {token!r}"
    assert "select(" in src


def test_pdm_read_only_session_never_add_or_commit() -> None:
    memory = FakeReadSession(
        personal_decision_records=[_record()],
        personal_decision_actions=[_action(action_id=1)],
        personal_decision_outcomes=[_outcome(action_id=1, horizon=5)],
        personal_decision_operation_links=[_link(action_id=1)],
    )
    payload = build_prospective_evidence_v1(memory_session=memory)
    assert payload["personal_decision_memory"]["captures_total"] == 1
    with pytest.raises(AssertionError, match="session.add"):
        memory.add(object())
    with pytest.raises(AssertionError, match="session.commit"):
        memory.commit()


def test_forward_read_only_session_never_add_or_commit() -> None:
    core = FakeReadSession(
        forward_prediction_batches=[_batch(batch_id=1, semantic="EXPECTED_RETURN")],
        forward_batch_evaluations=[],
        forward_predictions=[_pred(pred_id=1, batch_id=1, semantic="EXPECTED_RETURN", score=0.02)],
        forward_prediction_outcomes=[],
    )
    payload = build_prospective_evidence_v1(core_session=core)
    pending = payload["forward_predictions"]["expected_return"]
    assert pending is not None
    assert pending["status"] == "PENDING"
    assert pending["pending_count"] == 1
    with pytest.raises(AssertionError, match="session.add"):
        core.add(object())
    with pytest.raises(AssertionError, match="session.commit"):
        core.commit()


def test_immature_forward_stays_pending_not_fabricated() -> None:
    outcomes = [
        _fwd_outcome(pred_id=1, batch_id=3, predicted=0.04, realized=None, status="PENDING_OUTCOME"),
        _fwd_outcome(pred_id=2, batch_id=3, predicted=0.01, realized=None, status="PENDING_OUTCOME"),
    ]
    preds = [
        _pred(pred_id=1, batch_id=3, semantic="EXPECTED_RETURN", score=0.04, status="PENDING_OUTCOME"),
        _pred(pred_id=2, batch_id=3, semantic="EXPECTED_RETURN", score=0.01, status="PENDING_OUTCOME"),
    ]
    forward = summarize_forward_predictions(
        batches=[_batch(batch_id=3, semantic="EXPECTED_RETURN")],
        evaluations=[],
        predictions=preds,
        outcomes=outcomes,
    )
    section = forward["expected_return"]
    assert section["status"] == "PENDING"
    assert section["evaluated_count"] == 0
    assert section["pending_count"] == 2
    assert section["mae"] is None
    assert section["rmse"] is None
    assert section["mean_realized"] is None
    assert forward["freshness"]["pending_remains_pending"] is True
    assert forward["freshness"]["fabricated_immature_outcomes"] is False
    assert forward["latest_evaluated_batch"]["batch_id"] is None


def test_ranker_payload_excludes_rmse_and_mae() -> None:
    evaluated = [
        _fwd_outcome(pred_id=i, batch_id=8, predicted=float(i), realized=0.01 * i, status="EVALUATED")
        for i in range(1, 8)
    ]
    stored = _evaluation(batch_id=8, status="EVALUATED", evaluated_count=7, pending_count=0, mae=0.99, rmse=1.23)
    forward = summarize_forward_predictions(
        batches=[_batch(batch_id=8, semantic="RANKING_SCORE")],
        evaluations=[stored],
        predictions=[
            _pred(pred_id=i, batch_id=8, semantic="RANKING_SCORE", score=float(i), status="EVALUATED")
            for i in range(1, 8)
        ],
        outcomes=evaluated,
    )
    ranking = forward["ranking_score"]
    assert ranking is not None
    assert ranking["prediction_semantic"] == "RANKING_SCORE"
    assert "rmse" not in ranking
    assert "mae" not in ranking
    assert ranking.get("spearman_rank_ic") is not None
    blob = str(ranking)
    assert "rmse" not in blob.lower()
    assert "mae" not in blob.lower()


def test_expected_return_keeps_error_metrics_separate_from_ranker() -> None:
    evaluated = [
        _fwd_outcome(pred_id=i, batch_id=2, predicted=0.02, realized=0.01, status="EVALUATED") for i in range(1, 6)
    ]
    forward = summarize_forward_predictions(
        batches=[_batch(batch_id=2, semantic="EXPECTED_RETURN")],
        evaluations=[],
        predictions=[
            _pred(pred_id=i, batch_id=2, semantic="EXPECTED_RETURN", score=0.02, status="EVALUATED")
            for i in range(1, 6)
        ],
        outcomes=evaluated,
    )
    expected = forward["expected_return"]
    assert expected["prediction_semantic"] == "EXPECTED_RETURN"
    assert expected["rmse"] is not None
    assert expected["mae"] is not None
    assert forward["ranking_score"] is None


def test_small_sample_status_hides_unstable_alignment_rate() -> None:
    records = [_record(rec_id=1)]
    actions = [_action(action_id=i, action="CONSIDER_INCREASE") for i in range(1, 4)]
    outcomes = [_outcome(action_id=i, horizon=5, fwd="0.02", alignment=ALIGNED) for i in range(1, 4)]
    pdm = summarize_personal_decision_memory(records, actions, outcomes, [])
    h5 = next(h for h in pdm["horizons"] if h["horizon_sessions"] == 5)
    assert len(actions) < MIN_SAMPLE
    assert h5["direction_alignment"]["status"] == STATUS_INSUFFICIENT_SAMPLE
    assert h5["direction_alignment"]["alignment_rate"] is None
    assert h5["price_return"]["status"] == STATUS_INSUFFICIENT_SAMPLE
    assert h5["price_return"]["mean_price_return"] is None
    assert h5["price_return"]["median_price_return"] is None
    assert h5["matured_count"] == 3


def test_enough_samples_reports_mean_median_and_alignment() -> None:
    records = [_record()]
    actions = [_action(action_id=i, instrument_id=10 + i) for i in range(1, 7)]
    outcomes = []
    for i in range(1, 7):
        for horizon in HORIZONS:
            outcomes.append(
                _outcome(
                    action_id=i,
                    horizon=horizon,
                    fwd=str(0.01 * i),
                    alignment=ALIGNED if i % 2 else NOT_ALIGNED,
                )
            )
    pdm = summarize_personal_decision_memory(records, actions, outcomes, [])
    h20 = next(h for h in pdm["horizons"] if h["horizon_sessions"] == 20)
    assert h20["price_return"]["status"] == "OBSERVED"
    assert h20["price_return"]["mean_price_return"] is not None
    assert h20["price_return"]["median_price_return"] is not None
    assert h20["direction_alignment"]["alignment_rate"] is not None
    assert "accuracy score" in h20["direction_alignment"]["note"].lower()


def test_confirmed_link_is_metadata_not_causality() -> None:
    pdm = summarize_personal_decision_memory(
        [_record()],
        [_action(action_id=1)],
        [_outcome(action_id=1, horizon=5)],
        [_link(action_id=1, op_id=501)],
    )
    links = pdm["confirmed_operation_links"]
    assert links["count"] == 1
    assert links["role"] == "METADATA_ONLY"
    assert links["causality_claim"] is False
    assert links["linked_trade_means_recommendation_caused_trade"] is False
    assert "caused" in links["note"].lower()
    payload = build_prospective_evidence_v1()
    assert LINK_NOT_CAUSALITY_NOTE in payload["limitations"] or any(
        "CAUSED" in item or "METADATA" in item for item in payload["limitations"]
    )
    assert "CONFIRMED_OPERATION_LINK_IS_METADATA_ONLY" in payload["limitations"]
    assert "LINKED_TRADE_DOES_NOT_MEAN_RECOMMENDATION_CAUSED_TRADE" in payload["limitations"]


def _collect_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys |= _collect_keys(child)
    elif isinstance(value, list):
        for child in value:
            keys |= _collect_keys(child)
    return keys


def test_unified_payload_has_no_master_score() -> None:
    payload = build_prospective_evidence_v1()
    assert set(payload) >= {"personal_decision_memory", "forward_predictions", "limitations"}
    keys = {k.lower() for k in _collect_keys(payload)}
    for banned in ("kraken_score", "overall_accuracy", "master_score", "combined_score"):
        assert banned not in keys
    assert "NOT_KRAKEN_ACCURACY" in payload["limitations"]
    assert "NO_COMBINED_MASTER_SCORE" in payload["limitations"]


def test_unavailable_and_action_counts() -> None:
    actions = [
        _action(action_id=1, action="CONSIDER_INCREASE"),
        _action(action_id=2, action="CONSIDER_REDUCE"),
        _action(action_id=3, action="HOLD"),
    ]
    outcomes = [
        _outcome(action_id=1, horizon=5, status=OUTCOME_READY, fwd="0.02", alignment=ALIGNED),
        _outcome(action_id=2, horizon=5, status=OUTCOME_DATA_UNAVAILABLE, fwd=None, alignment=None),
        _outcome(action_id=3, horizon=5, status=OUTCOME_BASELINE_UNAVAILABLE, fwd=None, alignment=None),
        _outcome(action_id=1, horizon=20, status=OUTCOME_PENDING, fwd=None, alignment=None),
    ]
    pdm = summarize_personal_decision_memory([_record()], actions, outcomes, [])
    assert pdm["captures_total"] == 1
    assert pdm["action_counts"]["CONSIDER_INCREASE"] == 1
    assert pdm["action_counts"]["HOLD"] == 1
    h5 = next(h for h in pdm["horizons"] if h["horizon_sessions"] == 5)
    assert h5["unavailable_count"] == 2
    h20 = next(h for h in pdm["horizons"] if h["horizon_sessions"] == 20)
    assert h20["pending_count"] == 1
    hold_align = h5["direction_alignment"]
    assert hold_align["n"] == 1  # HOLD excluded; only INCREASE ready with alignment


def test_fake_session_select_roundtrip_matches_sqlalchemy_entity() -> None:
    stmt = select(PersonalDecisionRecord)
    entity = stmt.column_descriptions[0]["entity"]
    assert entity is PersonalDecisionRecord
    stmt_a = select(PersonalDecisionAction)
    assert stmt_a.column_descriptions[0]["entity"] is PersonalDecisionAction
    stmt_o = select(PersonalDecisionOutcome)
    assert stmt_o.column_descriptions[0]["entity"] is PersonalDecisionOutcome
    stmt_l = select(PersonalDecisionOperationLink)
    assert stmt_l.column_descriptions[0]["entity"] is PersonalDecisionOperationLink
    assert select(ForwardPredictionBatch).column_descriptions[0]["entity"] is ForwardPredictionBatch
    assert select(ForwardPrediction).column_descriptions[0]["entity"] is ForwardPrediction
    assert select(ForwardPredictionOutcome).column_descriptions[0]["entity"] is ForwardPredictionOutcome
    assert select(ForwardBatchEvaluation).column_descriptions[0]["entity"] is ForwardBatchEvaluation


def test_map_ui_horizons_not_by_horizon_and_forward_freshness() -> None:
    pdm = summarize_personal_decision_memory(
        [_record(rec_id=i) for i in range(1, 11)],
        [_action(action_id=i, record_id=i) for i in range(1, 11)],
        [_outcome(action_id=i, horizon=20, status=OUTCOME_PENDING, fwd=None, alignment=None) for i in range(1, 11)],
        [],
    )
    assert "by_horizon" not in pdm
    assert pdm["captures_total"] == 10
    h20 = next(h for h in pdm["horizons"] if h["horizon_sessions"] == 20)
    assert h20["matured_count"] == 0
    ui = map_prospective_ui({"personal_decision_memory": pdm, "forward_predictions": {}})
    assert ui["status"] != "OBSERVED"
    assert ui["personal_decision_memory"]["captures_total"] == 10

    three = summarize_personal_decision_memory(
        [_record()],
        [_action(action_id=i) for i in range(1, 4)],
        [_outcome(action_id=i, horizon=20, fwd="0.01") for i in range(1, 4)],
        [],
    )
    h20_small = next(h for h in three["horizons"] if h["horizon_sessions"] == 20)
    assert h20_small["matured_count"] == 3
    assert h20_small["price_return"]["status"] == STATUS_INSUFFICIENT_SAMPLE
    ui_small = map_prospective_ui({"personal_decision_memory": three, "forward_predictions": {}})
    mapped_small = next(
        h for h in ui_small["personal_decision_memory"]["horizons"] if h["horizon_sessions"] == 20
    )
    assert mapped_small["status"] == STATUS_INSUFFICIENT_SAMPLE

    six = summarize_personal_decision_memory(
        [_record()],
        [_action(action_id=i, instrument_id=10 + i) for i in range(1, 7)],
        [_outcome(action_id=i, horizon=20, fwd=str(0.01 * i)) for i in range(1, 7)],
        [],
    )
    h20_ok = next(h for h in six["horizons"] if h["horizon_sessions"] == 20)
    assert h20_ok["matured_count"] == 6
    assert h20_ok["price_return"]["status"] == "OBSERVED"
    ui_ok = map_prospective_ui({"personal_decision_memory": six, "forward_predictions": {}})
    mapped_ok = next(h for h in ui_ok["personal_decision_memory"]["horizons"] if h["horizon_sessions"] == 20)
    assert mapped_ok["status"] == "OBSERVED"

    forward = summarize_forward_predictions(
        batches=[_batch(batch_id=8, semantic="RANKING_SCORE")],
        evaluations=[_evaluation(batch_id=8, status="EVALUATED", evaluated_count=7, pending_count=0)],
        predictions=[
            _pred(pred_id=i, batch_id=8, semantic="RANKING_SCORE", score=float(i), status="EVALUATED")
            for i in range(1, 8)
        ],
        outcomes=[
            _fwd_outcome(pred_id=i, batch_id=8, predicted=float(i), realized=0.01 * i, status="EVALUATED")
            for i in range(1, 8)
        ],
    )
    assert forward["freshness"]["matured_count"] == 7
    ui_fwd = map_prospective_ui({"personal_decision_memory": {}, "forward_predictions": forward})
    assert ui_fwd["forward_predictions"]["freshness"]["matured_count"] == 7
    ranking = ui_fwd["forward_predictions"]["ranking_score"]
    assert ranking is not None
    assert "rmse" not in str(ranking).lower()
    assert "mae" not in str(ranking).lower()
