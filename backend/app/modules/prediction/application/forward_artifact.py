"""Load frozen Candidate V0 artifact for forward inference (never train)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.modules.prediction.application.forward_config import (
    EXPECTED_CANDIDATE_CONFIG_HASH,
    EXPECTED_DATASET_VALUES_HASH,
    EXPECTED_FEATURE_COUNT,
    EXPECTED_FEATURE_SCHEMA_HASH,
)
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG, CandidateV0Config
from app.modules.prediction.infrastructure.artifacts import candidate_artifact_dir
from app.modules.prediction.infrastructure.catboost_adapter import CatBoostRegressorAdapter


class ForwardArtifactError(ValueError):
    """Frozen candidate artifact cannot be used for forward inference."""


@dataclass(frozen=True, slots=True)
class LoadedForwardModel:
    adapter: CatBoostRegressorAdapter
    artifact_dir: Path
    config_hash: str
    feature_schema_hash: str
    feature_names: tuple[str, ...]
    dataset_values_hash: str | None
    metadata: dict[str, Any]


def load_frozen_candidate_v0(
    *,
    config: CandidateV0Config = CANDIDATE_V0_CONFIG,
    expected_config_hash: str = EXPECTED_CANDIDATE_CONFIG_HASH,
    root: Path | None = None,
) -> LoadedForwardModel:
    """Load exact Candidate V0 .cbm + verify feature schema. Never calls fit."""
    config.assert_feature_contract()
    actual_hash = config.config_hash()
    if actual_hash != expected_config_hash:
        raise ForwardArtifactError(
            f"config hash mismatch: code={actual_hash} expected={expected_config_hash}"
        )

    out_dir = candidate_artifact_dir(
        candidate_name=config.candidate_name,
        candidate_version=config.candidate_version,
        config_hash=actual_hash,
        root=root,
    )
    model_path = out_dir / "model.cbm"
    feature_list_path = out_dir / "feature_list.json"
    config_path = out_dir / "candidate_config.json"
    if not model_path.exists():
        raise ForwardArtifactError(f"missing model artifact: {model_path}")
    if not feature_list_path.exists():
        raise ForwardArtifactError(f"missing feature_list.json: {feature_list_path}")
    if not config_path.exists():
        raise ForwardArtifactError(f"missing candidate_config.json: {config_path}")

    feature_payload = json.loads(feature_list_path.read_text(encoding="utf-8"))
    artifact_features = [str(x) for x in feature_payload.get("features") or []]
    expected_features = list(config.feature_names)
    if len(artifact_features) != EXPECTED_FEATURE_COUNT:
        raise ForwardArtifactError(
            f"feature count mismatch: artifact={len(artifact_features)} expected={EXPECTED_FEATURE_COUNT}"
        )
    if artifact_features != expected_features:
        raise ForwardArtifactError("feature schema order/names mismatch vs Candidate V0 contract")

    schema_hash = config.feature_schema_hash()
    if schema_hash != EXPECTED_FEATURE_SCHEMA_HASH:
        raise ForwardArtifactError(
            f"feature schema hash mismatch: {schema_hash} != {EXPECTED_FEATURE_SCHEMA_HASH}"
        )

    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    file_config_hash = str(config_payload.get("config_hash") or "")
    if file_config_hash and file_config_hash != actual_hash:
        raise ForwardArtifactError(
            f"artifact config_hash drift: file={file_config_hash} code={actual_hash}"
        )
    dataset_values_hash = str(
        config_payload.get("required_values_hash") or EXPECTED_DATASET_VALUES_HASH
    )
    if dataset_values_hash != EXPECTED_DATASET_VALUES_HASH:
        raise ForwardArtifactError(
            f"dataset values_hash mismatch: {dataset_values_hash} != {EXPECTED_DATASET_VALUES_HASH}"
        )

    adapter = CatBoostRegressorAdapter.load(
        model_path,
        model_id=config.candidate_name,
        model_version=config.candidate_version,
        hyperparameters=dict(config.catboost_hyperparameters),
        feature_names=expected_features,
    )
    return LoadedForwardModel(
        adapter=adapter,
        artifact_dir=out_dir,
        config_hash=actual_hash,
        feature_schema_hash=schema_hash,
        feature_names=tuple(expected_features),
        dataset_values_hash=dataset_values_hash,
        metadata={
            "artifact_dir": str(out_dir),
            "model_path": str(model_path),
            "candidate_name": config.candidate_name,
            "candidate_version": config.candidate_version,
            "feature_count": len(expected_features),
        },
    )
