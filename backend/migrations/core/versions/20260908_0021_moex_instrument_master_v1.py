"""MOEX Instrument Master V1 + Manual Portfolio V1 tables.

Revision ID: 20260908_0021
Revises: 20260907_0020
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0021"
down_revision: str | None = "20260907_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS market")
    op.execute("CREATE SCHEMA IF NOT EXISTS portfolio")

    # Additive Instrument Master columns (nullable; skip-safe via IF NOT EXISTS).
    op.execute(
        """
        ALTER TABLE market.instruments
            ADD COLUMN IF NOT EXISTS instrument_subtype TEXT,
            ADD COLUMN IF NOT EXISTS support_level TEXT,
            ADD COLUMN IF NOT EXISTS primary_board TEXT,
            ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_instruments_support_level
            ON market.instruments (support_level)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_instruments_subtype
            ON market.instruments (instrument_subtype)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.universe_memberships (
            universe_code TEXT NOT NULL,
            instrument_id BIGINT NOT NULL
                REFERENCES market.instruments(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (universe_code, instrument_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_universe_memberships_instrument
            ON market.universe_memberships (instrument_id)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.instrument_master_sync_runs (
            id BIGSERIAL PRIMARY KEY,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            status TEXT NOT NULL,
            report JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_instrument_master_sync_runs_started
            ON market.instrument_master_sync_runs (started_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.manual_portfolios (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'MANUAL',
            base_currency TEXT NOT NULL DEFAULT 'RUB',
            cash_rub NUMERIC(20, 6) NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            version INT NOT NULL DEFAULT 1
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.manual_positions (
            id BIGSERIAL PRIMARY KEY,
            portfolio_id BIGINT NOT NULL
                REFERENCES portfolio.manual_portfolios(id) ON DELETE CASCADE,
            instrument_id BIGINT NOT NULL
                REFERENCES market.instruments(id) ON DELETE RESTRICT,
            units NUMERIC(24, 8) NOT NULL,
            average_price NUMERIC(20, 6),
            note TEXT,
            non_standard_lot BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_portfolio_manual_positions_portfolio_instrument
                UNIQUE (portfolio_id, instrument_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_portfolio_manual_positions_instrument
            ON portfolio.manual_positions (instrument_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS portfolio.manual_positions")
    op.execute("DROP TABLE IF EXISTS portfolio.manual_portfolios")
    op.execute("DROP TABLE IF EXISTS market.instrument_master_sync_runs")
    op.execute("DROP TABLE IF EXISTS market.universe_memberships")
    op.execute("DROP INDEX IF EXISTS market.ix_market_instruments_subtype")
    op.execute("DROP INDEX IF EXISTS market.ix_market_instruments_support_level")
    op.execute(
        """
        ALTER TABLE market.instruments
            DROP COLUMN IF EXISTS last_seen_at,
            DROP COLUMN IF EXISTS first_seen_at,
            DROP COLUMN IF EXISTS primary_board,
            DROP COLUMN IF EXISTS support_level,
            DROP COLUMN IF EXISTS instrument_subtype
        """
    )
