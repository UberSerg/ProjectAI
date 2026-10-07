"""Intelligence Stack V1 schema (additive).

Revision ID: 20261007_0027
Revises: 20260929_0026

Creates intelligence schema for documents, events, snapshots, signals,
committee decisions, knowledge rules, and refresh runs.
Reuses market.candles for intraday bars (timeframe e.g. 60m) — no separate candle table.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20261007_0027"
down_revision: str | None = "20260929_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS intelligence")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence.source_documents (
            id BIGSERIAL PRIMARY KEY,
            document_key TEXT NOT NULL,
            provider TEXT NOT NULL,
            source_type TEXT NOT NULL,
            canonical_url TEXT,
            title TEXT,
            published_at TIMESTAMPTZ,
            observed_at TIMESTAMPTZ NOT NULL,
            known_at TIMESTAMPTZ NOT NULL,
            content_hash TEXT NOT NULL,
            language TEXT,
            issuer_id BIGINT,
            instrument_id BIGINT REFERENCES market.instruments(id) ON DELETE SET NULL,
            mapping_basis TEXT,
            parse_status TEXT NOT NULL DEFAULT 'PENDING',
            raw_text TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            revision INTEGER NOT NULL DEFAULT 1,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_intel_source_documents_key_rev UNIQUE (document_key, revision),
            CONSTRAINT uq_intel_source_documents_hash UNIQUE (provider, content_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_intel_source_documents_known_at "
        "ON intelligence.source_documents (known_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_intel_source_documents_instrument "
        "ON intelligence.source_documents (instrument_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence.extracted_facts (
            id BIGSERIAL PRIMARY KEY,
            source_document_id BIGINT NOT NULL
                REFERENCES intelligence.source_documents(id) ON DELETE CASCADE,
            extractor_version TEXT NOT NULL,
            event_type TEXT NOT NULL,
            materiality TEXT NOT NULL DEFAULT 'UNKNOWN',
            direction TEXT NOT NULL DEFAULT 'UNKNOWN',
            affected_horizon TEXT,
            claim JSONB NOT NULL DEFAULT '{}'::jsonb,
            evidence_fragment TEXT,
            confidence DOUBLE PRECISION,
            status TEXT NOT NULL DEFAULT 'ACCEPTED',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence.intelligence_events (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT REFERENCES market.instruments(id) ON DELETE SET NULL,
            event_type TEXT NOT NULL,
            materiality TEXT NOT NULL DEFAULT 'UNKNOWN',
            direction TEXT NOT NULL DEFAULT 'UNKNOWN',
            title TEXT,
            known_at TIMESTAMPTZ NOT NULL,
            published_at TIMESTAMPTZ,
            observed_at TIMESTAMPTZ,
            source_document_id BIGINT
                REFERENCES intelligence.source_documents(id) ON DELETE SET NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_intel_events_instrument_known "
        "ON intelligence.intelligence_events (instrument_id, known_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence.intraday_feature_snapshots (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL
                REFERENCES market.instruments(id) ON DELETE CASCADE,
            as_of DATE NOT NULL,
            known_at TIMESTAMPTZ NOT NULL,
            interval TEXT NOT NULL DEFAULT '60m',
            coverage_status TEXT NOT NULL,
            features JSONB NOT NULL DEFAULT '{}'::jsonb,
            bars_used INTEGER NOT NULL DEFAULT 0,
            feature_hash TEXT,
            limitations JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_intel_intraday_feat UNIQUE (instrument_id, as_of, interval)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence.fundamental_snapshots (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL
                REFERENCES market.instruments(id) ON DELETE CASCADE,
            as_of DATE NOT NULL,
            known_at TIMESTAMPTZ NOT NULL,
            period_end DATE,
            issuer_kind TEXT NOT NULL DEFAULT 'INDUSTRIAL',
            status TEXT NOT NULL,
            metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            missing_metrics JSONB NOT NULL DEFAULT '[]'::jsonb,
            facts_used JSONB NOT NULL DEFAULT '[]'::jsonb,
            limitations JSONB NOT NULL DEFAULT '[]'::jsonb,
            provider TEXT,
            snapshot_hash TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_intel_fund_snap UNIQUE (instrument_id, as_of, issuer_kind)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence.macro_snapshots (
            id BIGSERIAL PRIMARY KEY,
            as_of DATE NOT NULL,
            known_at TIMESTAMPTZ NOT NULL,
            status TEXT NOT NULL,
            observations JSONB NOT NULL DEFAULT '{}'::jsonb,
            regimes JSONB NOT NULL DEFAULT '{}'::jsonb,
            sources JSONB NOT NULL DEFAULT '[]'::jsonb,
            limitations JSONB NOT NULL DEFAULT '[]'::jsonb,
            snapshot_hash TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_intel_macro_snap UNIQUE (as_of)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence.knowledge_rules (
            id BIGSERIAL PRIMARY KEY,
            rule_id TEXT NOT NULL,
            version TEXT NOT NULL,
            domain TEXT NOT NULL,
            title TEXT NOT NULL,
            principle TEXT NOT NULL,
            applicability JSONB NOT NULL DEFAULT '[]'::jsonb,
            required_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
            contraindications JSONB NOT NULL DEFAULT '[]'::jsonb,
            severity TEXT NOT NULL DEFAULT 'MEDIUM',
            source_reference TEXT,
            source_location TEXT,
            created_from TEXT NOT NULL DEFAULT 'kraken_methodology',
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            body JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_intel_knowledge_rules UNIQUE (rule_id, version)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence.knowledge_rule_evaluations (
            id BIGSERIAL PRIMARY KEY,
            rule_id TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            instrument_id BIGINT REFERENCES market.instruments(id) ON DELETE CASCADE,
            as_of DATE NOT NULL,
            state TEXT NOT NULL,
            why TEXT NOT NULL,
            evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_intel_rule_eval_instrument_asof "
        "ON intelligence.knowledge_rule_evaluations (instrument_id, as_of)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence.signal_outputs (
            id BIGSERIAL PRIMARY KEY,
            model_id TEXT NOT NULL,
            model_version TEXT NOT NULL,
            semantic TEXT NOT NULL,
            instrument_id BIGINT NOT NULL
                REFERENCES market.instruments(id) ON DELETE CASCADE,
            as_of DATE NOT NULL,
            known_at TIMESTAMPTZ,
            horizon TEXT NOT NULL,
            state TEXT NOT NULL,
            score DOUBLE PRECISION,
            confidence DOUBLE PRECISION,
            confidence_semantic TEXT,
            evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
            feature_snapshot_hash TEXT,
            data_freshness TEXT,
            limitations JSONB NOT NULL DEFAULT '[]'::jsonb,
            abstain_reason TEXT,
            model_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_intel_signal_outputs
                UNIQUE (model_id, model_version, instrument_id, as_of, horizon)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence.risk_assessments (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL
                REFERENCES market.instruments(id) ON DELETE CASCADE,
            as_of DATE NOT NULL,
            risk_state TEXT NOT NULL,
            risk_score DOUBLE PRECISION,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_intel_risk_assessments UNIQUE (instrument_id, as_of)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence.committee_decisions (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL
                REFERENCES market.instruments(id) ON DELETE CASCADE,
            as_of DATE NOT NULL,
            advisory_state TEXT NOT NULL,
            confidence DOUBLE PRECISION,
            consensus_strength DOUBLE PRECISION,
            disagreement_score DOUBLE PRECISION,
            committee_policy_version TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_intel_committee_decisions UNIQUE (instrument_id, as_of, committee_policy_version)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence.intelligence_snapshots (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL
                REFERENCES market.instruments(id) ON DELETE CASCADE,
            as_of DATE NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            freshness TEXT,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            payload_hash TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_intel_snapshots UNIQUE (instrument_id, as_of)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence.refresh_runs (
            id BIGSERIAL PRIMARY KEY,
            workflow_key TEXT NOT NULL,
            status TEXT NOT NULL,
            stages JSONB NOT NULL DEFAULT '{}'::jsonb,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            error_message TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS intelligence.refresh_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS intelligence.intelligence_snapshots CASCADE")
    op.execute("DROP TABLE IF EXISTS intelligence.committee_decisions CASCADE")
    op.execute("DROP TABLE IF EXISTS intelligence.risk_assessments CASCADE")
    op.execute("DROP TABLE IF EXISTS intelligence.signal_outputs CASCADE")
    op.execute("DROP TABLE IF EXISTS intelligence.knowledge_rule_evaluations CASCADE")
    op.execute("DROP TABLE IF EXISTS intelligence.knowledge_rules CASCADE")
    op.execute("DROP TABLE IF EXISTS intelligence.macro_snapshots CASCADE")
    op.execute("DROP TABLE IF EXISTS intelligence.fundamental_snapshots CASCADE")
    op.execute("DROP TABLE IF EXISTS intelligence.intraday_feature_snapshots CASCADE")
    op.execute("DROP TABLE IF EXISTS intelligence.intelligence_events CASCADE")
    op.execute("DROP TABLE IF EXISTS intelligence.extracted_facts CASCADE")
    op.execute("DROP TABLE IF EXISTS intelligence.source_documents CASCADE")
    op.execute("DROP SCHEMA IF EXISTS intelligence CASCADE")
