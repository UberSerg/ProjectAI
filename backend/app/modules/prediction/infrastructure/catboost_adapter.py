"""CatBoost infrastructure adapter (I/O allowed here, not in domain)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import numpy.typing as npt
from catboost import CatBoostRegressor

from app.modules.prediction.domain.ports import PredictionOutput


class CatBoostRegressorAdapter:
    """Fitted CatBoost model wrapper implementing PredictionModel."""

    def __init__(
        self,
        *,
        model_id: str,
        model_version: str,
        hyperparameters: dict,
        feature_names: list[str],
    ) -> None:
        self.model_id = model_id
        self.model_version = model_version
        self.feature_names = list(feature_names)
        self.hyperparameters = dict(hyperparameters)
        self._model = CatBoostRegressor(**self.hyperparameters)

    def fit(self, x: npt.NDArray[np.floating], y: npt.NDArray[np.floating]) -> CatBoostRegressorAdapter:
        self._model.fit(x, y, verbose=False)
        return self

    def predict_many(self, features: npt.NDArray[np.floating]) -> npt.NDArray[np.float64]:
        return np.asarray(self._model.predict(features), dtype=np.float64)

    def predict_one(self, features: npt.NDArray[np.floating]) -> PredictionOutput:
        vec = np.asarray(features, dtype=float).reshape(1, -1)
        pred = float(self.predict_many(vec)[0])
        return PredictionOutput(
            expected_return=pred,
            model_id=self.model_id,
            model_version=self.model_version,
        )

    def feature_importance(self) -> dict[str, float]:
        values = self._model.get_feature_importance()
        return {name: float(val) for name, val in zip(self.feature_names, values, strict=True)}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._model.save_model(str(path))

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        model_id: str,
        model_version: str,
        hyperparameters: dict,
        feature_names: list[str],
    ) -> CatBoostRegressorAdapter:
        adapter = cls(
            model_id=model_id,
            model_version=model_version,
            hyperparameters=hyperparameters,
            feature_names=feature_names,
        )
        # Fresh estimator for load_model — avoid param synonym conflicts with ctor kwargs.
        adapter._model = CatBoostRegressor()
        adapter._model.load_model(str(path))
        return adapter
