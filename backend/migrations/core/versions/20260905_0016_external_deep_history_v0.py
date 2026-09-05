"""External Deep History V0 — read-only staging for an external long-history CSV.

Revision ID: 20260905_0016
Revises: 20260904_0015
Create Date: 2026-09-05

Staging only. market.candles stays the canonical RAW MOEX observation store and is
never written by this feature. External rows live in separate market.external_*
tables until identity, reconciliation and price semantics are proven.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260905_0016"
down_revision: str | None = "20260904_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.external_sources (
            id BIGSERIAL PRIMARY KEY,
            source_code TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_size BIGINT NULL,
            file_sha256 TEXT NOT NULL,
            imported_at TIMESTAMPTZ NULL,
            parser_version TEXT NOT NULL,
            price_semantic TEXT NOT NULL DEFAULT 'UNKNOWN',
            status TEXT NOT NULL DEFAULT 'REGISTERED',
            audit_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_market_external_sources_code UNIQUE (source_code),
            CONSTRAINT uq_market_external_sources_sha256 UNIQUE (file_sha256)
        );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.external_source_instruments (
            id BIGSERIAL PRIMARY KEY,
            source_id BIGINT NOT NULL
                REFERENCES market.external_sources(id) ON DELETE CASCADE,
            source_symbol TEXT NOT NULL,
            first_date DATE NULL,
            last_date DATE NULL,
            observations BIGINT NOT NULL DEFAULT 0,
            active_years INTEGER[] NOT NULL DEFAULT '{}'::integer[],
            match_status TEXT NOT NULL DEFAULT 'UNKNOWN_HISTORICAL_SYMBOL',
            mapping_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            project_symbol TEXT NULL,
            quality_status TEXT NOT NULL DEFAULT 'UNKNOWN',
            research_eligible BOOLEAN NOT NULL DEFAULT FALSE,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_market_external_source_instruments
                UNIQUE (source_id, source_symbol)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_external_source_instruments_match
            ON market.external_source_instruments (source_id, match_status);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_external_source_instruments_research
            ON market.external_source_instruments (source_id, research_eligible);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_external_source_instruments_project_symbol
            ON market.external_source_instruments (project_symbol)
            WHERE project_symbol IS NOT NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.external_candles_daily (
            id BIGSERIAL PRIMARY KEY,
            source_id BIGINT NOT NULL
                REFERENCES market.external_sources(id) ON DELETE CASCADE,
            source_symbol TEXT NOT NULL,
            trade_date DATE NOT NULL,
            open NUMERIC(20, 8) NULL,
            high NUMERIC(20, 8) NULL,
            low NUMERIC(20, 8) NULL,
            close NUMERIC(20, 8) NULL,
            volume NUMERIC(28, 8) NULL,
            value NUMERIC(28, 8) NULL,
            reject_reason TEXT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_market_external_candles_daily
                UNIQUE (source_id, source_symbol, trade_date)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_external_candles_daily_symbol_date
            ON market.external_candles_daily (source_id, source_symbol, trade_date);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_external_candles_daily_date
            ON market.external_candles_daily (trade_date);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_external_candles_daily_year
            ON market.external_candles_daily (source_id, (EXTRACT(YEAR FROM trade_date)::INTEGER));
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_external_candles_daily_rejects
            ON market.external_candles_daily (source_id, reject_reason)
            WHERE reject_reason IS NOT NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.external_audit_runs (
            id BIGSERIAL PRIMARY KEY,
            source_id BIGINT NULL
                REFERENCES market.external_sources(id) ON DELETE SET NULL,
            run_type TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ NULL,
            status TEXT NOT NULL DEFAULT 'RUNNING',
            report JSONB NOT NULL DEFAULT '{}'::jsonb,
            metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_external_audit_runs_source_type
            ON market.external_audit_runs (source_id, run_type, started_at DESC);
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.external_reconciliation (
            id BIGSERIAL PRIMARY KEY,
            source_id BIGINT NOT NULL
                REFERENCES market.external_sources(id) ON DELETE CASCADE,
            source_symbol TEXT NOT NULL,
            project_symbol TEXT NULL,
            overlap_rows BIGINT NOT NULL DEFAULT 0,
            exact_ohlc_rows BIGINT NOT NULL DEFAULT 0,
            close_rel_med DOUBLE PRECISION NULL,
            close_rel_p95 DOUBLE PRECISION NULL,
            close_rel_p99 DOUBLE PRECISION NULL,
            volume_rel_med DOUBLE PRECISION NULL,
            status TEXT NOT NULL DEFAULT 'UNKNOWN',
            ca_probe_result JSONB NOT NULL DEFAULT '{}'::jsonb,
            metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_market_external_reconciliation
                UNIQUE (source_id, source_symbol)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_external_reconciliation_status
            ON market.external_reconciliation (source_id, status);
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.external_curated_eligibility (
            id BIGSERIAL PRIMARY KEY,
            source_id BIGINT NOT NULL
                REFERENCES market.external_sources(id) ON DELETE CASCADE,
            source_symbol TEXT NOT NULL,
            trade_date DATE NOT NULL,
            eligibility TEXT NOT NULL,
            reason TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_market_external_curated_eligibility
                UNIQUE (source_id, source_symbol, trade_date)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_external_curated_eligibility_status
            ON market.external_curated_eligibility (source_id, eligibility);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_external_curated_eligibility_date
            ON market.external_curated_eligibility (trade_date);
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.external_ml_readiness (
            id BIGSERIAL PRIMARY KEY,
            source_id BIGINT NOT NULL
                REFERENCES market.external_sources(id) ON DELETE CASCADE,
            year INTEGER NOT NULL,
            symbols BIGINT NOT NULL DEFAULT 0,
            eligible_symbols BIGINT NOT NULL DEFAULT 0,
            rows BIGINT NOT NULL DEFAULT 0,
            eligible_rows BIGINT NOT NULL DEFAULT 0,
            median_observations DOUBLE PRECISION NULL,
            feature_stack_status TEXT NOT NULL DEFAULT 'UNKNOWN',
            blocking_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
            metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_market_external_ml_readiness UNIQUE (source_id, year)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market.external_ml_readiness;")
    op.execute("DROP TABLE IF EXISTS market.external_curated_eligibility;")
    op.execute("DROP TABLE IF EXISTS market.external_reconciliation;")
    op.execute("DROP TABLE IF EXISTS market.external_audit_runs;")
    op.execute("DROP TABLE IF EXISTS market.external_candles_daily;")
    op.execute("DROP TABLE IF EXISTS market.external_source_instruments;")
    op.execute("DROP TABLE IF EXISTS market.external_sources;")
