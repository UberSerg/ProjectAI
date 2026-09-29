"""Broker accounts + FeeProfile / FeeRule + operation provenance.

Revision ID: 20260929_0026
Revises: 20260928_0025

Additive only:
- portfolio.fee_profiles / fee_rules / broker_accounts
- nullable broker_account_id on manual_portfolios
- provenance columns on personal_operations
- seed built-in Sber Investment profile + MOEX 0.3% + SBFR temporary zero-fee
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260929_0026"
down_revision: str | None = "20260928_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS portfolio")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.fee_profiles (
            id BIGSERIAL PRIMARY KEY,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            broker_code TEXT NOT NULL,
            broker_name TEXT NOT NULL,
            tariff_name TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            valid_from DATE,
            valid_to DATE,
            source_url TEXT,
            source_note TEXT,
            is_builtin BOOLEAN NOT NULL DEFAULT FALSE,
            read_only BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_fee_profiles_code_version UNIQUE (code, version)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.fee_rules (
            id BIGSERIAL PRIMARY KEY,
            fee_profile_id BIGINT NOT NULL
                REFERENCES portfolio.fee_profiles(id) ON DELETE CASCADE,
            code TEXT,
            market TEXT,
            trading_system TEXT,
            execution_channel TEXT,
            side TEXT,
            asset_class TEXT,
            instrument_subtype TEXT,
            instrument_id BIGINT
                REFERENCES market.instruments(id) ON DELETE SET NULL,
            instrument_symbol TEXT,
            turnover_from NUMERIC(20, 6),
            turnover_to NUMERIC(20, 6),
            fee_type TEXT NOT NULL DEFAULT 'PERCENTAGE',
            percentage_rate NUMERIC(20, 10),
            fixed_amount NUMERIC(20, 6),
            exclude_from_turnover BOOLEAN NOT NULL DEFAULT FALSE,
            priority INTEGER NOT NULL DEFAULT 100,
            valid_from DATE,
            valid_to DATE,
            explanation TEXT,
            source_note TEXT,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_fee_rules_side CHECK (
                side IS NULL OR side IN ('BUY', 'SELL', 'ANY')
            ),
            CONSTRAINT ck_fee_rules_fee_type CHECK (
                fee_type IN ('PERCENTAGE', 'FIXED', 'PERCENTAGE_PLUS_FIXED')
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_fee_rules_profile_priority
            ON portfolio.fee_rules (fee_profile_id, priority ASC, id ASC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio.broker_accounts (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            broker_code TEXT NOT NULL,
            broker_name TEXT NOT NULL,
            tariff_name TEXT,
            fee_profile_id BIGINT NOT NULL
                REFERENCES portfolio.fee_profiles(id) ON DELETE RESTRICT,
            base_currency TEXT NOT NULL DEFAULT 'RUB',
            active BOOLEAN NOT NULL DEFAULT TRUE,
            note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_broker_accounts_profile
            ON portfolio.broker_accounts (fee_profile_id)
        """
    )

    op.execute(
        """
        ALTER TABLE portfolio.manual_portfolios
            ADD COLUMN IF NOT EXISTS broker_account_id BIGINT
                REFERENCES portfolio.broker_accounts(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_manual_portfolios_broker_account
            ON portfolio.manual_portfolios (broker_account_id)
        """
    )

    op.execute(
        """
        ALTER TABLE portfolio.personal_operations
            ADD COLUMN IF NOT EXISTS broker_account_id BIGINT
                REFERENCES portfolio.broker_accounts(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS fee_rule_id BIGINT
                REFERENCES portfolio.fee_rules(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS commission_source TEXT
        """
    )
    op.execute(
        """
        ALTER TABLE portfolio.personal_operations
            DROP CONSTRAINT IF EXISTS ck_personal_operations_commission_source
        """
    )
    op.execute(
        """
        ALTER TABLE portfolio.personal_operations
            ADD CONSTRAINT ck_personal_operations_commission_source
            CHECK (
                commission_source IS NULL
                OR commission_source IN ('NONE', 'MANUAL', 'PROFILE_ESTIMATE')
            )
        """
    )

    # Built-in Sber Investment snapshot (user-provided tariff page, 2026-09-29).
    op.execute(
        """
        INSERT INTO portfolio.fee_profiles (
            code, name, broker_code, broker_name, tariff_name, version,
            valid_from, source_url, source_note, is_builtin, read_only
        )
        VALUES (
            'SBER_INVESTMENT',
            'СберИнвестиции — Инвестиционный',
            'SBER',
            'СберИнвестиции',
            'Инвестиционный',
            1,
            DATE '2026-09-29',
            'https://www.sberbank.ru/ru/person/investments/broker_service/tarifs',
            'User-provided tariff snapshot, 2026-09-29',
            TRUE,
            TRUE
        )
        ON CONFLICT (code, version) DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO portfolio.fee_rules (
            fee_profile_id, code, market, execution_channel, side,
            fee_type, percentage_rate, exclude_from_turnover, priority,
            valid_from, explanation, source_note, active
        )
        SELECT
            p.id,
            'SBER_MOEX_ONLINE_DEFAULT',
            'MOEX',
            'ONLINE',
            'ANY',
            'PERCENTAGE',
            0.0030000000,
            FALSE,
            100,
            DATE '2026-09-29',
            'Default MOEX stock-market online trades: 0.3% of turnover (broker commission; exchange fees separate). Turnover excludes NKD.',
            'User-provided tariff snapshot, 2026-09-29',
            TRUE
        FROM portfolio.fee_profiles p
        WHERE p.code = 'SBER_INVESTMENT' AND p.version = 1
          AND NOT EXISTS (
              SELECT 1 FROM portfolio.fee_rules r
              WHERE r.fee_profile_id = p.id AND r.code = 'SBER_MOEX_ONLINE_DEFAULT'
          )
        """
    )

    # Verified УК «Первая» BPIF only (SBFR). Do NOT seed SBMM/SBRB/FLOW as zero-fee.
    op.execute(
        """
        INSERT INTO portfolio.fee_rules (
            fee_profile_id, code, market, execution_channel, side,
            instrument_symbol, fee_type, percentage_rate,
            exclude_from_turnover, priority,
            valid_from, valid_to, explanation, source_note, active
        )
        SELECT
            p.id,
            'SBER_SBFR_ZERO_TEMP',
            'MOEX',
            'ONLINE',
            'ANY',
            'SBFR',
            'PERCENTAGE',
            0.0000000000,
            TRUE,
            10,
            DATE '2026-08-04',
            DATE '2026-12-31',
            'Temporary zero broker fee for verified УК Первая BPIF (SBFR). Turnover excluded from broker daily turnover.',
            'User-provided tariff snapshot, 2026-09-29; manager verified for SBFR only',
            TRUE
        FROM portfolio.fee_profiles p
        WHERE p.code = 'SBER_INVESTMENT' AND p.version = 1
          AND NOT EXISTS (
              SELECT 1 FROM portfolio.fee_rules r
              WHERE r.fee_profile_id = p.id AND r.code = 'SBER_SBFR_ZERO_TEMP'
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE portfolio.personal_operations
            DROP CONSTRAINT IF EXISTS ck_personal_operations_commission_source
        """
    )
    op.execute(
        """
        ALTER TABLE portfolio.personal_operations
            DROP COLUMN IF EXISTS commission_source,
            DROP COLUMN IF EXISTS fee_rule_id,
            DROP COLUMN IF EXISTS broker_account_id
        """
    )
    op.execute("DROP INDEX IF EXISTS portfolio.ix_manual_portfolios_broker_account")
    op.execute(
        """
        ALTER TABLE portfolio.manual_portfolios
            DROP COLUMN IF EXISTS broker_account_id
        """
    )
    op.execute("DROP INDEX IF EXISTS portfolio.ix_broker_accounts_profile")
    op.execute("DROP TABLE IF EXISTS portfolio.broker_accounts")
    op.execute("DROP INDEX IF EXISTS portfolio.ix_fee_rules_profile_priority")
    op.execute("DROP TABLE IF EXISTS portfolio.fee_rules")
    op.execute("DROP TABLE IF EXISTS portfolio.fee_profiles")
