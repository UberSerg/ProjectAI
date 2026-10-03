"""Frozen research-only experiment identity for Research Evidence Engine V1.

Does not train models. ``created_at`` is metadata only and never enters the fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.modules.learning.dataset_config import (
    FEATURE_MANIFEST_V1,
    PIT_DAILY_CORE_V3,
    PIT_DAILY_CORE_V4,
    V4_EVENT_FEATURE_NAMES,
    V4_FUNDAMENTAL_FEATURE_NAMES,
    feature_names_from_manifest,
)
from app.modules.market.application.historical_universe import HISTORICAL_EQUITY_UNIVERSE_V2
from app.modules.prediction.candidate_config import RANDOM_SEED, TARGET_LABEL

EXPERIMENT_VERSION = "research_evidence_experiment_v1"
PRIMARY_TARGET = TARGET_LABEL
TARGET_HORIZON = 20
REBALANCE_HORIZON_SESSIONS = 20
TRANSACTION_COST_SCENARIOS_BPS_PER_SIDE: tuple[int, ...] = (0, 10, 30, 50)
PRIMARY_RETURN_SEMANTIC = "MECHANICAL_PRICE_RETURN"
EVALUATION_WORDING = "CHRONOLOGICAL OOS RESEARCH"


def default_feature_group_definitions() -> dict[str, list[str]]:
    """BASE / FUNDAMENTALS / EVENTS / V4_FULL from frozen dataset manifests."""
    base = feature_names_from_manifest(PIT_DAILY_CORE_V3["feature_manifest"])
    if base != feature_names_from_manifest(FEATURE_MANIFEST_V1):
        raise ValueError("V3 feature manifest drifted from FEATURE_MANIFEST_V1")
    return {
        "BASE": list(base),
        "FUNDAMENTALS": list(V4_FUNDAMENTAL_FEATURE_NAMES),
        "EVENTS": list(V4_EVENT_FEATURE_NAMES),
        "V4_FULL": feature_names_from_manifest(PIT_DAILY_CORE_V4["feature_manifest"]),
    }


def _iso_date(value: date | str) -> str:
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
class ResearchEvidenceExperimentV1:
    """Deterministic paired V3/V4 research experiment contract (identity ≠ runtime)."""

    dataset_v3_run_id: int
    dataset_v4_run_id: int
    dataset_v3_hash: str
    dataset_v4_hash: str
    date_from: date | str
    date_to: date | str
    dataset_v3_values_hash: str | None = None
    dataset_v4_values_hash: str | None = None
    model_seed: int = RANDOM_SEED
    persist_registry: bool = False
    created_at: datetime | str | None = None
    feature_group_definitions: dict[str, list[str]] = field(
        default_factory=default_feature_group_definitions
    )

    def __post_init__(self) -> None:
        if self.persist_registry is True:
            raise ValueError(
                "persist_registry must be false: research evidence must not mutate "
                "the production candidate registry"
            )
        if self.persist_registry is not False:
            raise ValueError("persist_registry must be false")
        object.__setattr__(self, "date_from", _iso_date(self.date_from))
        object.__setattr__(self, "date_to", _iso_date(self.date_to))

    def identity_payload(self) -> dict[str, Any]:
        """Canonical frozen fields. Insertion order of this dict does not affect the hash."""
        return {
            "dataset_v3_hash": self.dataset_v3_hash,
            "dataset_v3_run_id": int(self.dataset_v3_run_id),
            "dataset_v3_values_hash": self.dataset_v3_values_hash,
            "dataset_v4_hash": self.dataset_v4_hash,
            "dataset_v4_run_id": int(self.dataset_v4_run_id),
            "dataset_v4_values_hash": self.dataset_v4_values_hash,
            "date_from": _iso_date(self.date_from),
            "date_to": _iso_date(self.date_to),
            "experiment_version": EXPERIMENT_VERSION,
            "feature_group_definitions": {
                key: list(names) for key, names in self.feature_group_definitions.items()
            },
            "historical_universe_version": HISTORICAL_EQUITY_UNIVERSE_V2,
            "model_seed": int(self.model_seed),
            "persist_registry": False,
            "primary_target": PRIMARY_TARGET,
            "rebalance_horizon_sessions": REBALANCE_HORIZON_SESSIONS,
            "target_horizon": TARGET_HORIZON,
            "transaction_cost_scenarios_bps_per_side": list(
                TRANSACTION_COST_SCENARIOS_BPS_PER_SIDE
            ),
        }

    @property
    def experiment_fingerprint(self) -> str:
        return fingerprint_identity(self.identity_payload())

    def to_record(self) -> dict[str, Any]:
        """Serializable envelope: identity + fingerprint + optional runtime metadata."""
        created = self.created_at
        if isinstance(created, datetime):
            created_meta = created.isoformat()
        else:
            created_meta = created
        return {
            "created_at": created_meta,
            "evaluation_wording": EVALUATION_WORDING,
            "experiment_fingerprint": self.experiment_fingerprint,
            "identity": self.identity_payload(),
            "primary_return_semantic": PRIMARY_RETURN_SEMANTIC,
            "research_only": True,
            "total_return": False,
        }
