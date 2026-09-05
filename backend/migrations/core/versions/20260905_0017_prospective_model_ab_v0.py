"""Prospective Model A/B V0 — synchronized forward V0 vs V1 experiment.

Revision ID: 20260905_0017
Revises: 20260905_0016
Create Date: 2026-09-05

Prospective only. No historical paired backfill: comparison batches may only exist for
as_of dates that appear strictly after the market watermark captured at activation.
market.candles is never written by this feature.

`prediction_semantic` is added to the Forward tables because Candidate V1 Ranker stores a
RANKING_SCORE in the historical `predicted_return_20d` column. The default keeps every
existing row EXPECTED_RETURN so operational V0 behaviour is unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260905_0017"
down_revision: str | None = "20260905_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE learning.forward_prediction_batches
            ADD COLUMN IF NOT EXISTS prediction_semantic TEXT NOT NULL
            DEFAULT 'EXPECTED_RETURN';
        """
    )
    op.execute(
        """
        ALTER TABLE learning.forward_predictions
            ADD COLUMN IF NOT EXISTS prediction_semantic TEXT NOT NULL
            DEFAULT 'EXPECTED_RETURN';
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_forward_prediction_batches_candidate_asof
            ON learning.forward_prediction_batches (candidate_config_hash, as_of_date);
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning.prospective_model_experiments (
            id BIGSERIAL PRIMARY KEY,
            code TEXT NOT NULL,
            human_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'REGISTERED',
            candidate_a_name TEXT NOT NULL,
            candidate_a_version TEXT NOT NULL,
            candidate_a_config_hash TEXT NOT NULL,
            candidate_b_name TEXT NOT NULL,
            candidate_b_version TEXT NOT NULL,
            candidate_b_config_hash TEXT NOT NULL,
            policy_name TEXT NOT NULL,
            risk_name TEXT NOT NULL,
            capital DOUBLE PRECISION NOT NULL DEFAULT 1000000.0,
            activated_at TIMESTAMPTZ NULL,
            activation_market_watermark DATE NULL,
            first_eligible_market_date DATE NULL,
            shadow_portfolio_a_id BIGINT NULL,
            shadow_portfolio_b_id BIGINT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_prospective_model_experiments_code UNIQUE (code)
        );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning.prospective_model_comparison_batches (
            id BIGSERIAL PRIMARY KEY,
            experiment_id BIGINT NOT NULL
                REFERENCES learning.prospective_model_experiments(id) ON DELETE CASCADE,
            as_of_date DATE NOT NULL,
            generated_at TIMESTAMPTZ NULL,
            market_watermark DATE NULL,
            feature_snapshot_hash TEXT NULL,
            feature_schema_hash TEXT NULL,
            candidate_a_batch_id BIGINT NULL
                REFERENCES learning.forward_prediction_batches(id) ON DELETE SET NULL,
            candidate_b_batch_id BIGINT NULL
                REFERENCES learning.forward_prediction_batches(id) ON DELETE SET NULL,
            eligible_a INTEGER NOT NULL DEFAULT 0,
            eligible_b INTEGER NOT NULL DEFAULT 0,
            common_eligible INTEGER NOT NULL DEFAULT 0,
            comparability_status TEXT NOT NULL DEFAULT 'NOT_COMPARABLE',
            rank_correlation DOUBLE PRECISION NULL,
            top20_overlap DOUBLE PRECISION NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            error_message TEXT NULL,
            summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_prospective_model_comparison_batches
                UNIQUE (experiment_id, as_of_date),
            CONSTRAINT ck_prospective_model_comparability CHECK (
                comparability_status IN (
                    'FULLY_COMPARABLE', 'PARTIALLY_COMPARABLE', 'NOT_COMPARABLE'
                )
            )
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_prospective_model_comparison_batches_status
            ON learning.prospective_model_comparison_batches (experiment_id, status);
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning.model_diagnostics_runs (
            id BIGSERIAL PRIMARY KEY,
            diagnostics_version TEXT NOT NULL DEFAULT 'MODEL_DIAGNOSTICS_V0',
            input_hash TEXT NOT NULL,
            period_from DATE NULL,
            period_to DATE NULL,
            candidate_a_hash TEXT NULL,
            candidate_b_hash TEXT NULL,
            dataset_values_hash TEXT NULL,
            status TEXT NOT NULL DEFAULT 'SUCCESS',
            report JSONB NOT NULL DEFAULT '{}'::jsonb,
            metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_model_diagnostics_runs_input_hash UNIQUE (input_hash)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_model_diagnostics_runs_version_created
            ON learning.model_diagnostics_runs (diagnostics_version, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS learning.model_diagnostics_runs;")
    op.execute("DROP TABLE IF EXISTS learning.prospective_model_comparison_batches;")
    op.execute("DROP TABLE IF EXISTS learning.prospective_model_experiments;")
    op.execute(
        "DROP INDEX IF EXISTS learning.ix_forward_prediction_batches_candidate_asof;"
    )
    op.execute(
        "ALTER TABLE learning.forward_predictions DROP COLUMN IF EXISTS prediction_semantic;"
    )
    op.execute(
        "ALTER TABLE learning.forward_prediction_batches "
        "DROP COLUMN IF EXISTS prediction_semantic;"
    )
