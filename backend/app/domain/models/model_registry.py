"""Model registry foundation (no training yet)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class ModelStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    REJECTED = "rejected"
    ARCHIVED = "archived"


@dataclass(slots=True)
class ModelRecord:
    model_name: str
    model_version: str
    created_at: datetime
    parameters: dict[str, Any] = field(default_factory=dict)
    training_dataset: str | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    status: ModelStatus = ModelStatus.CANDIDATE
