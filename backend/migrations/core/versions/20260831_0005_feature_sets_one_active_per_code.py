"""Enforce at most one active feature set version per code.

Revision ID: 20260831_0005
Revises: 20260831_0004
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260831_0005"
down_revision: str | None = "20260831_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_analytics_feature_sets_one_active_per_code
            ON analytics.feature_sets (code)
            WHERE is_active = TRUE;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS analytics.uq_analytics_feature_sets_one_active_per_code")
