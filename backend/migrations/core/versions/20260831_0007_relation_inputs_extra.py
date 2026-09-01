"""Rename relation_inputs.metadata to extra (avoid SQLAlchemy MetaData clash).

Revision ID: 20260831_0007
Revises: 20260831_0006
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260831_0007"
down_revision: str | None = "20260831_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'analytics'
                  AND table_name = 'relation_inputs'
                  AND column_name = 'metadata'
            ) THEN
                ALTER TABLE analytics.relation_inputs RENAME COLUMN metadata TO extra;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'analytics'
                  AND table_name = 'relation_inputs'
                  AND column_name = 'extra'
            ) THEN
                ALTER TABLE analytics.relation_inputs RENAME COLUMN extra TO metadata;
            END IF;
        END $$;
        """
    )
