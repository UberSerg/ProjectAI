"""Persist Candidate V0 provenance into existing learning.model_registry table."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def upsert_model_registry_row(
    session: Session,
    *,
    model_name: str,
    model_version: str,
    parameters: dict[str, Any],
    training_dataset: str,
    metrics: dict[str, float],
    status: str,
) -> None:
    """Insert or update learning.model_registry without a new migration."""
    session.execute(
        text(
            """
INSERT INTO learning.model_registry
    (model_name, model_version, created_at, parameters, training_dataset, metrics, status)
VALUES
    (:model_name, :model_version, :created_at, CAST(:parameters AS jsonb),
     :training_dataset, CAST(:metrics AS jsonb), :status)
ON CONFLICT (model_name, model_version) DO UPDATE SET
    parameters = EXCLUDED.parameters,
    training_dataset = EXCLUDED.training_dataset,
    metrics = EXCLUDED.metrics,
    status = EXCLUDED.status
"""
        ),
        {
            "model_name": model_name,
            "model_version": model_version,
            "created_at": datetime.now(UTC),
            "parameters": json.dumps(parameters),
            "training_dataset": training_dataset,
            "metrics": json.dumps(metrics),
            "status": status,
        },
    )
