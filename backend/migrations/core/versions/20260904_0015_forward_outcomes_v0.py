"""Forward prediction outcome evaluation V0.

Revision ID: 20260904_0015
Revises: 20260904_0014
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260904_0015"
down_revision: str | None = "20260904_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning.forward_prediction_outcomes (
            id BIGSERIAL PRIMARY KEY,
            forward_prediction_id BIGINT NOT NULL
                REFERENCES learning.forward_predictions(id) ON DELETE CASCADE,
            batch_id BIGINT NOT NULL
                REFERENCES learning.forward_prediction_batches(id) ON DELETE CASCADE,
            as_of_date DATE NOT NULL,
            instrument_id BIGINT NOT NULL,
            ticker TEXT NOT NULL,
            horizon_observations INTEGER NOT NULL DEFAULT 20,
            evaluator_version TEXT NOT NULL DEFAULT 'forward_outcome_v0',
            target_date DATE NULL,
            predicted_return_20d DOUBLE PRECISION NOT NULL,
            realized_return_20d DOUBLE PRECISION NULL,
            prediction_error DOUBLE PRECISION NULL,
            absolute_error DOUBLE PRECISION NULL,
            direction_correct BOOLEAN NULL,
            mechanical_ca_normalized BOOLEAN NOT NULL DEFAULT FALSE,
            quality_status TEXT NOT NULL DEFAULT 'PENDING',
            status TEXT NOT NULL DEFAULT 'PENDING_OUTCOME',
            label_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
            evaluated_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_forward_outcome_pred_horizon_version
                UNIQUE (forward_prediction_id, horizon_observations, evaluator_version)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_forward_outcomes_batch_status
            ON learning.forward_prediction_outcomes (batch_id, status);
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning.forward_batch_evaluations (
            id BIGSERIAL PRIMARY KEY,
            batch_id BIGINT NOT NULL
                REFERENCES learning.forward_prediction_batches(id) ON DELETE CASCADE,
            evaluator_version TEXT NOT NULL DEFAULT 'forward_outcome_v0',
            horizon_observations INTEGER NOT NULL DEFAULT 20,
            status TEXT NOT NULL DEFAULT 'PENDING',
            eligible_count INTEGER NOT NULL DEFAULT 0,
            evaluated_count INTEGER NOT NULL DEFAULT 0,
            invalid_count INTEGER NOT NULL DEFAULT 0,
            pending_count INTEGER NOT NULL DEFAULT 0,
            mean_predicted DOUBLE PRECISION NULL,
            mean_realized DOUBLE PRECISION NULL,
            mae DOUBLE PRECISION NULL,
            rmse DOUBLE PRECISION NULL,
            directional_accuracy DOUBLE PRECISION NULL,
            spearman_rank_ic DOUBLE PRECISION NULL,
            top20_realized_mean DOUBLE PRECISION NULL,
            bottom20_realized_mean DOUBLE PRECISION NULL,
            top_minus_bottom_spread DOUBLE PRECISION NULL,
            metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            evaluated_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_forward_batch_eval_version
                UNIQUE (batch_id, horizon_observations, evaluator_version)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS learning.forward_batch_evaluations;")
    op.execute("DROP TABLE IF EXISTS learning.forward_prediction_outcomes;")
