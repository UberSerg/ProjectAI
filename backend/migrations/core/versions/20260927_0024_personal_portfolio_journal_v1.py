"""Personal Portfolio journal + portfolio metadata.

Revision ID: 20260927_0024
Revises: 20260908_0023

Extends Manual Portfolio with an authoritative operation journal.
Projected cash/positions remain in manual_portfolios / manual_positions.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260927_0024"
down_revision: str | None = "20260908_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS portfolio")

    op.execute(
        """
        ALTER TABLE portfolio.manual_portfolios
            ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'ACTIVE',
            ADD COLUMN IF NOT EXISTS note TEXT,
            ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS total_contributed_rub NUMERIC(20, 6) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS total_withdrawn_rub NUMERIC(20, 6) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS realized_pnl_rub NUMERIC(20, 6) NOT NULL DEFAULT 0
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.personal_operations (
            id BIGSERIAL PRIMARY KEY,
            portfolio_id BIGINT NOT NULL
                REFERENCES portfolio.manual_portfolios(id) ON DELETE CASCADE,
            operation_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            occurred_at TIMESTAMPTZ NOT NULL,
            instrument_id BIGINT
                REFERENCES market.instruments(id) ON DELETE RESTRICT,
            lots NUMERIC(24, 8),
            units NUMERIC(24, 8),
            price NUMERIC(20, 6),
            amount NUMERIC(20, 6),
            commission NUMERIC(20, 6) NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'RUB',
            source TEXT NOT NULL DEFAULT 'MANUAL',
            note TEXT,
            idempotency_key TEXT NOT NULL,
            supersedes_operation_id BIGINT
                REFERENCES portfolio.personal_operations(id) ON DELETE SET NULL,
            correction_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_personal_operations_type CHECK (
                operation_type IN (
                    'DEPOSIT', 'WITHDRAWAL', 'BUY', 'SELL', 'COMMISSION',
                    'OPENING_CASH', 'OPENING_POSITION',
                    'DIVIDEND', 'COUPON', 'TAX', 'AMORTIZATION', 'OTHER_FEE'
                )
            ),
            CONSTRAINT ck_personal_operations_status CHECK (
                status IN ('ACTIVE', 'CANCELLED', 'SUPERSEDED')
            ),
            CONSTRAINT uq_personal_operations_idempotency
                UNIQUE (portfolio_id, idempotency_key)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_personal_operations_portfolio_occurred
            ON portfolio.personal_operations (portfolio_id, occurred_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_personal_operations_portfolio_status
            ON portfolio.personal_operations (portfolio_id, status)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS portfolio.personal_operations")
    op.execute(
        """
        ALTER TABLE portfolio.manual_portfolios
            DROP COLUMN IF EXISTS status,
            DROP COLUMN IF EXISTS note,
            DROP COLUMN IF EXISTS is_test,
            DROP COLUMN IF EXISTS total_contributed_rub,
            DROP COLUMN IF EXISTS total_withdrawn_rub,
            DROP COLUMN IF EXISTS realized_pnl_rub
        """
    )
