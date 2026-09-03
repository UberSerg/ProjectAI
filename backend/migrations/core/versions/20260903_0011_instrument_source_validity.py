"""Instrument source validity windows (H2).

Revision ID: 20260903_0011
Revises: 20260903_0010
Create Date: 2026-09-03

valid_from / valid_to are nullable DATEs.
Existing rows stay current/open-ended with unknown start (both NULL).
Uniqueness (source, external_id, board) is unchanged: same SECID+board
cannot occupy two disjoint periods in V0.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260903_0011"
down_revision: str | None = "20260903_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE market.instrument_sources
            ADD COLUMN IF NOT EXISTS valid_from DATE NULL;
        """
    )
    op.execute(
        """
        ALTER TABLE market.instrument_sources
            ADD COLUMN IF NOT EXISTS valid_to DATE NULL;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_market_instrument_sources_as_of
            ON market.instrument_sources (instrument_id, source, valid_from, valid_to);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS market.ix_market_instrument_sources_as_of")
    op.execute("ALTER TABLE market.instrument_sources DROP COLUMN IF EXISTS valid_to")
    op.execute("ALTER TABLE market.instrument_sources DROP COLUMN IF EXISTS valid_from")
