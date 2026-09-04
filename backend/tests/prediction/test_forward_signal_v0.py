"""Forward Signal V0 unit tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.modules.prediction.application.forward_artifact import (
    ForwardArtifactError,
    load_frozen_candidate_v0,
)
from app.modules.prediction.application.forward_assembler import (
    AssembledRow,
    assert_no_labels_in_features,
    rows_to_matrix,
)
from app.modules.prediction.application.forward_config import (
    EXPECTED_CANDIDATE_CONFIG_HASH,
    EXPECTED_FEATURE_COUNT,
    EXPECTED_FEATURE_SCHEMA_HASH,
    FORWARD_BASIC_FS_VERSION,
    FORWARD_RELATION_SET_VERSION,
    FORWARD_SEGMENT,
    FORWARD_TECH_FS_VERSION,
    FORWARD_TECH_MODEL_VERSION,
)
from app.modules.prediction.application.forward_runner import _distribution, _rank_predictions
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
from app.modules.prediction.infrastructure.forward_repository import (
    batch_prediction_hash,
    insert_predictions_immutable,
)


def test_exact_candidate_config_hash() -> None:
    """A+B: frozen Candidate V0 identity."""
    assert CANDIDATE_V0_CONFIG.config_hash() == EXPECTED_CANDIDATE_CONFIG_HASH
    assert CANDIDATE_V0_CONFIG.config_hash().startswith("4828047608080c1a")


def test_exact_90_feature_schema_order() -> None:
    """C: exact 90-feature schema/order."""
    names = list(CANDIDATE_V0_CONFIG.feature_names)
    assert len(names) == EXPECTED_FEATURE_COUNT == 90
    assert names[0] == "return_1d"
    assert names[7] == "volume_zscore_20d"
    assert "forward_return_20d" not in names
    assert "target_date_20d" not in names
    assert CANDIDATE_V0_CONFIG.feature_schema_hash() == EXPECTED_FEATURE_SCHEMA_HASH


def test_exact_version_pins_not_active_latest() -> None:
    """D–H: V2 pins; no active/latest resolution in forward config."""
    assert FORWARD_BASIC_FS_VERSION == 2
    assert FORWARD_TECH_FS_VERSION == 2
    assert FORWARD_TECH_MODEL_VERSION == 2
    assert FORWARD_RELATION_SET_VERSION == 2
    import app.modules.prediction.application.forward_config as fc

    src = Path(fc.__file__).read_text(encoding="utf-8")
    assert "never resolve active/latest" in src.lower() or (
        "Never resolve" in Path(fc.__file__).read_text(encoding="utf-8")
    )


def test_config_hash_mismatch_fails(tmp_path: Path) -> None:
    """B: config hash mismatch fails."""
    with pytest.raises(ForwardArtifactError, match="config hash mismatch"):
        load_frozen_candidate_v0(expected_config_hash="deadbeef" * 8, root=tmp_path)


def test_missing_artifact_fails(tmp_path: Path) -> None:
    """A: missing artifact fails (no train)."""
    with pytest.raises(ForwardArtifactError, match="missing model"):
        load_frozen_candidate_v0(root=tmp_path)


def test_no_labels_in_x() -> None:
    """R: no labels/target dates in X."""
    assert_no_labels_in_features({"return_1d": 0.1})
    with pytest.raises(ValueError, match="label leaked"):
        assert_no_labels_in_features({"forward_return_20d": 0.1})


def test_rank_descending_and_tiebreak() -> None:
    """L+M: rank descending; tie-break instrument_id ascending."""
    rows = [
        {"instrument_id": 3, "predicted_return_20d": 0.2, "ticker": "C"},
        {"instrument_id": 1, "predicted_return_20d": 0.2, "ticker": "A"},
        {"instrument_id": 2, "predicted_return_20d": 0.1, "ticker": "B"},
    ]
    ranked = _rank_predictions(rows)
    assert [r["instrument_id"] for r in ranked] == [1, 3, 2]
    assert [r["rank"] for r in ranked] == [1, 2, 3]
    assert ranked[0]["eligible_count"] == 3


def test_batch_prediction_hash_stable() -> None:
    """T: batch prediction hash stable."""
    rows = [
        {
            "as_of_date": "2026-09-01",
            "instrument_id": 2,
            "predicted_return_20d": 0.01,
            "rank": 2,
        },
        {
            "as_of_date": "2026-09-01",
            "instrument_id": 1,
            "predicted_return_20d": 0.02,
            "rank": 1,
        },
    ]
    h1 = batch_prediction_hash(rows, config_hash="abc")
    h2 = batch_prediction_hash(list(reversed(rows)), config_hash="abc")
    assert h1 == h2
    assert h1 != batch_prediction_hash(rows, config_hash="abd")


def test_forward_segment_distinct() -> None:
    """U: FORWARD segment distinct from DEV/HOLDOUT."""
    assert FORWARD_SEGMENT == "FORWARD_LIVE"
    assert FORWARD_SEGMENT not in {"DEVELOPMENT_OOS", "FINAL_HOLDOUT", "TRAIN"}


def test_distribution_helpers() -> None:
    d = _distribution([0.1, 0.2, 0.3])
    assert d["mean"] == pytest.approx(0.2)
    assert d["min"] == pytest.approx(0.1)
    assert d["max"] == pytest.approx(0.3)
    assert _distribution([])["mean"] is None


def test_no_model_fit_called_on_load(tmp_path: Path) -> None:
    """V: load path must not call fit — missing artifact fails before fit."""
    with patch(
        "app.modules.prediction.application.forward_artifact.CatBoostRegressorAdapter"
    ) as adapter_cls:
        adapter_cls.fit = MagicMock()
        with pytest.raises(ForwardArtifactError):
            load_frozen_candidate_v0(root=tmp_path)
        adapter_cls.fit.assert_not_called()


def test_insert_predictions_does_not_overwrite() -> None:
    """N+O: uniqueness / no overwrite semantics in repository helper."""
    session = MagicMock()
    existing = MagicMock()
    existing.predicted_return_20d = 0.05
    session.scalar.return_value = existing
    batch = MagicMock()
    batch.id = 1
    batch.segment = FORWARD_SEGMENT
    inserted, notes = insert_predictions_immutable(
        session,
        batch=batch,
        rows=[
            {
                "as_of_date": date(2026, 9, 1),
                "instrument_id": 1,
                "ticker": "SBER",
                "predicted_return_20d": 0.05,
                "rank": 1,
                "eligible_count": 1,
                "percentile": 1.0,
                "candidate_config_hash": "cfg",
                "feature_schema_hash": "fs",
                "input_lineage": {},
                "generated_at": datetime.now(UTC),
            }
        ],
    )
    assert inserted == 0
    assert any("EXISTING" in n for n in notes)
    session.add.assert_not_called()

    existing.predicted_return_20d = 0.99
    inserted2, notes2 = insert_predictions_immutable(
        session,
        batch=batch,
        rows=[
            {
                "as_of_date": date(2026, 9, 1),
                "instrument_id": 1,
                "ticker": "SBER",
                "predicted_return_20d": 0.05,
                "rank": 1,
                "eligible_count": 1,
                "percentile": 1.0,
                "candidate_config_hash": "cfg",
                "feature_schema_hash": "fs",
                "input_lineage": {},
                "generated_at": datetime.now(UTC),
            }
        ],
    )
    assert inserted2 == 0
    assert any("FROZEN" in n for n in notes2)


def test_matrix_order_matches_feature_names() -> None:
    """S: ordered vector respects feature_names."""
    names = list(CANDIDATE_V0_CONFIG.feature_names)
    features = {n: float(i) for i, n in enumerate(names)}
    row = AssembledRow(
        instrument_id=1,
        ticker="X",
        as_of_date=date(2026, 1, 2),
        features=features,
        eligible=True,
    )
    mat = rows_to_matrix([row])
    assert mat.shape == (1, 90)
    assert mat[0, 0] == pytest.approx(0.0)
    assert mat[0, 1] == pytest.approx(1.0)


def test_portfolio_policy_not_imported_by_forward_runner() -> None:
    """W: Forward runner must not call PortfolioPolicy / fit."""
    root = Path(__file__).resolve().parents[2]
    text = (root / "app/modules/prediction/application/forward_runner.py").read_text(
        encoding="utf-8"
    )
    assert "PortfolioPolicy" not in text
    assert "RankHysteresis" not in text
    assert ".fit(" not in text
