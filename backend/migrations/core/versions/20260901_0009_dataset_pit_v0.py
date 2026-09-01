"""Alembic: Dataset / PIT Join V0 tables.

Revision ID: 20260901_0009
Revises: 20260901_0008
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260901_0009"
down_revision: str | None = "20260901_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS learning")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning.dataset_specs (
            id UUID PRIMARY KEY,
            code TEXT NOT NULL,
            version INTEGER NOT NULL,
            description TEXT,
            feature_manifest JSONB NOT NULL DEFAULT '[]'::jsonb,
            relation_contexts JSONB NOT NULL DEFAULT '[]'::jsonb,
            label_spec JSONB NOT NULL DEFAULT '{}'::jsonb,
            quality_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
            basic_feature_set_code TEXT NOT NULL,
            basic_feature_set_version INTEGER NOT NULL,
            technical_feature_set_code TEXT NOT NULL,
            technical_feature_set_version INTEGER NOT NULL,
            technical_model_code TEXT NOT NULL,
            technical_model_version INTEGER NOT NULL,
            technical_model_config_hash TEXT,
            relation_set_code TEXT NOT NULL,
            relation_set_version INTEGER NOT NULL,
            universe_policy TEXT NOT NULL DEFAULT 'current_active_instruments',
            parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
            is_active BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_learning_dataset_specs_code_version UNIQUE (code, version)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_dataset_specs_one_active_per_code
            ON learning.dataset_specs (code)
            WHERE is_active = TRUE
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning.dataset_runs (
            id BIGSERIAL PRIMARY KEY,
            dataset_spec_id UUID NOT NULL REFERENCES learning.dataset_specs(id),
            date_from DATE,
            date_to DATE,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'PENDING',
            instruments_total INTEGER NOT NULL DEFAULT 0,
            samples_total INTEGER NOT NULL DEFAULT 0,
            eligible_1d INTEGER NOT NULL DEFAULT 0,
            eligible_5d INTEGER NOT NULL DEFAULT 0,
            eligible_10d INTEGER NOT NULL DEFAULT 0,
            eligible_20d INTEGER NOT NULL DEFAULT 0,
            core_invalid INTEGER NOT NULL DEFAULT 0,
            technical_missing INTEGER NOT NULL DEFAULT 0,
            relation_missing INTEGER NOT NULL DEFAULT 0,
            invalid_labels INTEGER NOT NULL DEFAULT 0,
            pit_violations INTEGER NOT NULL DEFAULT 0,
            pit_status TEXT NOT NULL DEFAULT 'PENDING',
            source_watermark JSONB,
            coverage_summary JSONB,
            manifest JSONB,
            resolved_universe JSONB,
            dataset_hash TEXT,
            workflow_id BIGINT,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_learning_dataset_runs_spec
            ON learning.dataset_runs (dataset_spec_id)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning.dataset_samples_daily (
            id BIGSERIAL PRIMARY KEY,
            dataset_run_id BIGINT NOT NULL REFERENCES learning.dataset_runs(id) ON DELETE CASCADE,
            dataset_spec_id UUID NOT NULL REFERENCES learning.dataset_specs(id),
            instrument_id BIGINT NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
            as_of_date DATE NOT NULL,
            features JSONB NOT NULL DEFAULT '{}'::jsonb,
            labels JSONB NOT NULL DEFAULT '{}'::jsonb,
            feature_quality JSONB NOT NULL DEFAULT '{}'::jsonb,
            label_quality JSONB NOT NULL DEFAULT '{}'::jsonb,
            training_eligibility JSONB NOT NULL DEFAULT '{}'::jsonb,
            lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
            content_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_learning_dataset_samples_daily
                UNIQUE (dataset_run_id, instrument_id, as_of_date)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_learning_dataset_samples_run
            ON learning.dataset_samples_daily (dataset_run_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_learning_dataset_samples_instrument_date
            ON learning.dataset_samples_daily (instrument_id, as_of_date)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS learning.dataset_samples_daily")
    op.execute("DROP TABLE IF EXISTS learning.dataset_runs")
    op.execute("DROP TABLE IF EXISTS learning.dataset_specs")
