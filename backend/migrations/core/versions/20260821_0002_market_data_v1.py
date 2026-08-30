"""Market Data V1 storage.

Revision ID: 20260821_0002
Revises: 20260321_0001
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260821_0002"
down_revision: str | None = "20260321_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS market")
    op.execute("ALTER TABLE system.workflows ADD COLUMN IF NOT EXISTS workflow_type TEXT")
    op.execute("ALTER TABLE system.workflows ADD COLUMN IF NOT EXISTS progress JSONB")
    op.execute(
        """
        CREATE TABLE market.instruments (
            id BIGSERIAL PRIMARY KEY,
            symbol TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            instrument_type TEXT NOT NULL,
            currency TEXT,
            exchange TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE market.instrument_sources (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            board TEXT NOT NULL DEFAULT '',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (source, external_id, board)
        );
        CREATE TABLE market.candles (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
            timeframe TEXT NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            open NUMERIC(24,8),
            high NUMERIC(24,8),
            low NUMERIC(24,8),
            close NUMERIC(24,8) NOT NULL,
            volume NUMERIC(28,8),
            source TEXT NOT NULL,
            batch_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (instrument_id, timeframe, timestamp, source)
        );
        CREATE TABLE market.series (
            id BIGSERIAL PRIMARY KEY,
            symbol TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            unit TEXT,
            frequency TEXT NOT NULL DEFAULT 'daily',
            source TEXT NOT NULL,
            external_id TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE market.series_values (
            id BIGSERIAL PRIMARY KEY,
            series_id BIGINT NOT NULL REFERENCES market.series(id) ON DELETE CASCADE,
            timestamp TIMESTAMPTZ NOT NULL,
            value NUMERIC(24,8) NOT NULL,
            source TEXT NOT NULL,
            batch_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (series_id, timestamp, source)
        );
        CREATE TABLE market.corporate_actions (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
            action_type TEXT NOT NULL,
            effective_date DATE NOT NULL,
            value NUMERIC(24,8),
            currency TEXT,
            source TEXT NOT NULL,
            external_id TEXT,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (instrument_id, action_type, effective_date, source)
        );
        CREATE TABLE market.ingestion_batches (
            id UUID PRIMARY KEY,
            source TEXT NOT NULL,
            data_type TEXT NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            records_fetched INTEGER NOT NULL DEFAULT 0,
            records_written INTEGER NOT NULL DEFAULT 0,
            raw_path TEXT,
            error TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        );
        CREATE TABLE market.data_quality_issues (
            id BIGSERIAL PRIMARY KEY,
            batch_id UUID REFERENCES market.ingestion_batches(id) ON DELETE SET NULL,
            instrument_id BIGINT REFERENCES market.instruments(id) ON DELETE CASCADE,
            series_id BIGINT REFERENCES market.series(id) ON DELETE CASCADE,
            check_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp TIMESTAMPTZ,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at TIMESTAMPTZ
        );
        CREATE INDEX ix_candles_instrument_timeframe_timestamp
            ON market.candles (instrument_id, timeframe, timestamp);
        CREATE INDEX ix_candles_timestamp ON market.candles (timestamp);
        CREATE INDEX ix_ingestion_batches_status_started
            ON market.ingestion_batches (status, started_at);
        CREATE INDEX ix_data_quality_issues_severity_created
            ON market.data_quality_issues (severity, created_at);
        """
    )


def downgrade() -> None:
    for table in (
        "data_quality_issues",
        "corporate_actions",
        "series_values",
        "series",
        "candles",
        "instrument_sources",
        "instruments",
        "ingestion_batches",
    ):
        op.execute(f"DROP TABLE IF EXISTS market.{table} CASCADE")
    op.execute("ALTER TABLE system.workflows DROP COLUMN IF EXISTS progress")
    op.execute("ALTER TABLE system.workflows DROP COLUMN IF EXISTS workflow_type")
"""Market Data V1 schema.

Revision ID: 20260821_0002
Revises: 20260321_0001
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260821_0002"
down_revision: str | None = "20260321_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE system.workflows
            ADD COLUMN IF NOT EXISTS workflow_type TEXT,
            ADD COLUMN IF NOT EXISTS meta JSONB NOT NULL DEFAULT '{}'::jsonb
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_system_workflows_status_started
            ON system.workflows (status, started_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_system_workflows_type_started
            ON system.workflows (workflow_type, started_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.instruments (
            id BIGSERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            exchange TEXT NOT NULL,
            currency TEXT NOT NULL,
            sector TEXT,
            isin TEXT,
            active_from DATE,
            active_to DATE,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_market_instruments_symbol_exchange UNIQUE (symbol, exchange)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_instruments_active_class
            ON market.instruments (is_active, asset_class)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.instrument_sources (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            board TEXT,
            source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_market_instrument_sources UNIQUE (source, external_id, board)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_instrument_sources_instrument
            ON market.instrument_sources (instrument_id)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.candles (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
            timeframe TEXT NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            open NUMERIC(18, 6) NOT NULL,
            high NUMERIC(18, 6) NOT NULL,
            low NUMERIC(18, 6) NOT NULL,
            close NUMERIC(18, 6) NOT NULL,
            volume NUMERIC(24, 6),
            source TEXT NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_market_candles UNIQUE (instrument_id, timeframe, timestamp, source)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_candles_instrument_tf_ts
            ON market.candles (instrument_id, timeframe, timestamp)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_candles_timestamp
            ON market.candles (timestamp)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.series (
            id BIGSERIAL PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            unit TEXT,
            source TEXT NOT NULL,
            description TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.series_values (
            id BIGSERIAL PRIMARY KEY,
            series_id BIGINT NOT NULL REFERENCES market.series(id) ON DELETE CASCADE,
            timestamp TIMESTAMPTZ NOT NULL,
            value NUMERIC(24, 8) NOT NULL,
            source TEXT NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_market_series_values UNIQUE (series_id, timestamp, source)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_series_values_series_ts
            ON market.series_values (series_id, timestamp)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.corporate_actions (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
            event_date DATE NOT NULL,
            event_type TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            source TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_corporate_actions_instrument_date
            ON market.corporate_actions (instrument_id, event_date)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.ingestion_batches (
            id BIGSERIAL PRIMARY KEY,
            source TEXT NOT NULL,
            data_type TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            status TEXT NOT NULL,
            records_received INTEGER NOT NULL DEFAULT 0,
            records_inserted INTEGER NOT NULL DEFAULT 0,
            records_updated INTEGER NOT NULL DEFAULT 0,
            records_rejected INTEGER NOT NULL DEFAULT 0,
            raw_location TEXT,
            error_message TEXT,
            workflow_id BIGINT REFERENCES system.workflows(id) ON DELETE SET NULL,
            meta JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_ingestion_batches_status_started
            ON market.ingestion_batches (status, started_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.data_quality_issues (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT REFERENCES market.instruments(id) ON DELETE SET NULL,
            batch_id BIGINT REFERENCES market.ingestion_batches(id) ON DELETE SET NULL,
            issue_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            timestamp TIMESTAMPTZ,
            message TEXT NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_dq_severity_created
            ON market.data_quality_issues (severity, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market.data_quality_issues")
    op.execute("DROP TABLE IF EXISTS market.ingestion_batches")
    op.execute("DROP TABLE IF EXISTS market.corporate_actions")
    op.execute("DROP TABLE IF EXISTS market.series_values")
    op.execute("DROP TABLE IF EXISTS market.series")
    op.execute("DROP TABLE IF EXISTS market.candles")
    op.execute("DROP TABLE IF EXISTS market.instrument_sources")
    op.execute("DROP TABLE IF EXISTS market.instruments")
    op.execute("DROP INDEX IF EXISTS ix_system_workflows_type_started")
    op.execute("DROP INDEX IF EXISTS ix_system_workflows_status_started")
    op.execute("ALTER TABLE system.workflows DROP COLUMN IF EXISTS meta")
    op.execute("ALTER TABLE system.workflows DROP COLUMN IF EXISTS workflow_type")
