"""Domain port: pure numerical prediction (no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True, slots=True)
class PredictionOutput:
    expected_return: float
    model_id: str
    model_version: str


class PredictionModel(Protocol):
    """Pure prediction interface — implementations must not query DB/network."""

    model_id: str
    model_version: str

    def predict_one(self, features: npt.NDArray[np.float64]) -> PredictionOutput: ...

    def predict_many(self, features: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]: ...
