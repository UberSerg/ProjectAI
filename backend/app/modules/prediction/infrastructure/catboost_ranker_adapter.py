"""CatBoostRanker infrastructure adapter."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import numpy.typing as npt
from catboost import CatBoostRanker, Pool


class CatBoostRankerAdapter:
    """Fitted CatBoost ranking model — scores are relative within a date group."""

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
        self._model = CatBoostRanker(**self.hyperparameters)

    def fit(
        self,
        x: npt.NDArray[np.floating],
        relevance: npt.NDArray[np.floating],
        group_id: npt.NDArray[np.integer],
    ) -> CatBoostRankerAdapter:
        train_pool = Pool(data=x, label=relevance, group_id=group_id, feature_names=self.feature_names)
        self._model.fit(train_pool, verbose=False)
        return self

    def predict_many(self, features: npt.NDArray[np.floating]) -> npt.NDArray[np.float64]:
        return np.asarray(self._model.predict(features), dtype=np.float64)

    def predict_one(self, features: npt.NDArray[np.floating]) -> None:
        raise NotImplementedError(
            "CatBoostRankerAdapter produces RANKING_SCORE via predict_many; "
            "do not treat scores as expected_return."
        )

    def feature_importance(self) -> dict[str, float]:
        # Ranker default LossFunctionChange needs a train Pool; PredictionValuesChange does not.
        from catboost import EFstrType

        values = self._model.get_feature_importance(type=EFstrType.PredictionValuesChange)
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
    ) -> CatBoostRankerAdapter:
        adapter = cls(
            model_id=model_id,
            model_version=model_version,
            hyperparameters=hyperparameters,
            feature_names=feature_names,
        )
        adapter._model = CatBoostRanker()
        adapter._model.load_model(str(path))
        return adapter
