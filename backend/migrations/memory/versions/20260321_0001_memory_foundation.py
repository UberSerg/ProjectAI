"""Enable pgvector and Decision Memory foundation schemas.

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


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SCHEMA IF NOT EXISTS memory")
    # Placeholder tables — business logic / LLM review not implemented yet
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory.decisions (
            id BIGSERIAL PRIMARY KEY,
            ticker TEXT,
            decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory.decision_factors (
            id BIGSERIAL PRIMARY KEY,
            decision_id BIGINT NOT NULL REFERENCES memory.decisions(id) ON DELETE CASCADE,
            factor_key TEXT NOT NULL,
            factor_value JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory.decision_outcomes (
            id BIGSERIAL PRIMARY KEY,
            decision_id BIGINT NOT NULL REFERENCES memory.decisions(id) ON DELETE CASCADE,
            outcome JSONB NOT NULL DEFAULT '{}'::jsonb,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory.decision_reviews (
            id BIGSERIAL PRIMARY KEY,
            decision_id BIGINT NOT NULL REFERENCES memory.decisions(id) ON DELETE CASCADE,
            review JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory.embeddings (
            id BIGSERIAL PRIMARY KEY,
            decision_id BIGINT REFERENCES memory.decisions(id) ON DELETE SET NULL,
            content_ref TEXT,
            embedding vector(1536),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memory.embeddings")
    op.execute("DROP TABLE IF EXISTS memory.decision_reviews")
    op.execute("DROP TABLE IF EXISTS memory.decision_outcomes")
    op.execute("DROP TABLE IF EXISTS memory.decision_factors")
    op.execute("DROP TABLE IF EXISTS memory.decisions")
    op.execute("DROP SCHEMA IF EXISTS memory CASCADE")
    op.execute("DROP EXTENSION IF EXISTS vector")
