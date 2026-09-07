"""Portfolio Candidate V1 snapshot storage.

Revision ID: 20260907_0020
Revises: 20260905_0019
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260907_0020"
down_revision: str | None = "20260905_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS investment")
    op.execute(
        """
        CREATE TABLE investment.portfolio_candidates (
            id BIGSERIAL PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            as_of DATE,
            generated_at TIMESTAMPTZ NOT NULL,
            capital NUMERIC(20,6) NOT NULL,
            currency TEXT NOT NULL DEFAULT 'RUB',
            status TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT 'PORTFOLIO_CANDIDATE_V1',
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_investment_portfolio_candidate_id UNIQUE (candidate_id),
            CONSTRAINT ck_investment_portfolio_candidate_status
                CHECK (status IN (
                    'READY_FOR_RESEARCH',
                    'PARTIAL',
                    'INSUFFICIENT_DATA',
                    'BLOCKED_BY_RISK',
                    'STALE'
                ))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_investment_portfolio_candidates_generated
            ON investment.portfolio_candidates (generated_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS investment.portfolio_candidates")
