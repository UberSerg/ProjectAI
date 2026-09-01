"""Alembic migration: Technical Agent V1 tables.

Revision ID: 20260901_0008
Revises: 20260831_0007
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260901_0008"
down_revision: str | None = "20260831_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS technical")
    op.execute("CREATE SCHEMA IF NOT EXISTS analytics")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics.instrument_technical_features_daily (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            timeframe TEXT NOT NULL DEFAULT '1d',
            feature_set_id UUID NOT NULL REFERENCES analytics.feature_sets(id),
            sma20 NUMERIC(18, 6),
            sma20_distance NUMERIC(18, 8),
            ema20 NUMERIC(18, 6),
            ema20_distance NUMERIC(18, 8),
            rsi14 NUMERIC(18, 8),
            atr14 NUMERIC(18, 6),
            atr14_pct NUMERIC(18, 8),
            has_sufficient_history BOOLEAN NOT NULL DEFAULT FALSE,
            is_valid BOOLEAN NOT NULL DEFAULT TRUE,
            quality_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
            source_basic_feature_id BIGINT,
            calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_analytics_instrument_technical_features_daily
                UNIQUE (instrument_id, date, timeframe, feature_set_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tech_feat_daily_date
            ON analytics.instrument_technical_features_daily (date)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tech_feat_daily_instrument_date
            ON analytics.instrument_technical_features_daily (instrument_id, date)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS technical.runs (
            id BIGSERIAL PRIMARY KEY,
            run_type TEXT NOT NULL,
            model_code TEXT NOT NULL,
            model_version INTEGER NOT NULL,
            model_config_hash TEXT NOT NULL,
            basic_feature_set_id UUID NOT NULL REFERENCES analytics.feature_sets(id),
            technical_feature_set_id UUID NOT NULL REFERENCES analytics.feature_sets(id),
            date_from DATE,
            date_to DATE,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'PENDING',
            instruments_total INTEGER NOT NULL DEFAULT 0,
            technical_feature_rows INTEGER NOT NULL DEFAULT 0,
            signal_rows INTEGER NOT NULL DEFAULT 0,
            valid_signals INTEGER NOT NULL DEFAULT 0,
            invalid_signals INTEGER NOT NULL DEFAULT 0,
            source_watermark JSONB,
            workflow_id BIGINT,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS technical.signals_daily (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
            as_of_date DATE NOT NULL,
            timeframe TEXT NOT NULL DEFAULT '1d',
            run_id BIGINT REFERENCES technical.runs(id),
            model_code TEXT NOT NULL,
            model_version INTEGER NOT NULL,
            model_config_hash TEXT NOT NULL,
            basic_feature_set_id UUID NOT NULL REFERENCES analytics.feature_sets(id),
            technical_feature_set_id UUID NOT NULL REFERENCES analytics.feature_sets(id),
            source_basic_feature_id BIGINT,
            source_technical_feature_id BIGINT,
            score NUMERIC(18, 8) NOT NULL,
            confidence NUMERIC(18, 8) NOT NULL,
            direction TEXT NOT NULL,
            trend_contribution NUMERIC(18, 8),
            momentum_contribution NUMERIC(18, 8),
            rsi_contribution NUMERIC(18, 8),
            volume_contribution NUMERIC(18, 8),
            is_valid BOOLEAN NOT NULL DEFAULT TRUE,
            quality_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
            calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_technical_signals_daily UNIQUE (
                instrument_id,
                as_of_date,
                timeframe,
                model_code,
                model_version,
                basic_feature_set_id,
                technical_feature_set_id
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_technical_signals_as_of
            ON technical.signals_daily (as_of_date)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_technical_signals_direction
            ON technical.signals_daily (direction)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS technical.signals_daily")
    op.execute("DROP TABLE IF EXISTS technical.runs")
    op.execute("DROP TABLE IF EXISTS analytics.instrument_technical_features_daily")
