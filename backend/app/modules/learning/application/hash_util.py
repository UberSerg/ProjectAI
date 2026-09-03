"""Deterministic content hashing for dataset samples / runs."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def sha256_hex(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def sample_content_hash(
    *,
    instrument_id: int,
    as_of_date: str,
    features: dict[str, Any],
    labels: dict[str, Any],
    lineage_identity: dict[str, Any],
) -> str:
    return sha256_hex(
        {
            "instrument_id": instrument_id,
            "as_of_date": as_of_date,
            "features": features,
            "labels": labels,
            "lineage": lineage_identity,
        }
    )


def sample_values_hash(
    *,
    instrument_id: int,
    as_of_date: str,
    features: dict[str, Any],
    labels: dict[str, Any],
) -> str:
    """Hash of X+Y only. Ignores surrogate row IDs (repeat-build identity)."""
    return sha256_hex(
        {
            "instrument_id": instrument_id,
            "as_of_date": as_of_date,
            "features": features,
            "labels": labels,
        }
    )


def dataset_hash(
    *,
    dataset_spec_code: str,
    dataset_spec_version: int,
    date_from: str | None,
    date_to: str | None,
    sample_hashes: list[str],
) -> str:
    return sha256_hex(
        {
            "dataset_spec_code": dataset_spec_code,
            "dataset_spec_version": dataset_spec_version,
            "date_from": date_from,
            "date_to": date_to,
            "samples": sorted(sample_hashes),
        }
    )


def dataset_values_hash(
    *,
    dataset_spec_code: str,
    dataset_spec_version: int,
    date_from: str | None,
    date_to: str | None,
    sample_hashes: list[str],
) -> str:
    """Dataset-level hash of values only (no lineage / artifact IDs)."""
    return dataset_hash(
        dataset_spec_code=dataset_spec_code,
        dataset_spec_version=dataset_spec_version,
        date_from=date_from,
        date_to=date_to,
        sample_hashes=sample_hashes,
    )
