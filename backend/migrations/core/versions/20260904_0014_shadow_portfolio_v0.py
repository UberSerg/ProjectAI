"""Shadow Portfolio V0 persistence.

Revision ID: 20260904_0014
Revises: 20260904_0013
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260904_0014"
down_revision: str | None = "20260904_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.shadow_portfolio_specs (
            id BIGSERIAL PRIMARY KEY,
            experiment_group TEXT NOT NULL,
            name TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT 'v0',
            config_hash TEXT NOT NULL,
            candidate_name TEXT NOT NULL,
            candidate_version TEXT NOT NULL,
            candidate_config_hash TEXT NOT NULL,
            dataset_values_hash TEXT NULL,
            policy_name TEXT NOT NULL,
            risk_name TEXT NOT NULL,
            entry_quantile DOUBLE PRECISION NOT NULL DEFAULT 0.20,
            exit_quantile DOUBLE PRECISION NOT NULL DEFAULT 0.35,
            min_trade_weight_delta DOUBLE PRECISION NOT NULL DEFAULT 0.02,
            max_single_weight DOUBLE PRECISION NOT NULL DEFAULT 0.20,
            dd_trigger DOUBLE PRECISION NULL,
            dd_recovery DOUBLE PRECISION NULL,
            dd_risk_off_gross DOUBLE PRECISION NULL,
            dd_normal_gross DOUBLE PRECISION NULL,
            initial_capital DOUBLE PRECISION NOT NULL DEFAULT 1000000,
            commission_bps DOUBLE PRECISION NOT NULL DEFAULT 0,
            slippage_bps DOUBLE PRECISION NOT NULL DEFAULT 0,
            fractional_shares BOOLEAN NOT NULL DEFAULT TRUE,
            dividend_cash BOOLEAN NOT NULL DEFAULT FALSE,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_shadow_portfolio_specs_config_hash UNIQUE (config_hash),
            CONSTRAINT uq_shadow_portfolio_specs_name UNIQUE (name)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.shadow_portfolios (
            id BIGSERIAL PRIMARY KEY,
            spec_id BIGINT NOT NULL
                REFERENCES portfolio.shadow_portfolio_specs(id),
            status TEXT NOT NULL DEFAULT 'INITIALIZED',
            activated_at TIMESTAMPTZ NOT NULL,
            first_forward_batch_id BIGINT NULL,
            first_forward_as_of_date DATE NULL,
            cash DOUBLE PRECISION NOT NULL,
            peak_nav DOUBLE PRECISION NOT NULL,
            exposure_cap DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            risk_mode TEXT NOT NULL DEFAULT 'normal',
            last_processed_market_date DATE NULL,
            last_processed_prediction_batch_id BIGINT NULL,
            last_decision_iso_week TEXT NULL,
            last_decision_id BIGINT NULL,
            positions JSONB NOT NULL DEFAULT '{}'::jsonb,
            provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
            warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_shadow_portfolios_spec UNIQUE (spec_id)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.shadow_decisions (
            id BIGSERIAL PRIMARY KEY,
            portfolio_id BIGINT NOT NULL
                REFERENCES portfolio.shadow_portfolios(id) ON DELETE CASCADE,
            forward_batch_id BIGINT NOT NULL,
            signal_as_of_date DATE NOT NULL,
            signal_generated_at TIMESTAMPTZ NOT NULL,
            decision_at TIMESTAMPTZ NOT NULL,
            iso_week TEXT NOT NULL,
            policy_name TEXT NOT NULL,
            risk_name TEXT NOT NULL,
            risk_mode TEXT NOT NULL,
            exposure_cap DOUBLE PRECISION NOT NULL,
            targets JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_shadow_decisions_portfolio_week UNIQUE (portfolio_id, iso_week)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.shadow_orders (
            id BIGSERIAL PRIMARY KEY,
            portfolio_id BIGINT NOT NULL
                REFERENCES portfolio.shadow_portfolios(id) ON DELETE CASCADE,
            decision_id BIGINT NOT NULL
                REFERENCES portfolio.shadow_decisions(id) ON DELETE CASCADE,
            instrument_id BIGINT NOT NULL,
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            target_weight DOUBLE PRECISION NOT NULL,
            target_notional DOUBLE PRECISION NOT NULL,
            quantity DOUBLE PRECISION NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            predicted_return_20d DOUBLE PRECISION NULL,
            rank INTEGER NULL,
            eligible_count INTEGER NULL,
            decision_at TIMESTAMPTZ NOT NULL,
            min_execution_date DATE NOT NULL,
            execution_date DATE NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_shadow_orders_portfolio_status
            ON portfolio.shadow_orders (portfolio_id, status);
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.shadow_fills (
            id BIGSERIAL PRIMARY KEY,
            portfolio_id BIGINT NOT NULL
                REFERENCES portfolio.shadow_portfolios(id) ON DELETE CASCADE,
            order_id BIGINT NOT NULL
                REFERENCES portfolio.shadow_orders(id) ON DELETE CASCADE,
            instrument_id BIGINT NOT NULL,
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity DOUBLE PRECISION NOT NULL,
            raw_open DOUBLE PRECISION NOT NULL,
            fill_price DOUBLE PRECISION NOT NULL,
            notional DOUBLE PRECISION NOT NULL,
            commission DOUBLE PRECISION NOT NULL DEFAULT 0,
            slippage_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
            execution_date DATE NOT NULL,
            decision_at TIMESTAMPTZ NOT NULL,
            filled_at TIMESTAMPTZ NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_shadow_fills_order UNIQUE (order_id)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.shadow_nav_daily (
            id BIGSERIAL PRIMARY KEY,
            portfolio_id BIGINT NOT NULL
                REFERENCES portfolio.shadow_portfolios(id) ON DELETE CASCADE,
            as_of_date DATE NOT NULL,
            cash DOUBLE PRECISION NOT NULL,
            market_value DOUBLE PRECISION NOT NULL,
            nav DOUBLE PRECISION NOT NULL,
            gross_exposure DOUBLE PRECISION NOT NULL,
            drawdown DOUBLE PRECISION NOT NULL,
            peak_nav DOUBLE PRECISION NOT NULL,
            position_count INTEGER NOT NULL,
            benchmark_value DOUBLE PRECISION NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_shadow_nav_daily UNIQUE (portfolio_id, as_of_date)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.shadow_risk_events (
            id BIGSERIAL PRIMARY KEY,
            portfolio_id BIGINT NOT NULL
                REFERENCES portfolio.shadow_portfolios(id) ON DELETE CASCADE,
            as_of_date DATE NOT NULL,
            nav DOUBLE PRECISION NOT NULL,
            running_peak DOUBLE PRECISION NOT NULL,
            drawdown DOUBLE PRECISION NOT NULL,
            previous_mode TEXT NOT NULL,
            new_mode TEXT NOT NULL,
            previous_exposure_cap DOUBLE PRECISION NOT NULL,
            new_exposure_cap DOUBLE PRECISION NOT NULL,
            reason TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS portfolio.shadow_risk_events;")
    op.execute("DROP TABLE IF EXISTS portfolio.shadow_nav_daily;")
    op.execute("DROP TABLE IF EXISTS portfolio.shadow_fills;")
    op.execute("DROP TABLE IF EXISTS portfolio.shadow_orders;")
    op.execute("DROP TABLE IF EXISTS portfolio.shadow_decisions;")
    op.execute("DROP TABLE IF EXISTS portfolio.shadow_portfolios;")
    op.execute("DROP TABLE IF EXISTS portfolio.shadow_portfolio_specs;")
