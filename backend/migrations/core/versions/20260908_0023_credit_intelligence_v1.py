"""Credit Intelligence V1: agencies, rating observations, sync jobs.

Revision ID: 20260908_0023
Revises: 20260908_0022

Schema choice: ``investment`` — bond/issue credit observations sit next to
bond_terms / cashflows. Issuer identity remains in ``fundamentals.issuers``;
this store holds agency rating facts for ISSUER|ISSUE subjects without
inventing ratings when the provider is NOT_READY.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0023"
down_revision: str | None = "20260908_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS investment")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS investment.credit_agencies (
            id BIGSERIAL PRIMARY KEY,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            country TEXT,
            scale_notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_investment_credit_agencies_code UNIQUE (code)
        )
        """
    )

    op.execute(
        """
        INSERT INTO investment.credit_agencies (code, name, country, scale_notes)
        VALUES
            ('ACRA', 'АКРА', 'RU', 'Russian national scale; not interchangeable with Expert RA without mapping'),
            ('EXPERT_RA', 'Эксперт РА', 'RU', 'Russian national scale; not interchangeable with ACRA without mapping'),
            ('NCR', 'НКР', 'RU', 'Russian national scale'),
            ('MOEX_CCI', 'MOEX CCI', 'RU', 'Requires MicexPassport / paid CCI subscription')
        ON CONFLICT (code) DO NOTHING
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS investment.credit_rating_observations (
            id BIGSERIAL PRIMARY KEY,
            subject_type TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            instrument_id BIGINT REFERENCES market.instruments(id) ON DELETE SET NULL,
            issuer_id BIGINT,
            agency_code TEXT NOT NULL
                REFERENCES investment.credit_agencies(code),
            rating_raw TEXT,
            scale TEXT,
            outlook TEXT,
            action_type TEXT,
            action_date DATE,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            known_at DATE,
            known_at_quality TEXT NOT NULL DEFAULT 'UNKNOWN',
            source TEXT NOT NULL,
            source_record_id TEXT,
            mapping_quality TEXT NOT NULL DEFAULT 'UNMAPPED',
            status TEXT NOT NULL DEFAULT 'UNKNOWN',
            availability_status TEXT NOT NULL DEFAULT 'SOURCE_NOT_READY',
            raw_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_credit_obs_subject_type
                CHECK (subject_type IN ('ISSUER', 'ISSUE')),
            CONSTRAINT ck_credit_obs_status
                CHECK (status IN ('CURRENT', 'WITHDRAWN', 'UNKNOWN')),
            CONSTRAINT ck_credit_obs_availability
                CHECK (availability_status IN (
                    'SOURCE_NOT_READY',
                    'NO_RATING_FOUND',
                    'MAPPING_FAILED',
                    'CURRENT_RATING_AVAILABLE',
                    'GOVERNMENT_RUSSIAN_FEDERAL'
                ))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_credit_obs_subject
            ON investment.credit_rating_observations (subject_type, subject_key)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_credit_obs_instrument
            ON investment.credit_rating_observations (instrument_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_credit_obs_agency_status
            ON investment.credit_rating_observations (agency_code, status, availability_status)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_obs_source_record
            ON investment.credit_rating_observations (source, source_record_id)
            WHERE source_record_id IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS investment.credit_sync_jobs (
            id BIGSERIAL PRIMARY KEY,
            subject_type TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            agency_code TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING',
            attempts INT NOT NULL DEFAULT 0,
            last_error TEXT,
            last_attempted_at TIMESTAMPTZ,
            last_success_at TIMESTAMPTZ,
            next_retry_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_credit_sync_subject_type
                CHECK (subject_type IN ('ISSUER', 'ISSUE')),
            CONSTRAINT ck_credit_sync_status
                CHECK (status IN (
                    'PENDING', 'RUNNING', 'SUCCESS', 'FAILED',
                    'NO_DATA', 'SOURCE_NOT_READY', 'SKIPPED'
                )),
            CONSTRAINT uq_credit_sync_jobs_subject_agency
                UNIQUE (subject_type, subject_key, agency_code)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_credit_sync_jobs_queue
            ON investment.credit_sync_jobs (
                status, next_retry_at ASC NULLS FIRST, id ASC
            )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS investment.ix_credit_sync_jobs_queue")
    op.execute("DROP TABLE IF EXISTS investment.credit_sync_jobs")
    op.execute("DROP INDEX IF EXISTS investment.uq_credit_obs_source_record")
    op.execute("DROP INDEX IF EXISTS investment.ix_credit_obs_agency_status")
    op.execute("DROP INDEX IF EXISTS investment.ix_credit_obs_instrument")
    op.execute("DROP INDEX IF EXISTS investment.ix_credit_obs_subject")
    op.execute("DROP TABLE IF EXISTS investment.credit_rating_observations")
    op.execute("DROP TABLE IF EXISTS investment.credit_agencies")
