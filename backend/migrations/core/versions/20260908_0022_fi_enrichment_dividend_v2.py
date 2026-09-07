"""Fixed Income Enrichment V2: enrichment jobs + research_fi_v1 pin seed.

Revision ID: 20260908_0022
Revises: 20260908_0021

Strategy stability: seed ``research_fi_v1`` from instruments that already have
``investment.bond_terms`` at migration time. Enrichment expands catalog
valuation; Candidate / Opportunity FI pool stays pinned until an explicit
universe version bump.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0022"
down_revision: str | None = "20260908_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS market")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market.instrument_enrichment_jobs (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL
                REFERENCES market.instruments(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            priority INT NOT NULL DEFAULT 3,
            status TEXT NOT NULL DEFAULT 'PENDING',
            attempts INT NOT NULL DEFAULT 0,
            last_error TEXT,
            last_attempted_at TIMESTAMPTZ,
            last_success_at TIMESTAMPTZ,
            next_retry_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_market_instrument_enrichment_jobs_instrument_kind
                UNIQUE (instrument_id, kind)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_enrichment_jobs_queue
            ON market.instrument_enrichment_jobs (
                status, priority ASC, next_retry_at ASC NULLS FIRST, id ASC
            )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_enrichment_jobs_instrument
            ON market.instrument_enrichment_jobs (instrument_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_enrichment_jobs_kind_status
            ON market.instrument_enrichment_jobs (kind, status)
        """
    )

    # Pin strategy FI universe to the CURRENT BondTerm sample only.
    # Do not auto-grow when enrichment later adds more BondTerm rows.
    op.execute(
        """
        INSERT INTO market.universe_memberships (universe_code, instrument_id)
        SELECT 'research_fi_v1', bt.instrument_id
        FROM investment.bond_terms bt
        ON CONFLICT (universe_code, instrument_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM market.universe_memberships WHERE universe_code = 'research_fi_v1'")
    op.execute("DROP INDEX IF EXISTS market.ix_market_enrichment_jobs_kind_status")
    op.execute("DROP INDEX IF EXISTS market.ix_market_enrichment_jobs_instrument")
    op.execute("DROP INDEX IF EXISTS market.ix_market_enrichment_jobs_queue")
    op.execute("DROP TABLE IF EXISTS market.instrument_enrichment_jobs")
