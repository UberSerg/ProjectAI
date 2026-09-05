"""Investment Foundation V0 fixed-income storage.

Revision ID: 20260905_0019
Revises: 20260905_0018
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260905_0019"
down_revision: str | None = "20260905_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS investment")
    op.execute(
        """
        CREATE TABLE investment.bond_terms (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
            bond_type TEXT NOT NULL,
            nominal NUMERIC(20,6),
            currency TEXT,
            coupon_type TEXT,
            coupon_rate NUMERIC(12,8),
            issue_date DATE,
            maturity_date DATE,
            lot_size BIGINT,
            support_status TEXT NOT NULL DEFAULT 'RESEARCH_ONLY',
            credit_quality_status TEXT NOT NULL DEFAULT 'UNKNOWN',
            known_at DATE NOT NULL,
            source TEXT NOT NULL,
            raw_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_investment_bond_terms_instrument UNIQUE (instrument_id),
            CONSTRAINT ck_investment_bond_type
                CHECK (bond_type IN ('Government','Corporate','Municipal')),
            CONSTRAINT ck_investment_bond_support
                CHECK (support_status IN ('SUPPORTED','RESEARCH_ONLY','UNSUPPORTED')),
            CONSTRAINT ck_investment_credit_quality
                CHECK (credit_quality_status IN ('UNKNOWN','OBSERVED'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE investment.bond_cashflows (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
            cashflow_date DATE NOT NULL,
            cashflow_type TEXT NOT NULL,
            amount NUMERIC(20,6),
            currency TEXT,
            known_at DATE NOT NULL,
            source TEXT NOT NULL,
            raw_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_investment_bond_cashflows
                UNIQUE (instrument_id,cashflow_date,cashflow_type,source),
            CONSTRAINT ck_investment_cashflow_type
                CHECK (cashflow_type IN ('COUPON','AMORTIZATION','REDEMPTION','OFFER'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE investment.bond_market_snapshots (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
            as_of DATE NOT NULL,
            clean_price_percent NUMERIC(12,6),
            accrued_interest NUMERIC(20,6),
            yield_value NUMERIC(12,8),
            source TEXT NOT NULL,
            observed_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_investment_bond_market_snapshot UNIQUE (instrument_id,as_of,source)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_investment_bond_cashflows_date "
        "ON investment.bond_cashflows (instrument_id,cashflow_date)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS investment.bond_market_snapshots")
    op.execute("DROP TABLE IF EXISTS investment.bond_cashflows")
    op.execute("DROP TABLE IF EXISTS investment.bond_terms")
    op.execute("DROP SCHEMA IF EXISTS investment")
