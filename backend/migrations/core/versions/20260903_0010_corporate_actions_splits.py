"""Corporate actions: known_at, external_id, idempotent identity for SPLIT ingest.

Revision ID: 20260903_0010
Revises: 20260901_0009
Create Date: 2026-09-03

event_date remains the economic effective date (MOEX splits.tradedate).
known_at is nullable — official splits feed has no announcement timestamp.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260903_0010"
down_revision: str | None = "20260901_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE market.corporate_actions
            ADD COLUMN IF NOT EXISTS known_at TIMESTAMPTZ NULL;
        """
    )
    op.execute(
        """
        ALTER TABLE market.corporate_actions
            ADD COLUMN IF NOT EXISTS external_id TEXT NULL;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_market_corporate_actions_identity
            ON market.corporate_actions (
                instrument_id,
                event_type,
                event_date,
                source,
                COALESCE(external_id, '')
            );
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS market.uq_market_corporate_actions_identity")
    op.execute("ALTER TABLE market.corporate_actions DROP COLUMN IF EXISTS external_id")
    op.execute("ALTER TABLE market.corporate_actions DROP COLUMN IF EXISTS known_at")
