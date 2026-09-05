"""DB-backed tests. Skipped until alembic 20260905_0018 is applied.

Every test runs inside the rolled-back `core_db` transaction, so nothing persists.
Live report/dividend coverage is expected to be empty — fixtures provide the data.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select, text

from app.infrastructure.market.models import CorporateAction, Instrument, InstrumentSource
from app.modules.fundamentals.application import pit
from app.modules.fundamentals.application.corporate_events_sync import (
    BASIS_EFFECTIVE_DATE_OBSERVABLE,
    sync_corporate_events,
)
from app.modules.fundamentals.application.identity import sync_issuer_identity
from app.modules.fundamentals.application.ingest_dividends import run_dividend_ingestion
from app.modules.fundamentals.application.ingest_reports import run_report_ingestion
from app.modules.fundamentals.application.metric_registry import ensure_metric_registry
from app.modules.fundamentals.application.readiness import build_readiness_report
from app.modules.fundamentals.domain.types import (
    METRIC_REGISTRY_SEED,
    SOURCE_MARKET_CORPORATE_ACTIONS,
    DividendStatus,
    IngestionStatus,
    IssuerIdentity,
    MappingStatus,
    NormalizationStatus,
)
from app.modules.fundamentals.infrastructure.models import (
    CorporateEvent,
    DividendEvent,
    FinancialFact,
    FinancialReport,
    Issuer,
    MetricRegistryEntry,
    SecurityIssuerMapping,
    fundamentals_schema_ready,
)

TEST_SYMBOL = "ZZFUNDTEST"


@pytest.fixture
def fundamentals_db(core_db):
    if not fundamentals_schema_ready(core_db):
        pytest.skip("fundamentals schema missing; apply alembic 20260905_0018")
    return core_db


@pytest.fixture
def test_instrument(fundamentals_db) -> Instrument:
    instrument = Instrument(
        symbol=TEST_SYMBOL,
        name="Fundamentals test issuer",
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=True,
    )
    fundamentals_db.add(instrument)
    fundamentals_db.flush()
    fundamentals_db.add(
        InstrumentSource(
            instrument_id=instrument.id,
            source="MOEX",
            external_id=TEST_SYMBOL,
            board="TQBR",
            valid_from=None,
            valid_to=None,
            source_metadata={},
        )
    )
    fundamentals_db.flush()
    return instrument


class _FakeIdentityProvider:
    """Answers only for the test SECID; everything else is honestly UNMAPPED."""

    source = "MOEX_ISS"

    def __init__(self, *, emitent_id: int | None = 999_001) -> None:
        self.emitent_id = emitent_id
        self.calls: list[str] = []

    def fetch_issuer(self, secid: str) -> IssuerIdentity:
        self.calls.append(secid)
        if secid != TEST_SYMBOL or self.emitent_id is None:
            return IssuerIdentity(
                secid=secid, mapping_status=MappingStatus.UNMAPPED, reason="NO_EMITENT_ID"
            )
        return IssuerIdentity(
            secid=secid,
            mapping_status=MappingStatus.MAPPED,
            moex_emitent_id=self.emitent_id,
            title="Тестовый эмитент",
            inn="7700000000",
            isin="RU000ZZFUND1",
        )


def _make_issuer(session, *, emitent_id: int = 999_002) -> Issuer:
    issuer = Issuer(moex_emitent_id=emitent_id, title="PIT test issuer", metadata_={})
    session.add(issuer)
    session.flush()
    return issuer


def test_metric_registry_seed_matches_domain(fundamentals_db) -> None:
    codes = set(
        fundamentals_db.scalars(select(MetricRegistryEntry.code)).all()
    )
    assert {m.code for m in METRIC_REGISTRY_SEED} <= codes

    ebitda = fundamentals_db.get(MetricRegistryEntry, "EBITDA")
    assert ebitda is not None
    assert ebitda.status == "AMBIGUOUS"
    assert ebitda.applies_to_banks is False

    # Re-seeding the same definitions changes nothing.
    assert ensure_metric_registry(fundamentals_db) == {
        "inserted": 0,
        "updated": 0,
        "total": len(METRIC_REGISTRY_SEED),
    }


def test_identity_sync_maps_only_what_the_provider_resolved(
    fundamentals_db, test_instrument
) -> None:
    provider = _FakeIdentityProvider()
    result = sync_issuer_identity(fundamentals_db, provider, symbols=[TEST_SYMBOL])

    assert provider.calls == [TEST_SYMBOL]
    assert result.mapped == 1
    assert result.issuers_inserted == 1
    assert result.mappings_inserted == 1

    mapping = fundamentals_db.scalar(
        select(SecurityIssuerMapping).where(
            SecurityIssuerMapping.instrument_id == test_instrument.id
        )
    )
    assert mapping is not None
    assert mapping.mapping_status == MappingStatus.MAPPED.value
    assert mapping.issuer_id is not None
    assert mapping.isin == "RU000ZZFUND1"

    # Idempotent: a second run neither duplicates nor rewrites anything.
    second = sync_issuer_identity(fundamentals_db, _FakeIdentityProvider(), symbols=[TEST_SYMBOL])
    assert second.status == IngestionStatus.NO_CHANGES.value
    assert second.mappings_inserted == 0
    assert second.issuers_inserted == 0
    assert second.mappings_unchanged == 1


def test_identity_sync_does_not_invent_an_issuer_when_unresolved(
    fundamentals_db, test_instrument
) -> None:
    result = sync_issuer_identity(
        fundamentals_db, _FakeIdentityProvider(emitent_id=None), symbols=[TEST_SYMBOL]
    )

    assert result.mapped == 0
    assert result.unmapped == 1
    assert result.issuers_inserted == 0

    mapping = fundamentals_db.scalar(
        select(SecurityIssuerMapping).where(
            SecurityIssuerMapping.instrument_id == test_instrument.id
        )
    )
    assert mapping is not None
    assert mapping.mapping_status == MappingStatus.UNMAPPED.value
    assert mapping.issuer_id is None


def test_corporate_events_sync_is_idempotent_and_declares_known_at_basis(
    fundamentals_db, test_instrument
) -> None:
    fundamentals_db.add(
        CorporateAction(
            instrument_id=test_instrument.id,
            event_date=date(2026, 4, 10),
            event_type="SPLIT",
            payload={"before": "1", "after": "10"},
            source="MOEX",
            external_id=None,
            known_at=None,
        )
    )
    fundamentals_db.flush()

    first = sync_corporate_events(fundamentals_db)
    assert first.status == IngestionStatus.SUCCESS.value

    event = fundamentals_db.scalar(
        select(CorporateEvent).where(CorporateEvent.instrument_id == test_instrument.id)
    )
    assert event is not None
    assert event.source == SOURCE_MARKET_CORPORATE_ACTIONS
    assert event.known_at == date(2026, 4, 10)
    assert event.payload["known_at_basis"] == BASIS_EFFECTIVE_DATE_OBSERVABLE

    second = sync_corporate_events(fundamentals_db)
    assert second.inserted == 0
    events = fundamentals_db.scalars(
        select(CorporateEvent).where(CorporateEvent.instrument_id == test_instrument.id)
    ).all()
    assert len(events) == 1


def test_corporate_events_sync_uses_source_known_at_when_present(
    fundamentals_db, test_instrument
) -> None:
    fundamentals_db.add(
        CorporateAction(
            instrument_id=test_instrument.id,
            event_date=date(2026, 4, 10),
            event_type="SPLIT",
            payload={},
            source="MOEX",
            external_id="split-zz-1",
            known_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
        )
    )
    fundamentals_db.flush()

    sync_corporate_events(fundamentals_db)
    event = fundamentals_db.scalar(
        select(CorporateEvent).where(CorporateEvent.instrument_id == test_instrument.id)
    )
    assert event is not None
    assert event.known_at == date(2026, 3, 1)
    assert event.payload["known_at_basis"] == "SOURCE_KNOWN_AT"


def test_pit_report_visibility_and_restatement_in_db(fundamentals_db) -> None:
    issuer = _make_issuer(fundamentals_db)
    original = FinancialReport(
        issuer_id=issuer.id,
        reporting_standard="IFRS",
        period_type="FY",
        period_end=date(2025, 12, 31),
        known_at=date(2026, 3, 20),
        source="FIXTURE",
        report_version=1,
        currency="RUB",
    )
    restated = FinancialReport(
        issuer_id=issuer.id,
        reporting_standard="IFRS",
        period_type="FY",
        period_end=date(2025, 12, 31),
        known_at=date(2026, 8, 10),
        source="FIXTURE",
        report_version=2,
        is_restatement=True,
        currency="RUB",
    )
    fundamentals_db.add_all([original, restated])
    fundamentals_db.flush()
    fundamentals_db.add_all(
        [
            FinancialFact(
                report_id=original.id,
                metric_code="NET_INCOME",
                value=1_000.0,
                normalization_status=NormalizationStatus.NORMALIZED.value,
            ),
            FinancialFact(
                report_id=restated.id,
                metric_code="NET_INCOME",
                value=1_100.0,
                normalization_status=NormalizationStatus.NORMALIZED.value,
            ),
        ]
    )
    fundamentals_db.flush()

    before = pit.get_fundamentals_as_of(fundamentals_db, issuer.id, date(2026, 3, 19))
    assert before.has_report is False
    assert before.facts == ()

    after_first = pit.get_fundamentals_as_of(fundamentals_db, issuer.id, date(2026, 5, 1))
    assert after_first.latest_report is not None
    assert after_first.latest_report.report_version == 1
    assert [fact.value for fact in after_first.facts] == [1_000.0]

    after_restatement = pit.get_fundamentals_as_of(fundamentals_db, issuer.id, date(2026, 9, 1))
    assert after_restatement.latest_report is not None
    assert after_restatement.latest_report.report_version == 2
    assert [fact.value for fact in after_restatement.facts] == [1_100.0]


def test_pit_dividend_state_in_db(fundamentals_db, test_instrument) -> None:
    issuer = _make_issuer(fundamentals_db, emitent_id=999_003)
    fundamentals_db.add_all(
        [
            DividendEvent(
                issuer_id=issuer.id,
                instrument_id=test_instrument.id,
                announcement_date=date(2026, 4, 20),
                known_at=date(2026, 4, 20),
                record_date=date(2026, 7, 10),
                amount_per_share=30.0,
                currency="RUB",
                status=DividendStatus.RECOMMENDED.value,
                source="FIXTURE",
                version=1,
            ),
            DividendEvent(
                issuer_id=issuer.id,
                instrument_id=test_instrument.id,
                announcement_date=date(2026, 6, 25),
                known_at=date(2026, 6, 25),
                record_date=date(2026, 7, 10),
                amount_per_share=34.0,
                currency="RUB",
                status=DividendStatus.APPROVED.value,
                source="FIXTURE",
                version=2,
            ),
        ]
    )
    fundamentals_db.flush()

    hidden = pit.get_dividend_state_as_of(
        fundamentals_db, date(2026, 4, 1), instrument_id=test_instrument.id
    )
    assert hidden.is_known is False

    recommended = pit.get_dividend_state_as_of(
        fundamentals_db, date(2026, 5, 1), instrument_id=test_instrument.id
    )
    assert recommended.status is DividendStatus.RECOMMENDED
    assert recommended.amount_per_share == 30.0

    approved = pit.get_dividend_state_as_of(
        fundamentals_db, date(2026, 6, 30), instrument_id=test_instrument.id
    )
    assert approved.status is DividendStatus.APPROVED
    assert approved.version == 2

    upcoming = pit.get_upcoming_dividend_as_of(
        fundamentals_db, date(2026, 6, 30), instrument_id=test_instrument.id
    )
    assert upcoming is not None
    assert upcoming.record_date == date(2026, 7, 10)


def test_report_and_dividend_ingestion_defer_without_provider(fundamentals_db) -> None:
    reports_before = int(
        fundamentals_db.execute(
            text("SELECT count(*) FROM fundamentals.financial_reports")
        ).scalar_one()
    )
    dividends_before = int(
        fundamentals_db.execute(
            text("SELECT count(*) FROM fundamentals.dividend_events")
        ).scalar_one()
    )

    reports = run_report_ingestion(fundamentals_db)
    dividends = run_dividend_ingestion(fundamentals_db)

    assert reports.status == IngestionStatus.DEFERRED.value
    assert reports.reason == "NO_PROVIDER_CONFIGURED"
    assert dividends.status == IngestionStatus.DEFERRED.value
    assert dividends.reason == "SOURCE_REJECTED_BY_AUDIT"

    assert (
        int(
            fundamentals_db.execute(
                text("SELECT count(*) FROM fundamentals.financial_reports")
            ).scalar_one()
        )
        == reports_before
    )
    assert (
        int(
            fundamentals_db.execute(
                text("SELECT count(*) FROM fundamentals.dividend_events")
            ).scalar_one()
        )
        == dividends_before
    )


def test_readiness_report_never_mutates_a_dataset_spec(fundamentals_db) -> None:
    report = build_readiness_report(fundamentals_db)

    assert report["dataset_spec_mutated"] is False
    assert report["status"] in {"NOT_READY", "PARTIAL", "READY"}
    assert "ABSOLUTE_RETURN_20D" in report["target_research_specs"]
