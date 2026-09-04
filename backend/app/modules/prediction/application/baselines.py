"""Simple baselines for Candidate V0 (train-only statistics)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


class ZeroBaseline:
    name = "zero"

    def fit(self, x: npt.NDArray[np.floating], y: npt.NDArray[np.floating]) -> ZeroBaseline:
        return self

    def predict(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.float64]:
        return np.zeros(len(x), dtype=np.float64)


class TrainMeanBaseline:
    name = "train_mean"

    def __init__(self) -> None:
        self.mean_: float = 0.0

    def fit(self, x: npt.NDArray[np.floating], y: npt.NDArray[np.floating]) -> TrainMeanBaseline:
        self.mean_ = float(np.mean(y)) if len(y) else 0.0
        return self

    def predict(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.float64]:
        return np.full(len(x), self.mean_, dtype=np.float64)


class RidgeBaseline:
    """Train-only median imputation + standardization + Ridge."""

    name = "ridge"

    def __init__(self, *, alpha: float = 1.0, random_state: int = 42) -> None:
        self.pipeline = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("model", Ridge(alpha=alpha, random_state=random_state)),
            ]
        )

    def fit(self, x: npt.NDArray[np.floating], y: npt.NDArray[np.floating]) -> RidgeBaseline:
        self.pipeline.fit(x, y)
        return self

    def predict(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.float64]:
        return np.asarray(self.pipeline.predict(x), dtype=np.float64)
