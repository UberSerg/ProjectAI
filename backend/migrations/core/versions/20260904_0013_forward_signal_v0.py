"""Forward Signal V0 persistence tables.

Revision ID: 20260904_0013
Revises: 20260904_0012
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260904_0013"
down_revision: str | None = "20260904_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning.forward_prediction_batches (
            id BIGSERIAL PRIMARY KEY,
            as_of_date DATE NOT NULL,
            segment TEXT NOT NULL DEFAULT 'FORWARD_LIVE',
            candidate_name TEXT NOT NULL,
            candidate_version TEXT NOT NULL,
            candidate_config_hash TEXT NOT NULL,
            feature_schema_hash TEXT NOT NULL,
            dataset_values_hash TEXT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            instrument_count INTEGER NOT NULL DEFAULT 0,
            eligible_count INTEGER NOT NULL DEFAULT 0,
            ineligible_count INTEGER NOT NULL DEFAULT 0,
            prediction_count INTEGER NOT NULL DEFAULT 0,
            input_lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
            input_lineage_hash TEXT NULL,
            prediction_hash TEXT NULL,
            pit_status TEXT NOT NULL DEFAULT 'PENDING',
            completeness JSONB NULL,
            timings JSONB NULL,
            error_message TEXT NULL,
            generated_at TIMESTAMPTZ NULL,
            started_at TIMESTAMPTZ NULL,
            completed_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_forward_batches_as_of_created
            ON learning.forward_prediction_batches (as_of_date DESC, created_at DESC);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_forward_batches_status_as_of
            ON learning.forward_prediction_batches (status, as_of_date DESC);
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning.forward_predictions (
            id BIGSERIAL PRIMARY KEY,
            batch_id BIGINT NOT NULL
                REFERENCES learning.forward_prediction_batches(id) ON DELETE CASCADE,
            as_of_date DATE NOT NULL,
            instrument_id BIGINT NOT NULL,
            ticker TEXT NOT NULL,
            predicted_return_20d DOUBLE PRECISION NOT NULL,
            rank INTEGER NULL,
            eligible_count INTEGER NULL,
            percentile DOUBLE PRECISION NULL,
            quality_status TEXT NOT NULL DEFAULT 'OK',
            candidate_config_hash TEXT NOT NULL,
            feature_schema_hash TEXT NOT NULL,
            input_lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
            segment TEXT NOT NULL DEFAULT 'FORWARD_LIVE',
            outcome_status TEXT NOT NULL DEFAULT 'PENDING_OUTCOME',
            generated_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_forward_pred_candidate_asof_instrument
                UNIQUE (candidate_config_hash, as_of_date, instrument_id)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_forward_predictions_batch_rank
            ON learning.forward_predictions (batch_id, rank);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS learning.forward_predictions;")
    op.execute("DROP TABLE IF EXISTS learning.forward_prediction_batches;")
