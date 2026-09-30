"""Personal Decision Memory V1 (schema memory, Memory DB only).

Immutable snapshots of Daily Personal Decision recommendations, frozen price
baselines, advisory operation links (no cross-DB FK) and forward outcomes.

Does not touch the placeholder ``memory.decisions`` family from 20260321_0001.

Revision ID: 20260930_0002
Revises: 20260321_0001
Create Date: 2026-09-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260930_0002"
down_revision: str | None = "20260321_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS memory")

    op.execute(
        """
        CREATE TABLE memory.personal_decision_records (
            id BIGSERIAL PRIMARY KEY,
            portfolio_id BIGINT NOT NULL,
            portfolio_name_snapshot TEXT NOT NULL,
            captured_at TIMESTAMPTZ NOT NULL,
            decision_as_of DATE,
            engine_version TEXT NOT NULL,
            new_cash_rub NUMERIC(20, 4),
            decision_payload JSONB NOT NULL,
            canonical_hash TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_fingerprint TEXT NOT NULL,
            candidate_provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
            broker_fee_provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_personal_decision_records_idempotency
                UNIQUE (portfolio_id, idempotency_key)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_personal_decision_records_portfolio_captured
        ON memory.personal_decision_records (portfolio_id, captured_at DESC, id DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE memory.personal_decision_actions (
            id BIGSERIAL PRIMARY KEY,
            decision_record_id BIGINT NOT NULL
                REFERENCES memory.personal_decision_records(id) ON DELETE CASCADE,
            original_action_id TEXT NOT NULL,
            action TEXT NOT NULL,
            priority TEXT,
            symbol TEXT,
            instrument_id BIGINT,
            reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
            target_weight NUMERIC,
            current_weight NUMERIC,
            lots_delta NUMERIC,
            units_delta NUMERIC,
            estimated_notional NUMERIC,
            limitations JSONB NOT NULL DEFAULT '[]'::jsonb,
            action_payload JSONB NOT NULL,
            baseline_price NUMERIC,
            baseline_market_date DATE,
            baseline_price_source TEXT,
            baseline_observed_at TIMESTAMPTZ,
            baseline_status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_personal_decision_actions_baseline_status
                CHECK (baseline_status IN ('AVAILABLE', 'UNAVAILABLE'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_personal_decision_actions_record
        ON memory.personal_decision_actions (decision_record_id)
        """
    )

    op.execute(
        """
        CREATE TABLE memory.personal_decision_operation_links (
            id BIGSERIAL PRIMARY KEY,
            decision_action_id BIGINT NOT NULL
                REFERENCES memory.personal_decision_actions(id) ON DELETE CASCADE,
            portfolio_id BIGINT NOT NULL,
            personal_operation_id BIGINT NOT NULL,
            link_source TEXT NOT NULL DEFAULT 'USER_CONFIRMED',
            linked_at TIMESTAMPTZ NOT NULL,
            unlinked_at TIMESTAMPTZ,
            active BOOLEAN NOT NULL DEFAULT TRUE
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_personal_decision_links_active
        ON memory.personal_decision_operation_links (decision_action_id, personal_operation_id)
        WHERE active
        """
    )
    op.execute(
        """
        CREATE INDEX ix_personal_decision_links_operation
        ON memory.personal_decision_operation_links (portfolio_id, personal_operation_id)
        """
    )

    op.execute(
        """
        CREATE TABLE memory.personal_decision_outcomes (
            id BIGSERIAL PRIMARY KEY,
            decision_action_id BIGINT NOT NULL
                REFERENCES memory.personal_decision_actions(id) ON DELETE CASCADE,
            horizon_sessions INT NOT NULL,
            status TEXT NOT NULL,
            target_session_date DATE,
            observed_session_date DATE,
            baseline_price NUMERIC,
            observed_price NUMERIC,
            return_type TEXT NOT NULL DEFAULT 'PRICE_RETURN',
            forward_return NUMERIC,
            directional_alignment TEXT,
            provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
            refreshed_at TIMESTAMPTZ,
            CONSTRAINT uq_personal_decision_outcomes_action_horizon
                UNIQUE (decision_action_id, horizon_sessions),
            CONSTRAINT ck_personal_decision_outcomes_horizon
                CHECK (horizon_sessions IN (5, 20, 60)),
            CONSTRAINT ck_personal_decision_outcomes_status
                CHECK (status IN ('PENDING', 'READY', 'DATA_UNAVAILABLE', 'BASELINE_UNAVAILABLE')),
            CONSTRAINT ck_personal_decision_outcomes_alignment
                CHECK (directional_alignment IS NULL
                       OR directional_alignment IN ('ALIGNED', 'NOT_ALIGNED'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_personal_decision_outcomes_status
        ON memory.personal_decision_outcomes (status)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memory.personal_decision_outcomes")
    op.execute("DROP TABLE IF EXISTS memory.personal_decision_operation_links")
    op.execute("DROP TABLE IF EXISTS memory.personal_decision_actions")
    op.execute("DROP TABLE IF EXISTS memory.personal_decision_records")
