"""Dataset PIT V4 — research-only PIT fund/event enrichment; V1–V3 immutable."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetRun, DatasetSampleDaily, DatasetSpec
from app.modules.fundamentals.application.pit import BASIS_CURRENT_ONLY, BASIS_DATED_WINDOW, BASIS_UNMAPPED
from app.modules.fundamentals.domain.types import (
    CorporateEventRef,
    CorporateEventType,
    DividendEventRef,
    DividendStatus,
    FactRef,
    MappingStatus,
    NormalizationStatus,
    PeriodType,
    ReportingStandard,
    ReportRef,
)
from app.modules.fundamentals.infrastructure.models import (
    CorporateEvent,
    DividendEvent,
    FinancialFact,
    FinancialReport,
    Issuer,
    SecurityIssuerMapping,
    fundamentals_schema_ready,
)
from app.modules.learning.application.builder import PITDatasetBuilder, grade_v4_research_quality
from app.modules.learning.application.compare_v3_v4 import compare_v3_v4_builds
from app.modules.learning.application.research_eval import assert_fair_v3_v4_compare_contract
from app.modules.learning.application.seed import seed_dataset_specs
from app.modules.learning.application.v4_enrichment import (
    V4EnrichmentIndex,
    load_v4_enrichment_index,
    resolve_v4_sample,
)
from app.modules.learning.dataset_config import (
    FEATURE_MANIFEST_V1,
    FEATURE_MANIFEST_V4,
    PIT_DAILY_CORE_ACTIVE_VERSION,
    PIT_DAILY_CORE_CODE,
    PIT_DAILY_CORE_V1,
    PIT_DAILY_CORE_V2,
    PIT_DAILY_CORE_V3,
    PIT_DAILY_CORE_V3_VERSION,
    PIT_DAILY_CORE_V4,
    PIT_DAILY_CORE_V4_VERSION,
    RESEARCH_CORE_GRADE_NOT_READY,
    RESEARCH_CORE_GRADE_PARTIAL,
    RESEARCH_CORE_GRADE_READY,
    RESEARCH_V4_PARTIAL_CURRENT_ONLY_PCT,
    RESEARCH_V4_PARTIAL_MIN_ENRICHMENT_PCT,
    UNIVERSE_POLICY_HISTORICAL_V2,
    V4_EVENT_FEATURE_NAMES,
    V4_FUNDAMENTAL_FEATURE_NAMES,
    feature_names_for_spec_version,
    feature_names_from_manifest,
)
from app.modules.prediction.application.research_dataset_loader import (
    ALLOWED_RESEARCH_VERSIONS,
    load_research_frame,
)
from app.modules.prediction.application.research_runner import run_experimental_v2_v3_oos
from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
from app.modules.prediction.candidate_v1_config import CANDIDATE_V1_RANKER_CONFIG
from tests.learning.test_dataset_v3 import (
    _add_basic,
    _add_candle,
    _bind_flush_only,
    _seed_v3_fixture,
)


def _require_fundamentals(session: Session) -> None:
    if not fundamentals_schema_ready(session):
        pytest.skip("fundamentals schema missing; apply alembic 20260905_0018")


def _mapping(*, issuer_id: int | None, valid_from=None, valid_to=None, status: str = "MAPPED"):
    return SimpleNamespace(
        mapping_status=status,
        issuer_id=issuer_id,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def _report(*, report_id: int, known_at: date, version: int = 1, is_restatement: bool = False) -> ReportRef:
    return ReportRef(
        report_id=report_id,
        issuer_id=1,
        reporting_standard=ReportingStandard.IFRS,
        period_type=PeriodType.FY,
        period_end=date(2025, 12, 31),
        known_at=known_at,
        report_version=version,
        is_restatement=is_restatement,
        source="FIXTURE",
        currency="RUB",
        unit_scale="units",
    )


def _fact(report_id: int, code: str, value: float, *, currency: str = "RUB", status=None) -> FactRef:
    return FactRef(
        metric_code=code,
        value=value,
        normalization_status=status or NormalizationStatus.NORMALIZED,
        currency=currency,
        unit_scale="units",
        report_id=report_id,
    )


def test_v1_v2_v3_immutable_and_v4_additive() -> None:
    assert PIT_DAILY_CORE_ACTIVE_VERSION == 1
    assert PIT_DAILY_CORE_V4_VERSION == 4
    assert PIT_DAILY_CORE_V1["version"] == 1
    assert PIT_DAILY_CORE_V2["version"] == 2
    assert PIT_DAILY_CORE_V3["version"] == 3
    v1 = feature_names_from_manifest(FEATURE_MANIFEST_V1)
    v3 = feature_names_from_manifest(PIT_DAILY_CORE_V3["feature_manifest"])
    v4 = feature_names_from_manifest(FEATURE_MANIFEST_V4)
    assert v1 == feature_names_from_manifest(PIT_DAILY_CORE_V2["feature_manifest"]) == v3
    assert v4[: len(v3)] == v3
    assert set(V4_FUNDAMENTAL_FEATURE_NAMES).issubset(set(v4))
    assert set(V4_EVENT_FEATURE_NAMES).issubset(set(v4))
    assert "EBITDA" not in v4
    assert "fund_revenue" not in v4
    assert PIT_DAILY_CORE_V3["label_spec"] == PIT_DAILY_CORE_V4["label_spec"]
    assert PIT_DAILY_CORE_V3["universe_policy"] == UNIVERSE_POLICY_HISTORICAL_V2
    assert PIT_DAILY_CORE_V4["universe_policy"] == UNIVERSE_POLICY_HISTORICAL_V2
    assert PIT_DAILY_CORE_V4["parameters"]["total_return"] is False
    assert PIT_DAILY_CORE_V4["parameters"]["primary_label_family"] == "MECHANICAL_PRICE_RETURN"
    assert PIT_DAILY_CORE_V4["parameters"]["production_activation"] is False
    assert feature_names_for_spec_version(2) == v1
    assert feature_names_for_spec_version(3) == v1
    assert feature_names_for_spec_version(4) == v4
    fair = assert_fair_v3_v4_compare_contract()
    assert fair["added_feature_count"] == len(V4_FUNDAMENTAL_FEATURE_NAMES) + len(V4_EVENT_FEATURE_NAMES)


def test_v4_spec_seeded_inactive_candidates_stay_v2(core_db: Session) -> None:
    seed_dataset_specs(core_db)
    v4 = core_db.scalar(
        select(DatasetSpec).where(
            DatasetSpec.code == PIT_DAILY_CORE_CODE,
            DatasetSpec.version == PIT_DAILY_CORE_V4_VERSION,
        )
    )
    assert v4 is not None
    assert v4.is_active is False
    active = core_db.scalar(
        select(DatasetSpec).where(
            DatasetSpec.code == PIT_DAILY_CORE_CODE,
            DatasetSpec.is_active.is_(True),
        )
    )
    assert active is not None
    assert active.version == 1
    assert CANDIDATE_V0_CONFIG.dataset_spec_version == 2
    assert CANDIDATE_V1_RANKER_CONFIG.dataset_spec_version == 2


def test_grade_v4_research_quality_boundaries() -> None:
    ready = grade_v4_research_quality(
        samples_total=10,
        apply_date_eligibility=True,
        pit_violations=0,
        fund_coverage_pct=50.0,
        event_coverage_pct=40.0,
        current_only_pct=10.0,
        malformed_contract=False,
    )
    assert ready["grade"] == RESEARCH_CORE_GRADE_READY
    assert ready["production_ready"] is False

    not_ready = grade_v4_research_quality(
        samples_total=10,
        apply_date_eligibility=True,
        pit_violations=1,
        fund_coverage_pct=50.0,
        event_coverage_pct=40.0,
        current_only_pct=0.0,
        malformed_contract=False,
    )
    assert not_ready["grade"] == RESEARCH_CORE_GRADE_NOT_READY
    assert "pit_violation" in not_ready["reasons"]

    zero = grade_v4_research_quality(
        samples_total=10,
        apply_date_eligibility=True,
        pit_violations=0,
        fund_coverage_pct=0.0,
        event_coverage_pct=0.0,
        current_only_pct=0.0,
        malformed_contract=False,
    )
    assert zero["grade"] == RESEARCH_CORE_GRADE_NOT_READY
    assert "zero_v4_enrichment_coverage" in zero["reasons"]

    partial = grade_v4_research_quality(
        samples_total=100,
        apply_date_eligibility=True,
        pit_violations=0,
        fund_coverage_pct=RESEARCH_V4_PARTIAL_MIN_ENRICHMENT_PCT - 0.1,
        event_coverage_pct=50.0,
        current_only_pct=RESEARCH_V4_PARTIAL_CURRENT_ONLY_PCT + 1,
        malformed_contract=False,
    )
    assert partial["grade"] == RESEARCH_CORE_GRADE_PARTIAL
    assert "low_fundamentals_coverage" in partial["reasons"]
    assert "current_only_issuer_mapping_share_material" in partial["reasons"]


def test_restatement_does_not_leak_backward() -> None:
    index = V4EnrichmentIndex(schema_ready=True)
    index.mappings_by_instrument = {7: [_mapping(issuer_id=1, valid_from=date(2020, 1, 1))]}
    a = _report(report_id=10, known_at=date(2026, 3, 20), version=1)
    b = _report(report_id=11, known_at=date(2026, 6, 10), version=2, is_restatement=True)
    index.reports_by_issuer = {1: [a, b]}
    index.facts_by_report = {
        10: (
            _fact(10, "NET_INCOME", 100.0),
            _fact(10, "REVENUE", 1000.0),
        ),
        11: (
            _fact(11, "NET_INCOME", 200.0),
            _fact(11, "REVENUE", 1000.0),
        ),
    }
    may = resolve_v4_sample(index, instrument_id=7, as_of=date(2026, 5, 1))
    july = resolve_v4_sample(index, instrument_id=7, as_of=date(2026, 7, 1))
    assert may.features["fund_net_margin"] == pytest.approx(0.1)
    assert july.features["fund_net_margin"] == pytest.approx(0.2)
    assert may.lineage["fundamentals"]["report_id"] == 10
    assert july.lineage["fundamentals"]["report_id"] == 11
    assert may.lineage["fundamentals"]["issuer_resolution_basis"] == BASIS_DATED_WINDOW


def test_event_disclosure_known_at_not_economic_date() -> None:
    index = V4EnrichmentIndex(schema_ready=True)
    index.mappings_by_instrument = {7: []}
    div = DividendEventRef(
        known_at=date(2026, 6, 15),
        status=DividendStatus.RECOMMENDED,
        source="FIXTURE",
        instrument_id=7,
        record_date=date(2026, 7, 20),
        amount_per_share=5.0,
        currency="RUB",
    )
    index.div_by_instrument = {7: [div]}
    before = resolve_v4_sample(index, instrument_id=7, as_of=date(2026, 6, 10))
    after = resolve_v4_sample(index, instrument_id=7, as_of=date(2026, 6, 20))
    assert before.features["event_has_known_upcoming_dividend"] is None
    assert before.features["event_days_to_next_dividend_record_date"] is None
    assert after.features["event_has_known_upcoming_dividend"] == 1.0
    assert after.features["event_days_to_next_dividend_record_date"] == 30.0


def test_unmapped_and_no_report_and_partial_metric_and_empty_dividends() -> None:
    index = V4EnrichmentIndex(schema_ready=True)
    index.mappings_by_instrument = {1: [], 2: [_mapping(issuer_id=9, valid_from=date(2020, 1, 1))]}
    index.reports_by_issuer = {
        9: [_report(report_id=1, known_at=date(2026, 3, 1))],
    }
    index.facts_by_report = {
        1: (
            _fact(1, "REVENUE", 100.0),
            _fact(1, "OPERATING_INCOME", 20.0),
            _fact(1, "EBITDA", 30.0, status=NormalizationStatus.AMBIGUOUS),
            _fact(1, "TOTAL_DEBT", 50.0),
            _fact(1, "TOTAL_EQUITY", 0.0),
        )
    }
    unmapped = resolve_v4_sample(index, instrument_id=1, as_of=date(2026, 5, 1))
    assert unmapped.lineage["fundamentals"]["issuer_resolution_basis"] == BASIS_UNMAPPED
    assert all(unmapped.features[n] is None for n in V4_FUNDAMENTAL_FEATURE_NAMES)
    assert unmapped.features["event_has_known_upcoming_dividend"] is None

    mapped = resolve_v4_sample(index, instrument_id=2, as_of=date(2026, 5, 1))
    assert mapped.features["fund_operating_margin"] == pytest.approx(0.2)
    assert mapped.features["fund_net_margin"] is None
    assert mapped.features["fund_debt_to_equity"] is None
    assert "fund_ebitda" not in mapped.features
    assert mapped.features["event_has_known_upcoming_dividend"] is None

    split_only = V4EnrichmentIndex(schema_ready=True)
    split_only.corp_by_instrument = {
        3: [
            CorporateEventRef(
                event_type=CorporateEventType.SPLIT,
                event_date=date(2026, 1, 10),
                known_at=date(2026, 1, 10),
                source="TEST",
                instrument_id=3,
            )
        ]
    }
    row = resolve_v4_sample(split_only, instrument_id=3, as_of=date(2026, 2, 1))
    assert row.features["event_days_since_last_split"] == 22.0
    assert row.features["event_has_known_upcoming_dividend"] is None
    assert row.lineage["events"].get("dividend_missing_reason") == "NO_DIVIDEND_COVERAGE"


def test_current_only_mapping_is_explicit() -> None:
    index = V4EnrichmentIndex(schema_ready=True)
    index.mappings_by_instrument = {4: [_mapping(issuer_id=1)]}
    index.reports_by_issuer = {1: [_report(report_id=1, known_at=date(2026, 1, 1))]}
    index.facts_by_report = {1: (_fact(1, "REVENUE", 10.0), _fact(1, "NET_INCOME", 1.0))}
    row = resolve_v4_sample(index, instrument_id=4, as_of=date(2026, 5, 1))
    assert row.lineage["fundamentals"]["issuer_resolution_basis"] == BASIS_CURRENT_ONLY
    assert row.features["fund_net_margin"] == pytest.approx(0.1)


def test_incompatible_currency_ratio_is_missing() -> None:
    index = V4EnrichmentIndex(schema_ready=True)
    index.mappings_by_instrument = {5: [_mapping(issuer_id=1, valid_from=date(2020, 1, 1))]}
    index.reports_by_issuer = {1: [_report(report_id=1, known_at=date(2026, 1, 1))]}
    index.facts_by_report = {
        1: (
            _fact(1, "NET_INCOME", 10.0, currency="USD"),
            _fact(1, "REVENUE", 100.0, currency="RUB"),
        )
    }
    row = resolve_v4_sample(index, instrument_id=5, as_of=date(2026, 5, 1))
    assert row.features["fund_net_margin"] is None
    assert row.features["fund_has_recent_report"] == 1.0


def test_v4_historical_universe_and_labels_match_v3(core_db: Session) -> None:
    _bind_flush_only(core_db)
    fx = _seed_v3_fixture(core_db)
    ids = [fx["dead"].id, fx["aaa"].id, fx["new"].id]
    builder = PITDatasetBuilder(core_db)
    v3 = builder.run_build(
        date_from=date(2024, 5, 1),
        date_to=date(2024, 7, 15),
        dataset_spec_version=PIT_DAILY_CORE_V3_VERSION,
        instrument_ids=ids,
        seed_specs=False,
    )
    v4 = builder.run_build(
        date_from=date(2024, 5, 1),
        date_to=date(2024, 7, 15),
        dataset_spec_version=PIT_DAILY_CORE_V4_VERSION,
        instrument_ids=ids,
        seed_specs=False,
    )
    assert v3["pit_status"] == v4["pit_status"] == "PASS"
    run3 = core_db.get(DatasetRun, v3["dataset_run_id"])
    run4 = core_db.get(DatasetRun, v4["dataset_run_id"])
    assert run4.resolved_universe["policy"] == UNIVERSE_POLICY_HISTORICAL_V2
    cov = run4.coverage_summary or {}
    assert cov.get("return_truth", {}).get("total_return") is False
    assert cov.get("return_truth", {}).get("primary_label_family") == "MECHANICAL_PRICE_RETURN"
    assert cov.get("return_truth", {}).get("dividend_adjusted") is False
    univ = cov.get("universe") or {}
    assert univ.get("inactive_instruments_with_samples", 0) >= 1
    samples3 = {
        (s.instrument_id, s.as_of_date): s
        for s in core_db.scalars(
            select(DatasetSampleDaily).where(DatasetSampleDaily.dataset_run_id == run3.id)
        )
    }
    samples4 = {
        (s.instrument_id, s.as_of_date): s
        for s in core_db.scalars(
            select(DatasetSampleDaily).where(DatasetSampleDaily.dataset_run_id == run4.id)
        )
    }
    assert set(samples3) == set(samples4)
    dead_dates = {d for iid, d in samples4 if iid == fx["dead"].id}
    assert dead_dates
    assert all(d <= date(2024, 6, 28) for d in dead_dates)
    for key, s3 in samples3.items():
        s4 = samples4[key]
        assert s3.labels.get("forward_return_1d") == s4.labels.get("forward_return_1d")
        assert s3.labels.get("forward_return_20d") == s4.labels.get("forward_return_20d")
        feats = dict(s4.features or {})
        assert "eligible_to" not in feats
        assert "forward_return_1d" not in feats
        for name in V4_FUNDAMENTAL_FEATURE_NAMES:
            if feats.get(name) is None:
                continue
            assert feats[name] != 0 or name == "fund_has_recent_report"
        lin = (s4.lineage or {}).get("v4_enrichment") or (s4.metadata or {}).get("v4_enrichment")
        assert lin is not None


def test_v4_instrument_ids_cannot_bypass_eligibility(core_db: Session) -> None:
    _bind_flush_only(core_db)
    fx = _seed_v3_fixture(core_db)
    result = PITDatasetBuilder(core_db).run_build(
        date_from=date(2024, 12, 1),
        date_to=date(2024, 12, 5),
        dataset_spec_version=PIT_DAILY_CORE_V4_VERSION,
        instrument_ids=[fx["new"].id],
        seed_specs=False,
    )
    samples = list(
        core_db.scalars(
            select(DatasetSampleDaily).where(
                DatasetSampleDaily.dataset_run_id == result["dataset_run_id"]
            )
        )
    )
    assert samples == []


def test_v4_deterministic_rebuild_and_query_bound(core_db: Session) -> None:
    _bind_flush_only(core_db)
    fx = _seed_v3_fixture(core_db)
    ids = [fx["aaa"].id, fx["dead"].id]
    b = PITDatasetBuilder(core_db)
    r1 = b.run_build(
        date_from=date(2024, 5, 6),
        date_to=date(2024, 5, 20),
        dataset_spec_version=PIT_DAILY_CORE_V4_VERSION,
        instrument_ids=ids,
        seed_specs=False,
    )
    r2 = b.run_build(
        date_from=date(2024, 5, 6),
        date_to=date(2024, 5, 20),
        dataset_spec_version=PIT_DAILY_CORE_V4_VERSION,
        instrument_ids=ids,
        seed_specs=False,
    )
    assert r1["values_hash"] == r2["values_hash"]
    assert r1["dataset_hash"] == r2["dataset_hash"]
    run = core_db.get(DatasetRun, r1["dataset_run_id"])
    q = ((run.coverage_summary or {}).get("v4") or {}).get("preload_query_count")
    assert q is not None
    assert q <= 8


def test_v4_preload_query_count_bounded(core_db: Session) -> None:
    _require_fundamentals(core_db)
    _bind_flush_only(core_db)
    fx = _seed_v3_fixture(core_db)
    index = load_v4_enrichment_index(core_db, instrument_ids=[fx["aaa"].id, fx["dead"].id])
    assert index.query_count <= 8
    assert index.query_count >= 1


def test_v4_hash_changes_when_fundamental_value_changes(core_db: Session) -> None:
    _require_fundamentals(core_db)
    _bind_flush_only(core_db)
    fx = _seed_v3_fixture(core_db)
    inst = fx["aaa"]
    issuer = Issuer(title=f"ISS-{uuid4().hex[:6]}", moex_emitent_id=9_001_111)
    core_db.add(issuer)
    core_db.flush()
    core_db.add(
        SecurityIssuerMapping(
            instrument_id=inst.id,
            issuer_id=issuer.id,
            valid_from=date(2020, 1, 1),
            valid_to=None,
            source="FIXTURE",
            mapping_status=MappingStatus.MAPPED.value,
        )
    )
    report = FinancialReport(
        issuer_id=issuer.id,
        reporting_standard="IFRS",
        period_type="FY",
        period_end=date(2023, 12, 31),
        known_at=date(2024, 3, 1),
        source="FIXTURE",
        report_version=1,
        currency="RUB",
        unit_scale="units",
    )
    core_db.add(report)
    core_db.flush()
    ni = FinancialFact(
        report_id=report.id,
        metric_code="NET_INCOME",
        value=100.0,
        currency="RUB",
        unit_scale="units",
        normalization_status=NormalizationStatus.NORMALIZED.value,
    )
    rev = FinancialFact(
        report_id=report.id,
        metric_code="REVENUE",
        value=1000.0,
        currency="RUB",
        unit_scale="units",
        normalization_status=NormalizationStatus.NORMALIZED.value,
    )
    core_db.add_all([ni, rev])
    core_db.flush()
    builder = PITDatasetBuilder(core_db)
    first = builder.run_build(
        date_from=date(2024, 5, 6),
        date_to=date(2024, 5, 10),
        dataset_spec_version=PIT_DAILY_CORE_V4_VERSION,
        instrument_ids=[inst.id],
        seed_specs=False,
    )
    ni.value = 250.0
    core_db.flush()
    second = builder.run_build(
        date_from=date(2024, 5, 6),
        date_to=date(2024, 5, 10),
        dataset_spec_version=PIT_DAILY_CORE_V4_VERSION,
        instrument_ids=[inst.id],
        seed_specs=False,
    )
    assert first["values_hash"] != second["values_hash"]


def test_v4_db_restatement_and_dividend_lookahead(core_db: Session) -> None:
    _require_fundamentals(core_db)
    _bind_flush_only(core_db)
    fx = _seed_v3_fixture(core_db)
    inst = fx["aaa"]
    issuer = Issuer(title=f"ISS-{uuid4().hex[:6]}", moex_emitent_id=9_001_222)
    core_db.add(issuer)
    core_db.flush()
    core_db.add(
        SecurityIssuerMapping(
            instrument_id=inst.id,
            issuer_id=issuer.id,
            valid_from=date(2020, 1, 1),
            source="FIXTURE",
            mapping_status=MappingStatus.MAPPED.value,
        )
    )
    original = FinancialReport(
        issuer_id=issuer.id,
        reporting_standard="IFRS",
        period_type="FY",
        period_end=date(2023, 12, 31),
        known_at=date(2024, 3, 20),
        source="FIXTURE",
        report_version=1,
        currency="RUB",
        unit_scale="units",
    )
    restated = FinancialReport(
        issuer_id=issuer.id,
        reporting_standard="IFRS",
        period_type="FY",
        period_end=date(2023, 12, 31),
        known_at=date(2024, 6, 10),
        source="FIXTURE",
        report_version=2,
        is_restatement=True,
        currency="RUB",
        unit_scale="units",
    )
    core_db.add_all([original, restated])
    core_db.flush()
    core_db.add_all(
        [
            FinancialFact(
                report_id=original.id,
                metric_code="NET_INCOME",
                value=100.0,
                currency="RUB",
                unit_scale="units",
                normalization_status=NormalizationStatus.NORMALIZED.value,
            ),
            FinancialFact(
                report_id=original.id,
                metric_code="REVENUE",
                value=1000.0,
                currency="RUB",
                unit_scale="units",
                normalization_status=NormalizationStatus.NORMALIZED.value,
            ),
            FinancialFact(
                report_id=restated.id,
                metric_code="NET_INCOME",
                value=400.0,
                currency="RUB",
                unit_scale="units",
                normalization_status=NormalizationStatus.NORMALIZED.value,
            ),
            FinancialFact(
                report_id=restated.id,
                metric_code="REVENUE",
                value=1000.0,
                currency="RUB",
                unit_scale="units",
                normalization_status=NormalizationStatus.NORMALIZED.value,
            ),
            DividendEvent(
                issuer_id=issuer.id,
                instrument_id=inst.id,
                announcement_date=date(2024, 5, 15),
                known_at=date(2024, 5, 15),
                record_date=date(2024, 6, 20),
                amount_per_share=3.0,
                currency="RUB",
                status=DividendStatus.RECOMMENDED.value,
                source="FIXTURE",
                version=1,
            ),
            CorporateEvent(
                issuer_id=issuer.id,
                instrument_id=inst.id,
                event_type=CorporateEventType.SPLIT.value,
                event_date=date(2024, 4, 1),
                known_at=date(2024, 4, 1),
                source="FIXTURE",
            ),
        ]
    )
    core_db.flush()
    for day in (date(2024, 6, 10), date(2024, 6, 11), date(2024, 6, 12), date(2024, 6, 13), date(2024, 6, 14)):
        if day.weekday() >= 5:
            continue
        _add_candle(core_db, inst.id, day, close=140.0)
        _add_basic(core_db, instrument_id=inst.id, day=day, feature_set_id=fx["basic"].id)
    core_db.flush()
    result = PITDatasetBuilder(core_db).run_build(
        date_from=date(2024, 5, 6),
        date_to=date(2024, 6, 14),
        dataset_spec_version=PIT_DAILY_CORE_V4_VERSION,
        instrument_ids=[inst.id],
        seed_specs=False,
    )
    samples = {
        s.as_of_date: s
        for s in core_db.scalars(
            select(DatasetSampleDaily).where(
                DatasetSampleDaily.dataset_run_id == result["dataset_run_id"]
            )
        )
    }
    mid = samples[date(2024, 5, 6)]
    late = samples[date(2024, 6, 14)]
    assert mid.features.get("fund_net_margin") == pytest.approx(0.1)
    assert late.features.get("fund_net_margin") == pytest.approx(0.4)
    assert mid.features.get("event_has_known_upcoming_dividend") is None
    after_dates = sorted(d for d in samples if d >= date(2024, 5, 15))
    assert after_dates
    assert samples[after_dates[0]].features.get("event_has_known_upcoming_dividend") == 1.0
    assert late.features.get("event_days_since_last_split") is not None


def test_compare_v3_v4_fair_and_does_not_activate(core_db: Session) -> None:
    _bind_flush_only(core_db)
    fx = _seed_v3_fixture(core_db)
    artifact = compare_v3_v4_builds(
        core_db,
        date_from=date(2024, 5, 6),
        date_to=date(2024, 5, 20),
        instrument_ids=[fx["aaa"].id, fx["dead"].id],
        rebuild=True,
    )
    assert artifact["sample_diff"]["fair_contract_status"] == "PASS"
    assert artifact["active_dataset_spec"]["unchanged"] is True
    joined = " ".join(artifact["interpretation"]).lower()
    assert "v4 wins" not in joined
    assert "does not say that v4 is better" in joined
    assert artifact["feature_manifest_delta"]["added_count"] > 0


def test_research_loader_v4_missing_is_nan_not_zero(core_db: Session) -> None:
    _bind_flush_only(core_db)
    fx = _seed_v3_fixture(core_db)
    result = PITDatasetBuilder(core_db).run_build(
        date_from=date(2024, 5, 6),
        date_to=date(2024, 5, 10),
        dataset_spec_version=PIT_DAILY_CORE_V4_VERSION,
        instrument_ids=[fx["aaa"].id],
        seed_specs=False,
    )
    _, frame = load_research_frame(
        core_db,
        dataset_spec_version=4,
        dataset_run_id=result["dataset_run_id"],
    )
    assert ALLOWED_RESEARCH_VERSIONS == frozenset({2, 3, 4})
    col = frame["fund_net_margin"]
    assert col.isna().all()
    assert not bool((col == 0.0).any())
    assert np.isnan(col.iloc[0])


def test_experimental_oos_forbids_registry_persist_v4(core_db: Session) -> None:
    with pytest.raises(ValueError, match="must not persist"):
        run_experimental_v2_v3_oos(
            core_db,
            dataset_spec_version=4,
            persist_registry=True,
        )
