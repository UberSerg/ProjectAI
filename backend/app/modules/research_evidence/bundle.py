"""Filesystem evidence bundle writers. No new DB table. Do not commit runtime artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.modules.prediction.infrastructure.artifacts import write_json
from app.modules.research_evidence.experiment import (
    EVALUATION_WORDING,
    PRIMARY_RETURN_SEMANTIC,
    canonical_semantic_json,
)

BUNDLE_PART_NAMES: tuple[str, ...] = (
    "manifest",
    "dataset_compare",
    "model_regression",
    "model_ranker",
    "ablation",
    "stability",
    "economics",
    "prospective",
    "evidence_overview",
)

PENDING_PART: dict[str, Any] = {"status": "PENDING"}

RUNTIME_TIMESTAMP_KEYS = frozenset(
    {
        "bundled_at",
        "created_at",
        "evaluated_at",
        "finished_at",
        "generated_at",
        "started_at",
        "written_at",
    }
)

MANIFEST_TRUTH: dict[str, Any] = {
    "candidate_promoted": False,
    "evaluation_wording": EVALUATION_WORDING,
    "persist_registry": False,
    "personal_decision_mutated": False,
    "primary_return_semantic": PRIMARY_RETURN_SEMANTIC,
    "production_registry_mutated": False,
    "research_only": True,
    "shadow_mutated": False,
    "total_return": False,
}


def _strip_runtime_timestamps(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            key: _strip_runtime_timestamps(value)
            for key, value in obj.items()
            if key not in RUNTIME_TIMESTAMP_KEYS
        }
    if isinstance(obj, list):
        return [_strip_runtime_timestamps(item) for item in obj]
    return obj


def payload_file_hash(payload: Any) -> str:
    semantic = _strip_runtime_timestamps(payload)
    return hashlib.sha256(canonical_semantic_json(semantic).encode("utf-8")).hexdigest()


def _forced_manifest(user_part: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(user_part or {})
    merged.update(MANIFEST_TRUTH)
    return merged


def write_evidence_bundle(root: Path, parts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write the nine JSON artifacts. Missing parts are honest PENDING, not fake metrics."""
    supplied = parts or {}
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    file_hashes: list[str] = []
    written: dict[str, str] = {}
    for name in BUNDLE_PART_NAMES:
        if name == "manifest":
            payload = _forced_manifest(supplied.get(name) if isinstance(supplied.get(name), dict) else None)
        elif name in supplied and supplied[name] is not None:
            payload = supplied[name]
        else:
            payload = dict(PENDING_PART)
        path = root / f"{name}.json"
        write_json(path, payload)
        file_hashes.append(payload_file_hash(payload))
        written[name] = str(path)
    bundle_hash = hashlib.sha256("".join(file_hashes).encode("utf-8")).hexdigest()
    return {
        "bundle_hash": bundle_hash,
        "files": written,
        "root": str(root),
    }
