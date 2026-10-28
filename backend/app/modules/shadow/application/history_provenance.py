"""Traceable history kind: Recorded LIVE vs Counterfactual Replay.

Propagates along ForwardBatch → ShadowDecision → ShadowOrder → ShadowFill → reporting.
Does not rewrite recorded LIVE timestamps or batch lineage.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.modules.prediction.infrastructure.forward_models import ForwardPredictionBatch

HISTORY_KIND_COUNTERFACTUAL = "COUNTERFACTUAL_REPLAY"
HISTORY_KIND_RECORDED_LIVE = "RECORDED_LIVE"


def batch_history_kind(batch: ForwardPredictionBatch | None) -> str:
    if batch is None:
        return HISTORY_KIND_RECORDED_LIVE
    lineage = batch.input_lineage or {}
    kind = str(lineage.get("history_kind") or "").upper()
    if kind == HISTORY_KIND_COUNTERFACTUAL or lineage.get("reconstruction") is True:
        return HISTORY_KIND_COUNTERFACTUAL
    return HISTORY_KIND_RECORDED_LIVE


def provenance_from_batch(
    batch: ForwardPredictionBatch,
    *,
    session_date: date | None = None,
    policy_name: str | None = None,
    risk_name: str | None = None,
    execution_version: str | None = None,
) -> dict[str, Any]:
    """Structured provenance for decision/order/fill metadata and NAV reporting."""
    lineage = dict(batch.input_lineage or {})
    kind = batch_history_kind(batch)
    day = session_date or batch.as_of_date
    out: dict[str, Any] = {
        "history_kind": kind,
        "forward_batch_id": int(batch.id),
        "session_date": day.isoformat() if day is not None else None,
        "pit_as_of": batch.as_of_date.isoformat() if batch.as_of_date is not None else None,
        "reconstruction": kind == HISTORY_KIND_COUNTERFACTUAL,
    }
    if kind == HISTORY_KIND_COUNTERFACTUAL:
        out["reconstructed_at"] = lineage.get("reconstructed_at")
        out["pit_visibility_clock"] = lineage.get("pit_visibility_clock")
        out["pit_input_bound"] = lineage.get("pit_visibility_clock") or (
            batch.as_of_date.isoformat() if batch.as_of_date else None
        )
    if policy_name:
        out["policy_name"] = policy_name
    if risk_name:
        out["risk_name"] = risk_name
    if execution_version:
        out["execution_version"] = execution_version
    return out


def merge_provenance(meta: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    merged = dict(meta)
    merged.update({k: v for k, v in provenance.items() if v is not None})
    return merged


__all__ = [
    "HISTORY_KIND_COUNTERFACTUAL",
    "HISTORY_KIND_RECORDED_LIVE",
    "batch_history_kind",
    "merge_provenance",
    "provenance_from_batch",
]
