"""IntelligenceResearchExperimentV1 — research-only experiment identity.

Fingerprint excludes runtime timestamps. persist_registry must stay false.
Does not mutate V4 / Canonical Campaign contracts or production Candidate pins.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.modules.intelligence.isolation import (
    assert_production_isolation,
    production_isolation_report,
)
from app.modules.intelligence.research.constants import (
    EVALUATION_WORDING,
    EXPERIMENT_NAME,
    EXPERIMENT_VERSION,
    MODEL_SEED,
    PRIMARY_TARGET,
    TARGET_HORIZON,
)
from app.modules.intelligence.research.packs import feature_group_definitions
from app.modules.market.application.historical_universe import HISTORICAL_EQUITY_UNIVERSE_V2


def _iso_date(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def canonical_semantic_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint_identity(identity: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_semantic_json(identity).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IntelligenceResearchExperimentV1:
    """Deterministic research experiment for Intelligence Stack feature packs."""

    date_from: date | str
    date_to: date | str
    model_seed: int = MODEL_SEED
    persist_registry: bool = False
    created_at: datetime | str | None = None
    feature_group_definitions: dict[str, list[str]] = field(
        default_factory=feature_group_definitions
    )
    # Optional lineage to an existing DatasetRun used as BASE rows (implementation detail).
    base_dataset_run_id: int | None = None
    base_dataset_hash: str | None = None
    base_dataset_values_hash: str | None = None

    def __post_init__(self) -> None:
        if self.persist_registry is True:
            raise ValueError(
                "persist_registry must be false: Intelligence Research must not mutate "
                "the production candidate registry"
            )
        if self.persist_registry is not False:
            raise ValueError("persist_registry must be false")
        object.__setattr__(self, "date_from", _iso_date(self.date_from))
        object.__setattr__(self, "date_to", _iso_date(self.date_to))
        assert_production_isolation()

    def identity_payload(self) -> dict[str, Any]:
        return {
            "base_dataset_hash": self.base_dataset_hash,
            "base_dataset_run_id": self.base_dataset_run_id,
            "base_dataset_values_hash": self.base_dataset_values_hash,
            "date_from": _iso_date(self.date_from),
            "date_to": _iso_date(self.date_to),
            "experiment_name": EXPERIMENT_NAME,
            "experiment_version": EXPERIMENT_VERSION,
            "feature_group_definitions": {
                key: list(names) for key, names in self.feature_group_definitions.items()
            },
            "historical_universe_version": HISTORICAL_EQUITY_UNIVERSE_V2,
            "is_dataset_v5": False,
            "model_seed": int(self.model_seed),
            "persist_registry": False,
            "primary_target": PRIMARY_TARGET,
            "retunes_canonical_campaign": False,
            "retunes_v4": False,
            "target_horizon": TARGET_HORIZON,
        }

    @property
    def experiment_fingerprint(self) -> str:
        return fingerprint_identity(self.identity_payload())

    def to_record(self) -> dict[str, Any]:
        created = self.created_at
        if isinstance(created, datetime):
            created_meta = created.isoformat()
        else:
            created_meta = created
        return {
            "created_at": created_meta,
            "evaluation_wording": EVALUATION_WORDING,
            "experiment_fingerprint": self.experiment_fingerprint,
            "experiment_name": EXPERIMENT_NAME,
            "identity": self.identity_payload(),
            "is_dataset_v5": False,
            "marketing": EXPERIMENT_NAME,
            "production_isolation": production_isolation_report(),
            "research_only": True,
            "total_return": False,
        }
