"""Append-only prospective intelligence captures.

Revision ID: 20261012_0028
Revises: 20261007_0027

A later refresh inserts a new row. It does not update an older capture.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20261012_0028"
down_revision: str | None = "20261007_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence.prospective_captures (
            id BIGSERIAL PRIMARY KEY,
            captured_at TIMESTAMPTZ NOT NULL,
            instrument_id BIGINT NOT NULL
                REFERENCES market.instruments(id) ON DELETE CASCADE,
            as_of DATE NOT NULL,
            payload JSONB NOT NULL,
            payload_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_intel_prospective_captures_instrument
        ON intelligence.prospective_captures (instrument_id, captured_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS intelligence.ix_intel_prospective_captures_instrument")
    op.execute("DROP TABLE IF EXISTS intelligence.prospective_captures")
