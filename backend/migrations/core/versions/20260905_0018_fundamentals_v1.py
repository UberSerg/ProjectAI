"""Fundamental & Event Intelligence V1 — data foundation (schema fundamentals).

Revision ID: 20260905_0018
Revises: 20260905_0017
Create Date: 2026-09-05

Storage only. No report/dividend provider exists yet: a live source audit rejected
MOEX ISS `/iss/securities/{SECID}/dividends.json` (returns the security description,
not a dividend table) and e-disclosure.ru (HTTP 403). Only MOEX ISS issuer identity
and the existing market.corporate_actions SPLIT feed can populate these tables today.

`known_at` is mandatory on every knowledge-bearing table (reports, dividends, events):
a row must declare when the information became available, separately from the economic
date (`period_end`, `record_date`, `effective_date`). Rows whose availability date is
unknown are not written at all rather than backdated.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260905_0018"
down_revision: str | None = "20260905_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS fundamentals;")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals.issuers (
            id BIGSERIAL PRIMARY KEY,
            moex_emitent_id BIGINT NULL,
            inn TEXT NULL,
            okpo TEXT NULL,
            title TEXT NOT NULL,
            title_en TEXT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_fundamentals_issuers_moex_emitent UNIQUE (moex_emitent_id)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fundamentals_issuers_inn
            ON fundamentals.issuers (inn);
        """
    )

    # issuer_id stays nullable so an UNMAPPED / AMBIGUOUS instrument can be recorded
    # honestly instead of being attached to an invented issuer.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals.security_issuer_mappings (
            id BIGSERIAL PRIMARY KEY,
            instrument_id BIGINT NOT NULL
                REFERENCES market.instruments(id) ON DELETE CASCADE,
            issuer_id BIGINT NULL
                REFERENCES fundamentals.issuers(id) ON DELETE SET NULL,
            valid_from DATE NULL,
            valid_to DATE NULL,
            source TEXT NOT NULL,
            external_secid TEXT NULL,
            isin TEXT NULL,
            mapping_status TEXT NOT NULL DEFAULT 'UNMAPPED',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_fundamentals_mapping_status CHECK (
                mapping_status IN ('MAPPED', 'AMBIGUOUS', 'UNMAPPED')
            ),
            CONSTRAINT ck_fundamentals_mapping_window CHECK (
                valid_from IS NULL OR valid_to IS NULL OR valid_from < valid_to
            )
        );
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_fundamentals_security_issuer_mappings
            ON fundamentals.security_issuer_mappings (
                instrument_id,
                source,
                COALESCE(external_secid, ''),
                COALESCE(valid_from, DATE '0001-01-01')
            );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fundamentals_mappings_issuer
            ON fundamentals.security_issuer_mappings (issuer_id);
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals.source_documents (
            id BIGSERIAL PRIMARY KEY,
            provider TEXT NOT NULL,
            source_url TEXT NULL,
            provider_document_id TEXT NULL,
            retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            published_at TIMESTAMPTZ NULL,
            content_hash TEXT NULL,
            mime_type TEXT NULL,
            storage_ref TEXT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_fundamentals_source_documents_identity
            ON fundamentals.source_documents (
                provider,
                COALESCE(provider_document_id, ''),
                COALESCE(content_hash, '')
            );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals.metric_registry (
            code TEXT PRIMARY KEY,
            title_ru TEXT NOT NULL,
            title_en TEXT NOT NULL,
            description TEXT NULL,
            applies_to_banks BOOLEAN NOT NULL DEFAULT TRUE,
            status TEXT NOT NULL DEFAULT 'SUPPORTED',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_fundamentals_metric_status CHECK (
                status IN ('SUPPORTED', 'AMBIGUOUS', 'UNSUPPORTED')
            )
        );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals.financial_reports (
            id BIGSERIAL PRIMARY KEY,
            issuer_id BIGINT NOT NULL
                REFERENCES fundamentals.issuers(id) ON DELETE CASCADE,
            reporting_standard TEXT NOT NULL,
            period_type TEXT NOT NULL,
            period_start DATE NULL,
            period_end DATE NOT NULL,
            published_at TIMESTAMPTZ NULL,
            known_at DATE NOT NULL,
            known_at_precision TEXT NOT NULL DEFAULT 'DATE',
            source TEXT NOT NULL,
            source_document_id BIGINT NULL
                REFERENCES fundamentals.source_documents(id) ON DELETE SET NULL,
            report_version INTEGER NOT NULL DEFAULT 1,
            is_restatement BOOLEAN NOT NULL DEFAULT FALSE,
            currency TEXT NULL,
            unit_scale TEXT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_fundamentals_financial_reports UNIQUE (
                issuer_id, reporting_standard, period_type, period_end, report_version, source
            ),
            CONSTRAINT ck_fundamentals_reporting_standard CHECK (
                reporting_standard IN ('IFRS', 'RAS', 'OTHER')
            ),
            CONSTRAINT ck_fundamentals_known_at_precision CHECK (
                known_at_precision IN ('DATE', 'TIMESTAMP')
            ),
            CONSTRAINT ck_fundamentals_report_period CHECK (
                period_start IS NULL OR period_start <= period_end
            )
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fundamentals_financial_reports_pit
            ON fundamentals.financial_reports (issuer_id, known_at, period_end DESC);
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals.financial_facts (
            id BIGSERIAL PRIMARY KEY,
            report_id BIGINT NOT NULL
                REFERENCES fundamentals.financial_reports(id) ON DELETE CASCADE,
            metric_code TEXT NOT NULL,
            value DOUBLE PRECISION NULL,
            currency TEXT NULL,
            unit_scale TEXT NULL,
            source_metric_name TEXT NOT NULL DEFAULT '',
            normalization_status TEXT NOT NULL DEFAULT 'SOURCE_ONLY',
            quality_status TEXT NOT NULL DEFAULT 'UNKNOWN',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_fundamentals_financial_facts UNIQUE (
                report_id, metric_code, source_metric_name
            ),
            CONSTRAINT ck_fundamentals_normalization_status CHECK (
                normalization_status IN (
                    'NORMALIZED', 'SOURCE_ONLY', 'AMBIGUOUS', 'UNSUPPORTED'
                )
            )
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fundamentals_financial_facts_metric
            ON fundamentals.financial_facts (metric_code, normalization_status);
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals.dividend_events (
            id BIGSERIAL PRIMARY KEY,
            issuer_id BIGINT NULL
                REFERENCES fundamentals.issuers(id) ON DELETE CASCADE,
            instrument_id BIGINT NULL
                REFERENCES market.instruments(id) ON DELETE CASCADE,
            announcement_date DATE NULL,
            known_at DATE NOT NULL,
            board_recommendation_date DATE NULL,
            shareholder_approval_date DATE NULL,
            record_date DATE NULL,
            ex_date DATE NULL,
            payment_date DATE NULL,
            amount_per_share DOUBLE PRECISION NULL,
            currency TEXT NULL,
            status TEXT NOT NULL DEFAULT 'UNKNOWN',
            source TEXT NOT NULL,
            source_document_id BIGINT NULL
                REFERENCES fundamentals.source_documents(id) ON DELETE SET NULL,
            version INTEGER NOT NULL DEFAULT 1,
            supersedes_id BIGINT NULL
                REFERENCES fundamentals.dividend_events(id) ON DELETE SET NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_fundamentals_dividend_status CHECK (
                status IN (
                    'PROPOSED', 'RECOMMENDED', 'APPROVED', 'PAID', 'CANCELLED', 'UNKNOWN'
                )
            ),
            CONSTRAINT ck_fundamentals_dividend_subject CHECK (
                issuer_id IS NOT NULL OR instrument_id IS NOT NULL
            )
        );
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_fundamentals_dividend_events_identity
            ON fundamentals.dividend_events (
                COALESCE(issuer_id, 0),
                COALESCE(instrument_id, 0),
                source,
                COALESCE(record_date, DATE '0001-01-01'),
                COALESCE(ex_date, DATE '0001-01-01'),
                version
            );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fundamentals_dividend_events_pit
            ON fundamentals.dividend_events (instrument_id, known_at);
        """
    )

    # known_at is NOT NULL here on purpose: market.corporate_actions.known_at is
    # nullable, so the sync must declare an explicit, conservative availability date.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals.corporate_events (
            id BIGSERIAL PRIMARY KEY,
            issuer_id BIGINT NULL
                REFERENCES fundamentals.issuers(id) ON DELETE SET NULL,
            instrument_id BIGINT NULL
                REFERENCES market.instruments(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            event_date DATE NOT NULL,
            known_at DATE NOT NULL,
            effective_date DATE NULL,
            source TEXT NOT NULL,
            external_id TEXT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_fundamentals_corporate_event_subject CHECK (
                issuer_id IS NOT NULL OR instrument_id IS NOT NULL
            )
        );
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_fundamentals_corporate_events_identity
            ON fundamentals.corporate_events (
                event_type,
                COALESCE(instrument_id, 0),
                COALESCE(issuer_id, 0),
                event_date,
                source,
                COALESCE(external_id, '')
            );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fundamentals_corporate_events_pit
            ON fundamentals.corporate_events (instrument_id, known_at);
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals.ingestion_runs (
            id BIGSERIAL PRIMARY KEY,
            provider TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ NULL,
            requested_range TEXT NULL,
            status TEXT NOT NULL DEFAULT 'RUNNING',
            summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fundamentals_ingestion_runs_provider
            ON fundamentals.ingestion_runs (provider, started_at DESC);
        """
    )

    _seed_metric_registry()


def _seed_metric_registry() -> None:
    """Conservative seed. EBITDA stays AMBIGUOUS: it is not an IFRS/RAS line item."""
    op.execute(
        """
        INSERT INTO fundamentals.metric_registry
            (code, title_ru, title_en, description, applies_to_banks, status)
        VALUES
            ('REVENUE', 'Выручка', 'Revenue',
             'Выручка / процентные и прочие доходы отчётного периода.', FALSE, 'SUPPORTED'),
            ('OPERATING_INCOME', 'Операционная прибыль', 'Operating income',
             'Операционная прибыль. У банков операционного результата в этом смысле нет.',
             FALSE, 'SUPPORTED'),
            ('NET_INCOME', 'Чистая прибыль', 'Net income',
             'Чистая прибыль периода, относящаяся к акционерам.', TRUE, 'SUPPORTED'),
            ('TOTAL_ASSETS', 'Итого активы', 'Total assets',
             'Итого активы на конец периода.', TRUE, 'SUPPORTED'),
            ('TOTAL_EQUITY', 'Итого капитал', 'Total equity',
             'Итого капитал на конец периода.', TRUE, 'SUPPORTED'),
            ('TOTAL_DEBT', 'Итого долг', 'Total debt',
             'Процентный долг. Для банков привлечённые средства не являются долгом в этом смысле.',
             FALSE, 'SUPPORTED'),
            ('CASH_AND_EQUIVALENTS', 'Денежные средства и эквиваленты', 'Cash and equivalents',
             'Денежные средства и эквиваленты на конец периода.', TRUE, 'SUPPORTED'),
            ('OPERATING_CASH_FLOW', 'Операционный денежный поток', 'Operating cash flow',
             'Чистый денежный поток от операционной деятельности.', TRUE, 'SUPPORTED'),
            ('EBITDA', 'EBITDA', 'EBITDA',
             'Не является строкой отчётности: определение зависит от эмитента. '
             'Использовать только как раскрытый эмитентом показатель.', FALSE, 'AMBIGUOUS')
        ON CONFLICT (code) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fundamentals.ingestion_runs;")
    op.execute("DROP TABLE IF EXISTS fundamentals.corporate_events;")
    op.execute("DROP TABLE IF EXISTS fundamentals.dividend_events;")
    op.execute("DROP TABLE IF EXISTS fundamentals.financial_facts;")
    op.execute("DROP TABLE IF EXISTS fundamentals.financial_reports;")
    op.execute("DROP TABLE IF EXISTS fundamentals.metric_registry;")
    op.execute("DROP TABLE IF EXISTS fundamentals.source_documents;")
    op.execute("DROP TABLE IF EXISTS fundamentals.security_issuer_mappings;")
    op.execute("DROP TABLE IF EXISTS fundamentals.issuers;")
    op.execute("DROP SCHEMA IF EXISTS fundamentals;")
