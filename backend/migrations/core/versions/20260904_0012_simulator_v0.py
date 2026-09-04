"""Historical Simulator V0 persistence tables.

Revision ID: 20260904_0012
Revises: 20260903_0011
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260904_0012"
down_revision: str | None = "20260903_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.simulation_specs (
            id BIGSERIAL PRIMARY KEY,
            config_hash TEXT NOT NULL,
            segment TEXT NOT NULL,
            policy_name TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_portfolio_simulation_specs_config_hash UNIQUE (config_hash)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.simulation_runs (
            id BIGSERIAL PRIMARY KEY,
            simulation_spec_id BIGINT NOT NULL
                REFERENCES portfolio.simulation_specs(id),
            status TEXT NOT NULL DEFAULT 'PENDING',
            segment TEXT NOT NULL,
            date_from DATE NULL,
            date_to DATE NULL,
            candidate_config_hash TEXT NULL,
            dataset_values_hash TEXT NULL,
            prediction_hash TEXT NULL,
            values_hash TEXT NULL,
            metrics JSONB NULL,
            benchmark JSONB NULL,
            provenance JSONB NULL,
            error_message TEXT NULL,
            started_at TIMESTAMPTZ NULL,
            finished_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_portfolio_simulation_runs_segment_created
            ON portfolio.simulation_runs (segment, created_at DESC);
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.simulation_nav_daily (
            id BIGSERIAL PRIMARY KEY,
            simulation_run_id BIGINT NOT NULL
                REFERENCES portfolio.simulation_runs(id) ON DELETE CASCADE,
            as_of_date DATE NOT NULL,
            nav DOUBLE PRECISION NOT NULL,
            cash DOUBLE PRECISION NOT NULL,
            gross_exposure DOUBLE PRECISION NOT NULL,
            cash_weight DOUBLE PRECISION NOT NULL,
            peak_nav DOUBLE PRECISION NOT NULL,
            drawdown DOUBLE PRECISION NOT NULL,
            CONSTRAINT uq_portfolio_sim_nav_daily UNIQUE (simulation_run_id, as_of_date)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.simulation_positions_daily (
            id BIGSERIAL PRIMARY KEY,
            simulation_run_id BIGINT NOT NULL
                REFERENCES portfolio.simulation_runs(id) ON DELETE CASCADE,
            as_of_date DATE NOT NULL,
            instrument_id BIGINT NOT NULL,
            ticker TEXT NOT NULL,
            quantity DOUBLE PRECISION NOT NULL,
            market_price DOUBLE PRECISION NULL,
            market_value DOUBLE PRECISION NULL,
            weight DOUBLE PRECISION NULL,
            CONSTRAINT uq_portfolio_sim_positions_daily
                UNIQUE (simulation_run_id, as_of_date, instrument_id)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.simulation_orders (
            id BIGSERIAL PRIMARY KEY,
            simulation_run_id BIGINT NOT NULL
                REFERENCES portfolio.simulation_runs(id) ON DELETE CASCADE,
            decision_date DATE NOT NULL,
            execution_date DATE NOT NULL,
            instrument_id BIGINT NOT NULL,
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            target_weight DOUBLE PRECISION NOT NULL,
            target_notional DOUBLE PRECISION NOT NULL,
            quantity DOUBLE PRECISION NOT NULL,
            reason TEXT NULL,
            prediction_date DATE NULL,
            predicted_return_20d DOUBLE PRECISION NULL,
            rank INTEGER NULL,
            policy_name TEXT NULL,
            fold_id TEXT NULL,
            metadata JSONB NULL
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.simulation_fills (
            id BIGSERIAL PRIMARY KEY,
            simulation_run_id BIGINT NOT NULL
                REFERENCES portfolio.simulation_runs(id) ON DELETE CASCADE,
            execution_date DATE NOT NULL,
            decision_date DATE NULL,
            instrument_id BIGINT NOT NULL,
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity DOUBLE PRECISION NOT NULL,
            raw_open DOUBLE PRECISION NOT NULL,
            fill_price DOUBLE PRECISION NOT NULL,
            notional DOUBLE PRECISION NOT NULL,
            commission DOUBLE PRECISION NOT NULL,
            slippage_cost DOUBLE PRECISION NOT NULL,
            metadata JSONB NULL
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.simulation_ca_events (
            id BIGSERIAL PRIMARY KEY,
            simulation_run_id BIGINT NOT NULL
                REFERENCES portfolio.simulation_runs(id) ON DELETE CASCADE,
            event_date DATE NOT NULL,
            instrument_id BIGINT NOT NULL,
            ticker TEXT NOT NULL,
            event_type TEXT NOT NULL,
            factor TEXT NOT NULL,
            quantity_before DOUBLE PRECISION NOT NULL,
            quantity_after DOUBLE PRECISION NOT NULL
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS portfolio.simulation_ca_events")
    op.execute("DROP TABLE IF EXISTS portfolio.simulation_fills")
    op.execute("DROP TABLE IF EXISTS portfolio.simulation_orders")
    op.execute("DROP TABLE IF EXISTS portfolio.simulation_positions_daily")
    op.execute("DROP TABLE IF EXISTS portfolio.simulation_nav_daily")
    op.execute("DROP TABLE IF EXISTS portfolio.simulation_runs")
    op.execute("DROP TABLE IF EXISTS portfolio.simulation_specs")
