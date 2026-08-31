"""Relations Engine V1 — relation inputs, sets, runs, snapshots, lag metrics.

Revision ID: 20260831_0006
Revises: 20260831_0005
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260831_0006"
down_revision: str | None = "20260831_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS analytics")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics.relation_inputs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code TEXT NOT NULL,
            input_family TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id BIGINT NOT NULL,
            feature_key TEXT NOT NULL,
            transform TEXT NOT NULL,
            alignment_policy TEXT NOT NULL,
            display_name TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            extra JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_analytics_relation_inputs_code UNIQUE (code),
            CONSTRAINT ck_analytics_relation_inputs_family
                CHECK (input_family IN ('instrument_feature', 'series_feature'))
        );

        CREATE INDEX IF NOT EXISTS ix_analytics_relation_inputs_active
            ON analytics.relation_inputs (is_active) WHERE is_active = TRUE;
        CREATE INDEX IF NOT EXISTS ix_analytics_relation_inputs_subject
            ON analytics.relation_inputs (subject_type, subject_id);
        CREATE INDEX IF NOT EXISTS ix_analytics_relation_inputs_family
            ON analytics.relation_inputs (input_family);

        CREATE TABLE IF NOT EXISTS analytics.relation_sets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code TEXT NOT NULL,
            version INTEGER NOT NULL,
            description TEXT,
            parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
            is_active BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_analytics_relation_sets_code_version UNIQUE (code, version)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_analytics_relation_sets_one_active_per_code
            ON analytics.relation_sets (code)
            WHERE is_active = TRUE;

        CREATE INDEX IF NOT EXISTS ix_analytics_relation_sets_active
            ON analytics.relation_sets (is_active) WHERE is_active = TRUE;

        CREATE TABLE IF NOT EXISTS analytics.relation_runs (
            id BIGSERIAL PRIMARY KEY,
            relation_set_id UUID NOT NULL REFERENCES analytics.relation_sets(id),
            run_type TEXT NOT NULL,
            as_of_from DATE,
            as_of_to DATE,
            cadence TEXT,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'PENDING',
            inputs_total INTEGER NOT NULL DEFAULT 0,
            pairs_calculated INTEGER NOT NULL DEFAULT 0,
            snapshots_written INTEGER NOT NULL DEFAULT 0,
            snapshots_valid INTEGER NOT NULL DEFAULT 0,
            snapshots_invalid INTEGER NOT NULL DEFAULT 0,
            snapshots_skipped INTEGER NOT NULL DEFAULT 0,
            source_watermark TIMESTAMPTZ,
            error_message TEXT,
            workflow_id BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_analytics_relation_runs_type CHECK (run_type IN ('LATEST', 'BACKFILL')),
            CONSTRAINT ck_analytics_relation_runs_cadence
                CHECK (cadence IS NULL OR cadence IN ('DAILY', 'WEEKLY'))
        );

        CREATE INDEX IF NOT EXISTS ix_analytics_relation_runs_set
            ON analytics.relation_runs (relation_set_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_analytics_relation_runs_status
            ON analytics.relation_runs (status, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_analytics_relation_runs_workflow
            ON analytics.relation_runs (workflow_id);

        CREATE TABLE IF NOT EXISTS analytics.relation_snapshots (
            id BIGSERIAL PRIMARY KEY,
            relation_run_id BIGINT NOT NULL REFERENCES analytics.relation_runs(id),
            relation_set_id UUID NOT NULL REFERENCES analytics.relation_sets(id),
            relation_set_version INTEGER NOT NULL,
            as_of_date DATE NOT NULL,
            window_observations INTEGER NOT NULL,
            input_a_id UUID NOT NULL REFERENCES analytics.relation_inputs(id),
            input_b_id UUID NOT NULL REFERENCES analytics.relation_inputs(id),
            sample_count INTEGER NOT NULL DEFAULT 0,
            coverage_ratio NUMERIC(10, 6),
            pearson NUMERIC(18, 8),
            spearman NUMERIC(18, 8),
            rolling_corr_mean NUMERIC(18, 8),
            rolling_corr_std NUMERIC(18, 8),
            sign_consistency NUMERIC(18, 8),
            best_leader_input_id UUID REFERENCES analytics.relation_inputs(id),
            best_follower_input_id UUID REFERENCES analytics.relation_inputs(id),
            best_lag INTEGER,
            best_lag_pearson NUMERIC(18, 8),
            best_lag_spearman NUMERIC(18, 8),
            is_valid BOOLEAN NOT NULL DEFAULT TRUE,
            quality_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
            calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_analytics_relation_snapshots_unordered_pair
                CHECK (input_a_id < input_b_id),
            CONSTRAINT uq_analytics_relation_snapshots_pair
                UNIQUE (relation_set_id, as_of_date, window_observations, input_a_id, input_b_id)
        );

        CREATE INDEX IF NOT EXISTS ix_analytics_relation_snapshots_as_of
            ON analytics.relation_snapshots (as_of_date DESC);
        CREATE INDEX IF NOT EXISTS ix_analytics_relation_snapshots_set_as_of
            ON analytics.relation_snapshots (relation_set_id, as_of_date DESC);
        CREATE INDEX IF NOT EXISTS ix_analytics_relation_snapshots_run
            ON analytics.relation_snapshots (relation_run_id);
        CREATE INDEX IF NOT EXISTS ix_analytics_relation_snapshots_pair_lookup
            ON analytics.relation_snapshots (input_a_id, input_b_id, as_of_date DESC);
        CREATE INDEX IF NOT EXISTS ix_analytics_relation_snapshots_valid
            ON analytics.relation_snapshots (is_valid, as_of_date DESC);
        CREATE INDEX IF NOT EXISTS ix_analytics_relation_snapshots_abs_pearson
            ON analytics.relation_snapshots (as_of_date DESC, window_observations);

        CREATE TABLE IF NOT EXISTS analytics.relation_lag_metrics (
            id BIGSERIAL PRIMARY KEY,
            snapshot_id BIGINT NOT NULL REFERENCES analytics.relation_snapshots(id) ON DELETE CASCADE,
            leader_input_id UUID NOT NULL REFERENCES analytics.relation_inputs(id),
            follower_input_id UUID NOT NULL REFERENCES analytics.relation_inputs(id),
            lag INTEGER NOT NULL,
            pearson NUMERIC(18, 8),
            spearman NUMERIC(18, 8),
            sample_count INTEGER NOT NULL DEFAULT 0,
            coverage_ratio NUMERIC(10, 6),
            CONSTRAINT ck_analytics_relation_lag_positive CHECK (lag >= 1),
            CONSTRAINT uq_analytics_relation_lag_metrics
                UNIQUE (snapshot_id, leader_input_id, follower_input_id, lag)
        );

        CREATE INDEX IF NOT EXISTS ix_analytics_relation_lag_metrics_snapshot
            ON analytics.relation_lag_metrics (snapshot_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS analytics.relation_lag_metrics CASCADE")
    op.execute("DROP TABLE IF EXISTS analytics.relation_snapshots CASCADE")
    op.execute("DROP TABLE IF EXISTS analytics.relation_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS analytics.relation_sets CASCADE")
    op.execute("DROP TABLE IF EXISTS analytics.relation_inputs CASCADE")
