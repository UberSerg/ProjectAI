"""CrossSectionalMLModelV1 — research ML provenance wrapper → SignalOutputV1.

Does NOT promote Candidate. Missing provenance => ABSTAIN with clear reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from app.modules.intelligence.contracts.provenance import EvidenceRef
from app.modules.intelligence.contracts.signal import SignalOutputV1, abstain_signal, unknown_signal
from app.modules.intelligence.signals.base import (
    clip,
    optional_float,
    parse_as_of,
    parse_known_at,
    score_to_state,
)

MODEL_ID = "CrossSectionalMLModelV1"
MODEL_VERSION = "1"
SEMANTIC = "CROSS_SECTIONAL_ML"
HORIZON = "20d"


def _resolve_score(provenance: Mapping[str, Any]) -> tuple[float | None, str | None]:
    """Prefer explicit score in [-1,1]; else map cross-sectional rank percentile."""
    for key in ("score", "signal_score", "normalized_score"):
        val = optional_float(provenance.get(key))
        if val is not None:
            return clip(val), key

    for key in ("rank_percentile", "cross_sectional_percentile", "percentile_rank"):
        pct = optional_float(provenance.get(key))
        if pct is not None:
            # 0..1 → -1..1 around median.
            return clip(2.0 * pct - 1.0), key

    y_pred = optional_float(provenance.get("y_pred") or provenance.get("expected_return"))
    if y_pred is not None:
        # Soft scale for forward-return-like units (~10% move ≈ |1|).
        return clip(y_pred / 0.10), "y_pred"

    return None, None


class CrossSectionalMLModelV1:
    model_id = MODEL_ID
    model_version = MODEL_VERSION
    semantic = SEMANTIC

    def evaluate(
        self,
        *,
        instrument_id: int,
        as_of: date | datetime | str,
        provenance: Mapping[str, Any] | None,
    ) -> SignalOutputV1:
        as_of_d = parse_as_of(as_of)
        if as_of_d is None:
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=date.today(),
                reason="missing_as_of",
                horizon=HORIZON,
            )

        if provenance is None:
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="research_ml_provenance_unavailable",
                horizon=HORIZON,
                limitations=("no_candidate_promotion",),
            )

        if provenance.get("persist_registry") is True:
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="persist_registry_forbidden_for_intelligence",
                horizon=HORIZON,
                limitations=("production_isolation",),
            )

        if provenance.get("candidate_promotion") is True:
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="candidate_promotion_forbidden",
                horizon=HORIZON,
                limitations=("production_isolation",),
            )

        required = ("model_id", "model_version", "dataset_spec_version")
        missing = [k for k in required if provenance.get(k) in (None, "")]
        if missing:
            return abstain_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason=f"incomplete_ml_provenance:{','.join(missing)}",
                horizon=HORIZON,
                limitations=("research_provenance_required",),
            )

        score, score_source = _resolve_score(provenance)
        if score is None:
            status = str(provenance.get("status") or "").lower()
            if status in {"insufficient_samples", "not_ready", "unavailable"}:
                return abstain_signal(
                    model_id=MODEL_ID,
                    model_version=MODEL_VERSION,
                    semantic=SEMANTIC,
                    instrument_id=instrument_id,
                    as_of=as_of_d,
                    reason=f"research_ml_status_{status}",
                    horizon=HORIZON,
                )
            return unknown_signal(
                model_id=MODEL_ID,
                model_version=MODEL_VERSION,
                semantic=SEMANTIC,
                instrument_id=instrument_id,
                as_of=as_of_d,
                reason="research_ml_score_unavailable",
                horizon=HORIZON,
            )

        confidence = optional_float(provenance.get("confidence"))
        if confidence is None:
            # Evidence completeness proxy from provenance richness.
            keys = (
                "dataset_run_id",
                "dataset_hash",
                "experiment_label",
                "feature_snapshot_hash",
                "config_hash",
            )
            present = sum(1 for k in keys if provenance.get(k) not in (None, ""))
            confidence = clip(0.35 + 0.1 * present, 0.0, 0.85)
        else:
            confidence = clip(confidence, 0.0, 1.0)

        known_at = parse_known_at(provenance.get("known_at"))
        experiment = provenance.get("experiment_label") or provenance.get("label")
        src_model = str(provenance.get("model_id"))
        src_version = str(provenance.get("model_version"))

        return SignalOutputV1(
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            semantic=SEMANTIC,
            instrument_id=instrument_id,
            as_of=as_of_d,
            known_at=known_at,
            horizon=HORIZON,
            state=score_to_state(score),
            score=score,
            confidence=confidence,
            confidence_semantic="MODEL_DEFINED",
            evidence_refs=(
                EvidenceRef(
                    source_type="research_ml_provenance",
                    provider=src_model,
                    known_at=known_at,
                    note=str(experiment) if experiment else "research_only",
                    extra={
                        "wrapped_model_id": src_model,
                        "wrapped_model_version": src_version,
                        "dataset_spec_version": provenance.get("dataset_spec_version"),
                    },
                ),
            ),
            feature_snapshot_hash=(
                str(provenance["feature_snapshot_hash"])
                if provenance.get("feature_snapshot_hash")
                else None
            ),
            data_freshness=str(provenance.get("status") or "research"),
            limitations=(
                "research_intelligence_only",
                "no_candidate_promotion",
                "persist_registry_false",
            ),
            model_metadata={
                "wrapped_model_id": src_model,
                "wrapped_model_version": src_version,
                "dataset_spec_version": provenance.get("dataset_spec_version"),
                "dataset_run_id": provenance.get("dataset_run_id"),
                "dataset_hash": provenance.get("dataset_hash"),
                "experiment_label": experiment,
                "score_source": score_source,
                "persist_registry": False,
                "candidate_promotion": False,
            },
        )
