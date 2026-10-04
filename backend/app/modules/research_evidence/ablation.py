"""V4 feature-pack ablation on identical rows / y / folds / hypers / seed.

Masked columns become NaN (NATIVE_NAN), never 0, and samples are never dropped.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.modules.learning.dataset_config import (
    V4_EVENT_FEATURE_NAMES,
    V4_FUNDAMENTAL_FEATURE_NAMES,
    feature_names_for_spec_version,
)
from app.modules.prediction.application.splits import WalkForwardFold
from app.modules.prediction.candidate_config import (
    CANDIDATE_V0_CONFIG,
    RANDOM_SEED,
    CandidateV0Config,
)
from app.modules.research_evidence.oos import (
    EVALUATION_KIND,
    MISSING_FEATURE_POLICY,
    STATUS_INSUFFICIENT,
    SemanticName,
    assert_no_registry_persist,
    run_chronological_oos,
)

VARIANT_BASE = "BASE"
VARIANT_BASE_FUNDAMENTALS = "BASE+FUNDAMENTALS"
VARIANT_BASE_EVENTS = "BASE+EVENTS"
VARIANT_V4_FULL = "V4_FULL"
ABLATION_VARIANTS: tuple[str, ...] = (
    VARIANT_BASE,
    VARIANT_BASE_FUNDAMENTALS,
    VARIANT_BASE_EVENTS,
    VARIANT_V4_FULL,
)


def v3_base_feature_names() -> list[str]:
    return feature_names_for_spec_version(3)


def columns_to_mask(variant: str) -> tuple[str, ...]:
    if variant == VARIANT_BASE:
        return tuple(V4_FUNDAMENTAL_FEATURE_NAMES) + tuple(V4_EVENT_FEATURE_NAMES)
    if variant == VARIANT_BASE_FUNDAMENTALS:
        return tuple(V4_EVENT_FEATURE_NAMES)
    if variant == VARIANT_BASE_EVENTS:
        return tuple(V4_FUNDAMENTAL_FEATURE_NAMES)
    if variant == VARIANT_V4_FULL:
        return ()
    raise ValueError(f"unknown ablation variant: {variant}")


def apply_ablation_mask(frame: pd.DataFrame, variant: str) -> pd.DataFrame:
    """Keep every sample; set masked V4 columns to NaN (not 0)."""
    out = frame.copy()
    for col in columns_to_mask(variant):
        if col in out.columns:
            out[col] = np.nan
    return out


def assert_identical_ablation_rows(original: pd.DataFrame, masked: pd.DataFrame) -> None:
    if len(original) != len(masked):
        raise ValueError("ablation must not drop samples")
    if list(original.index) != list(masked.index):
        raise ValueError("ablation must preserve row identity")
    if not original["y"].equals(masked["y"]):
        raise ValueError("ablation must keep the same y")
    if "sample_id" in original.columns and not original["sample_id"].equals(masked["sample_id"]):
        raise ValueError("ablation must keep the same sample_id")


def run_v4_ablation(
    frame: pd.DataFrame,
    *,
    semantic: SemanticName = "regression",
    feature_names: list[str] | None = None,
    persist_registry: bool = False,
    model_factory: Callable[[list[str]], Any] | None = None,
    folds: list[WalkForwardFold] | list[dict[str, Any]] | None = None,
    development_end_exclusive: date | None = None,
    min_train_n: int = 100,
    min_val_n: int = 20,
    random_seed: int = RANDOM_SEED,
    config: CandidateV0Config = CANDIDATE_V0_CONFIG,
    variants: tuple[str, ...] = ABLATION_VARIANTS,
    fold_progress: Callable[[dict[str, Any]], None] | None = None,
    variant_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Same V4 rows, same y, same folds, same hypers, same seed; only the NaN mask differs."""
    assert_no_registry_persist(persist_registry)
    names = list(feature_names or feature_names_for_spec_version(4))
    out: dict[str, Any] = {
        "evaluation_kind": EVALUATION_KIND,
        "artifact_kind": "v4_feature_ablation",
        "missing_feature_policy": MISSING_FEATURE_POLICY,
        "persist_registry": False,
        "random_seed": random_seed,
        "same_rows": True,
        "same_y": True,
        "same_folds": True,
        "same_hyperparameters": True,
        "same_seed": True,
        "note": (
            "CHRONOLOGICAL OOS RESEARCH ablation. Mask extra V4 columns to NaN; "
            "do not drop samples; Missing ≠ zero. Not a production Candidate."
        ),
        "variants": {},
    }
    n_rows = int(len(frame))
    y_checksum = float(pd.to_numeric(frame["y"], errors="coerce").sum(min_count=1) or 0.0)
    for variant in variants:
        masked = apply_ablation_mask(frame, variant)
        assert_identical_ablation_rows(frame, masked)
        result = run_chronological_oos(
            masked,
            semantic=semantic,
            feature_names=names,
            persist_registry=False,
            model_factory=model_factory,
            folds=folds,
            development_end_exclusive=development_end_exclusive,
            min_train_n=min_train_n,
            min_val_n=min_val_n,
            random_seed=random_seed,
            config=config,
            fold_progress=fold_progress,
        )
        result["ablation_variant"] = variant
        result["masked_columns"] = list(columns_to_mask(variant))
        result["n_rows"] = int(len(masked))
        out["variants"][variant] = result
        if variant_progress is not None:
            variant_progress(
                {
                    "variant": variant,
                    "semantic": semantic,
                    "index": len(out["variants"]),
                    "total": len(variants),
                    "folds_done": len(result.get("folds") or []),
                }
            )
    row_counts = {name: payload.get("n_rows") for name, payload in out["variants"].items()}
    if any(n != n_rows for n in row_counts.values()):
        out["same_rows"] = False
        out["status"] = STATUS_INSUFFICIENT
        out["reason"] = "ablation_row_count_mismatch"
        return out
    out["n_rows"] = n_rows
    out["y_sum"] = y_checksum
    out["status"] = "ok"
    return out
