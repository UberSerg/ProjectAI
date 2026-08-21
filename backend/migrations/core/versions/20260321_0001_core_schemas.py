"""Create core domain schemas.

Revision ID: 20260321_0001
Revises:
Create Date: 2026-03-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260321_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = ("market", "analytics", "portfolio", "learning", "system")


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS system.schema_meta (
            id SERIAL PRIMARY KEY,
            key TEXT NOT NULL UNIQUE,
            value TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO system.schema_meta (key, value)
        VALUES ('platform', 'projectai-core')
        ON CONFLICT (key) DO NOTHING
        """
    )
    # Future workflow tracking foundation (no investment jobs yet)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS system.workflows (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS system.workflow_steps (
            id BIGSERIAL PRIMARY KEY,
            workflow_id BIGINT NOT NULL REFERENCES system.workflows(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Model registry foundation
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning.model_registry (
            id BIGSERIAL PRIMARY KEY,
            model_name TEXT NOT NULL,
            model_version TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
            training_dataset TEXT,
            metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'candidate',
            UNIQUE (model_name, model_version)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS learning.model_registry")
    op.execute("DROP TABLE IF EXISTS system.workflow_steps")
    op.execute("DROP TABLE IF EXISTS system.workflows")
    op.execute("DROP TABLE IF EXISTS system.schema_meta")
    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
