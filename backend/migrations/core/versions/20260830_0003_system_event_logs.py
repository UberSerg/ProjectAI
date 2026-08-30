"""Add system.event_logs for same-day technology journal.

Revision ID: 20260830_0003
Revises: 20260821_0002
Create Date: 2026-08-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260830_0003"
down_revision: str | None = "20260821_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS system")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS system.event_logs (
            id BIGSERIAL PRIMARY KEY,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            level TEXT NOT NULL,
            component TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            details JSONB,
            workflow_id BIGINT,
            batch_id TEXT,
            instrument_id BIGINT,
            trace_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_event_logs_level CHECK (level IN ('INFO', 'WARNING', 'ERROR'))
        );

        CREATE INDEX IF NOT EXISTS ix_event_logs_timestamp
            ON system.event_logs (timestamp DESC);
        CREATE INDEX IF NOT EXISTS ix_event_logs_level_timestamp
            ON system.event_logs (level, timestamp DESC);
        CREATE INDEX IF NOT EXISTS ix_event_logs_workflow_id
            ON system.event_logs (workflow_id);
        CREATE INDEX IF NOT EXISTS ix_event_logs_trace_id
            ON system.event_logs (trace_id);
        CREATE INDEX IF NOT EXISTS ix_event_logs_component_timestamp
            ON system.event_logs (component, timestamp DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS system.event_logs")
