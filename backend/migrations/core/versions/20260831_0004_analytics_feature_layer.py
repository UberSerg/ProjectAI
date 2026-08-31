"""Analytics Feature Layer V1 — versioned feature store.

Revision ID: 20260831_0004
Revises: 20260830_0003
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260831_0004"
down_revision: str | None = "20260830_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS analytics")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics.feature_sets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code TEXT NOT NULL,
            version INTEGER NOT NULL,
            description TEXT,
            parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
            is_active BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_analytics_feature_sets_code_version UNIQUE (code, version)
        );

        CREATE INDEX IF NOT EXISTS ix_analytics_feature_sets_active
            ON analytics.feature_sets (is_active) WHERE is_active = TRUE;

        CREATE TABLE IF NOT EXISTS analytics.feature_runs (
            id BIGSERIAL PRIMARY KEY,
            feature_set_id UUID NOT NULL REFERENCES analytics.feature_sets(id),
            run_type TEXT NOT NULL,
            date_from DATE,
            date_to DATE,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'PENDING',
            instruments_total INTEGER NOT NULL DEFAULT 0,
            instrument_rows_calculated INTEGER NOT NULL DEFAULT 0,
            series_rows_calculated INTEGER NOT NULL DEFAULT 0,
            rows_valid INTEGER NOT NULL DEFAULT 0,
            rows_invalid INTEGER NOT NULL DEFAULT 0,
            rows_skipped INTEGER NOT NULL DEFAULT 0,
            source_watermark TIMESTAMPTZ,
            error_message TEXT,
            workflow_id BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_analytics_feature_runs_type CHECK (run_type IN ('BACKFILL', 'UPDATE'))
        );

        CREATE INDEX IF NOT EXISTS ix_analytics_feature_runs_feature_set
            ON analytics.feature_runs (feature_set_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_analytics_feature_runs_status
            ON analytics.feature_runs (status, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_analytics_feature_runs_workflow
            ON analytics.feature_runs (workflow_id);

        CREATE TABLE IF NOT EXISTS analytics.instrument_features_daily (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            timeframe TEXT NOT NULL DEFAULT '1d',
            feature_set_id UUID NOT NULL REFERENCES analytics.feature_sets(id),
            feature_version INTEGER NOT NULL,
            close NUMERIC(18, 6),
            volume NUMERIC(24, 6),
            return_1d NUMERIC(18, 8),
            return_2d NUMERIC(18, 8),
            return_3d NUMERIC(18, 8),
            return_5d NUMERIC(18, 8),
            return_10d NUMERIC(18, 8),
            return_20d NUMERIC(18, 8),
            log_return_1d NUMERIC(18, 8),
            volatility_5d NUMERIC(18, 8),
            volatility_20d NUMERIC(18, 8),
            drawdown_20d NUMERIC(18, 8),
            volume_change_1d NUMERIC(18, 8),
            volume_zscore_20d NUMERIC(18, 8),
            has_sufficient_history BOOLEAN NOT NULL DEFAULT FALSE,
            is_valid BOOLEAN NOT NULL DEFAULT TRUE,
            quality_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
            calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            source_updated_at TIMESTAMPTZ,
            CONSTRAINT uq_analytics_instrument_features_daily
                UNIQUE (instrument_id, date, timeframe, feature_set_id)
        );

        CREATE INDEX IF NOT EXISTS ix_analytics_instrument_features_instrument_date
            ON analytics.instrument_features_daily (instrument_id, date DESC);
        CREATE INDEX IF NOT EXISTS ix_analytics_instrument_features_set_date
            ON analytics.instrument_features_daily (feature_set_id, date DESC);
        CREATE INDEX IF NOT EXISTS ix_analytics_instrument_features_valid
            ON analytics.instrument_features_daily (is_valid, date DESC);

        CREATE TABLE IF NOT EXISTS analytics.series_features_daily (
            id BIGSERIAL PRIMARY KEY,
            series_id BIGINT NOT NULL REFERENCES market.series(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            feature_set_id UUID NOT NULL REFERENCES analytics.feature_sets(id),
            value NUMERIC(24, 8),
            previous_value NUMERIC(24, 8),
            absolute_change NUMERIC(24, 8),
            pct_change NUMERIC(18, 8),
            days_since_change INTEGER,
            is_valid BOOLEAN NOT NULL DEFAULT TRUE,
            quality_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
            calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_analytics_series_features_daily
                UNIQUE (series_id, date, feature_set_id)
        );

        CREATE INDEX IF NOT EXISTS ix_analytics_series_features_series_date
            ON analytics.series_features_daily (series_id, date DESC);
        CREATE INDEX IF NOT EXISTS ix_analytics_series_features_set_date
            ON analytics.series_features_daily (feature_set_id, date DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS analytics.series_features_daily;
        DROP TABLE IF EXISTS analytics.instrument_features_daily;
        DROP TABLE IF EXISTS analytics.feature_runs;
        DROP TABLE IF EXISTS analytics.feature_sets;
        """
    )
