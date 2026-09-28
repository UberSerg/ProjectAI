"""Multi-Portfolio V2 — lifecycle + wipe synthetic primary book.

Revision ID: 20260928_0025
Revises: 20260927_0024

- Clears disposable Manual/Personal user portfolio rows (ops → positions → portfolios).
- Sets lifecycle default to DRAFT (column ``status``).
- Adds case-insensitive unique name for non-test portfolios.
- Does NOT touch market / shadow / learning / candidate data.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260928_0025"
down_revision: str | None = "20260927_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS portfolio")

    # Dependency-safe wipe of user (and leftover test) manual books only.
    # CASCADE on FKs also clears children if portfolio rows are deleted first,
    # but we delete children explicitly for clarity and auditability.
    op.execute("DELETE FROM portfolio.personal_operations")
    op.execute("DELETE FROM portfolio.manual_positions")
    op.execute("DELETE FROM portfolio.manual_portfolios")

    op.execute(
        """
        ALTER TABLE portfolio.manual_portfolios
            ALTER COLUMN status SET DEFAULT 'DRAFT'
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_manual_portfolios_name_ci_user
        ON portfolio.manual_portfolios (lower(btrim(name)))
        WHERE is_test = FALSE
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS portfolio.uq_manual_portfolios_name_ci_user")
    op.execute(
        """
        ALTER TABLE portfolio.manual_portfolios
            ALTER COLUMN status SET DEFAULT 'ACTIVE'
        """
    )
