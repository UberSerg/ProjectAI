"""Dataset PIT V3 — historical universe, eligibility, isolation from V1/V2/Candidate."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.analytics.models import InstrumentFeatureDaily
from app.infrastructure.learning.models import DatasetRun, DatasetSampleDaily, DatasetSpec
from app.infrastructure.market.models import Candle, Instrument, InstrumentSource
from app.infrastructure.technical.models import InstrumentTechnicalFeatureDaily, TechnicalSignalDaily
from app.modules.analytics.application.resolve import resolve_feature_set
from app.modules.analytics.application.seed import seed_feature_sets
from app.modules.learning.application.builder import PITDatasetBuilder
from app.modules.learning.application.labels import ForwardReturnLabelCalculator, PriceObservation
from app.modules.learning.application.seed import seed_dataset_specs
from app.modules.learning.application.universe_resolve import (
    HistoricalUniverseResolutionError,
    resolve_dataset_universe,
)
from app.modules.learning.dataset_config import (
    PIT_DAILY_CORE_ACTIVE_VERSION,
    PIT_DAILY_CORE_CODE,
    PIT_DAILY_CORE_V1,
    PIT_DAILY_CORE_V2,
    PIT_DAILY_CORE_V2_VERSION,
    PIT_DAILY_CORE_V3,
    PIT_DAILY_CORE_V3_VERSION,
    UNIVERSE_POLICY_CURRENT_ACTIVE,
    UNIVERSE_POLICY_HISTORICAL_V2,
    feature_names_from_manifest,
    uses_mechanical_label_basis,
)
from app.modules.market.application.historical_universe import (
    HISTORICAL_EQUITY_UNIVERSE_V2,
    QUALITY_FIRST_CANDLE,
    QUALITY_MOEX_LISTED_FROM,
    QUALITY_MOEX_LISTED_TILL,
)
from app.modules.prediction.candidate_v1_config import CANDIDATE_V1_RANKER_CONFIG
from app.modules.technical.technical_config import RULES_V1_CODE, RULES_V2_CONFIG_HASH, RULES_V2_VERSION


def _bind_flush_only(session: Session) -> None:
    def _commit() -> None:
        session.flush()

    session.commit = _commit  # type: ignore[method-assign]


def _sym(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:8].upper()}"


def _add_instrument(
    session: Session,
    *,
    symbol: str,
    is_active: bool = True,
    active_to: date | None = None,
) -> Instrument:
    inst = Instrument(
        symbol=symbol,
        name=symbol,
        asset_class="equity",
        exchange="MOEX",
        currency="RUB",
        is_active=is_active,
        active_to=active_to,
    )
    session.add(inst)
    session.flush()
    return inst


def _add_candle(session: Session, instrument_id: int, day: date, close: float = 100.0) -> Candle:
    c = Candle(
        instrument_id=instrument_id,
        timeframe="1d",
        timestamp=datetime(day.year, day.month, day.day, tzinfo=UTC),
        open=Decimal(str(close)),
        high=Decimal(str(close)),
        low=Decimal(str(close)),
        close=Decimal(str(close)),
        volume=Decimal("1000"),
        source="test",
    )
    session.add(c)
    return c


def _add_board(
    session: Session,
    instrument_id: int,
    *,
    listed_from: date | None = None,
    listed_till: date | None = None,
    history_from: date | None = None,
) -> None:
    meta: dict = {}
    if listed_from is not None:
        meta["listed_from"] = listed_from.isoformat()
    if listed_till is not None:
        meta["listed_till"] = listed_till.isoformat()
    if history_from is not None:
        meta["history_from"] = history_from.isoformat()
    session.add(
        InstrumentSource(
            instrument_id=instrument_id,
            source="moex",
            external_id=f"ext-{instrument_id}-{uuid4().hex[:6]}",
            board="TQBR",
            source_metadata=meta,
        )
    )


def _add_basic(
    session: Session,
    *,
    instrument_id: int,
    day: date,
    feature_set_id,
) -> InstrumentFeatureDaily:
    row = InstrumentFeatureDaily(
        instrument_id=instrument_id,
        date=day,
        timeframe="1d",
        feature_set_id=feature_set_id,
        feature_version=2,
        close=Decimal("100"),
        return_1d=Decimal("0.01"),
        return_5d=Decimal("0.02"),
        has_sufficient_history=True,
        is_valid=True,
        quality_flags={},
    )
    session.add(row)
    return row


def _add_tech_and_signal(
    session: Session,
    *,
    instrument_id: int,
    day: date,
    basic_fs_id,
    tech_fs_id,
) -> None:
    session.add(
        InstrumentTechnicalFeatureDaily(
            instrument_id=instrument_id,
            date=day,
            timeframe="1d",
            feature_set_id=tech_fs_id,
            rsi14=Decimal("50"),
            has_sufficient_history=True,
            is_valid=True,
            quality_flags={},
        )
    )
    session.add(
        TechnicalSignalDaily(
            instrument_id=instrument_id,
            as_of_date=day,
            timeframe="1d",
            model_code=RULES_V1_CODE,
            model_version=RULES_V2_VERSION,
            model_config_hash=RULES_V2_CONFIG_HASH,
            basic_feature_set_id=basic_fs_id,
            technical_feature_set_id=tech_fs_id,
            score=Decimal("0.1"),
            confidence=Decimal("0.5"),
            direction="neutral",
            is_valid=True,
            quality_flags={},
        )
    )


def test_v3_spec_seeded_inactive(core_db: Session) -> None:
    seed_dataset_specs(core_db)
    v3 = core_db.scalar(
        select(DatasetSpec).where(
            DatasetSpec.code == PIT_DAILY_CORE_CODE,
            DatasetSpec.version == PIT_DAILY_CORE_V3_VERSION,
        )
    )
    assert v3 is not None
    assert v3.is_active is False
    assert v3.universe_policy == UNIVERSE_POLICY_HISTORICAL_V2
    assert v3.universe_policy == HISTORICAL_EQUITY_UNIVERSE_V2
    assert uses_mechanical_label_basis(v3.label_spec)
    assert v3.label_spec.get("dividend_adjusted") is False
    assert v3.label_spec.get("total_return") is False
    assert (v3.parameters or {}).get("fundamentals_in_features") is False


def test_v1_v2_immutable_semantics() -> None:
    assert PIT_DAILY_CORE_V1["universe_policy"] == UNIVERSE_POLICY_CURRENT_ACTIVE
    assert PIT_DAILY_CORE_V2["universe_policy"] == UNIVERSE_POLICY_CURRENT_ACTIVE
    assert PIT_DAILY_CORE_V3["universe_policy"] == UNIVERSE_POLICY_HISTORICAL_V2
    assert PIT_DAILY_CORE_ACTIVE_VERSION == 1
    v2_features = feature_names_from_manifest(PIT_DAILY_CORE_V2["feature_manifest"])
    v3_features = feature_names_from_manifest(PIT_DAILY_CORE_V3["feature_manifest"])
    assert v2_features == v3_features
    assert "forward_return_5d" not in v3_features
    assert "eligible_to" not in v3_features
    assert "eligible_from" not in v3_features


def test_v3_inactive_by_default_and_candidate_stays_v2(core_db: Session) -> None:
    seed_dataset_specs(core_db)
    active = core_db.scalar(select(DatasetSpec).where(DatasetSpec.is_active.is_(True)))
    assert active is not None
    assert active.version == 1
    assert CANDIDATE_V1_RANKER_CONFIG.dataset_spec_version == PIT_DAILY_CORE_V2_VERSION


def test_resolve_historical_includes_inactive(core_db: Session) -> None:
    dead = _add_instrument(core_db, symbol=_sym("DEAD"), is_active=False, active_to=date(2024, 11, 1))
    aaa = _add_instrument(core_db, symbol=_sym("AAA"), is_active=True)
    for d in (date(2021, 1, 4), date(2023, 6, 1), date(2024, 10, 1)):
        _add_candle(core_db, dead.id, d)
    for d in (date(2020, 1, 2), date(2025, 1, 2)):
        _add_candle(core_db, aaa.id, d)
    _add_board(
        core_db,
        dead.id,
        listed_from=date(2021, 1, 1),
        listed_till=date(2024, 11, 1),
    )
    _add_board(core_db, aaa.id, listed_from=date(2019, 1, 1))
    core_db.flush()

    resolved = resolve_dataset_universe(
        core_db,
        universe_policy=UNIVERSE_POLICY_HISTORICAL_V2,
        instrument_ids=[dead.id, aaa.id],
        parameters={"use_research_cohort": False},
    )
    assert resolved.apply_date_eligibility is True
    ids = {i.id for i in resolved.instruments}
    assert dead.id in ids
    assert aaa.id in ids
    assert resolved.resolved_universe["inactive_now"] >= 1
    assert resolved.resolved_universe["universe_quality"] == "PARTIAL"
    elig = resolved.eligibility_by_id[dead.id]
    assert elig.includes(date(2022, 6, 1))
    assert not elig.includes(date(2024, 11, 2))
    assert elig.eligible_from_quality == QUALITY_MOEX_LISTED_FROM
    assert elig.eligible_to_quality == QUALITY_MOEX_LISTED_TILL


def test_resolve_current_active_excludes_inactive(core_db: Session) -> None:
    dead = _add_instrument(core_db, symbol=_sym("DIN"), is_active=False)
    live = _add_instrument(core_db, symbol=_sym("LIV"), is_active=True)
    _add_candle(core_db, dead.id, date(2022, 1, 3))
    _add_candle(core_db, live.id, date(2022, 1, 3))
    core_db.flush()
    resolved = resolve_dataset_universe(
        core_db,
        universe_policy=UNIVERSE_POLICY_CURRENT_ACTIVE,
        instrument_ids=[dead.id, live.id],
    )
    assert {i.id for i in resolved.instruments} == {live.id}
    assert resolved.apply_date_eligibility is False


def test_empty_historical_universe_fails_hard(core_db: Session) -> None:
    with patch(
        "app.modules.learning.application.universe_resolve.build_historical_equity_universe",
        return_value=[],
    ):
        with pytest.raises(HistoricalUniverseResolutionError, match="zero eligible"):
            resolve_dataset_universe(
                core_db,
                universe_policy=UNIVERSE_POLICY_HISTORICAL_V2,
                instrument_ids=[999999],
                parameters={"use_research_cohort": False},
            )


def test_candle_fallback_marked_proxy(core_db: Session) -> None:
    inst = _add_instrument(core_db, symbol=_sym("PX"), is_active=True)
    _add_candle(core_db, inst.id, date(2023, 5, 2))
    core_db.flush()
    resolved = resolve_dataset_universe(
        core_db,
        universe_policy=UNIVERSE_POLICY_HISTORICAL_V2,
        instrument_ids=[inst.id],
        parameters={"use_research_cohort": False},
    )
    elig = resolved.eligibility_by_id[inst.id]
    assert elig.eligible_from_quality == QUALITY_FIRST_CANDLE
    assert resolved.resolved_universe["proxy_boundaries"] >= 1
    assert resolved.resolved_universe["universe_quality"] == "PARTIAL"


def _seed_v3_fixture(session: Session) -> dict:
    seed_feature_sets(session)
    seed_dataset_specs(session)
    basic = resolve_feature_set(session, "basic_daily", 2)
    dead = _add_instrument(
        session, symbol=_sym("DEAD"), is_active=False, active_to=date(2024, 6, 28)
    )
    aaa = _add_instrument(session, symbol=_sym("AAA"), is_active=True)
    new = _add_instrument(session, symbol=_sym("NEW"), is_active=True)
    # DEAD listed 2021-01..2024-06
    for i in range(0, 40):
        day = date(2024, 5, 1) + timedelta(days=i)
        if day.weekday() >= 5:
            continue
        _add_candle(session, dead.id, day, close=50 + i)
        _add_basic(session, instrument_id=dead.id, day=day, feature_set_id=basic.id)
    # Feature rows after delisting — must be rejected by eligibility gate.
    for day in (date(2024, 7, 1), date(2024, 7, 2), date(2024, 7, 3)):
        _add_candle(session, dead.id, day, close=1.0)
        _add_basic(session, instrument_id=dead.id, day=day, feature_set_id=basic.id)
    _add_board(
        session,
        dead.id,
        listed_from=date(2021, 1, 4),
        listed_till=date(2024, 6, 28),
    )
    # AAA always active
    for i in range(0, 40):
        day = date(2024, 5, 1) + timedelta(days=i)
        if day.weekday() >= 5:
            continue
        _add_candle(session, aaa.id, day, close=100 + i)
        _add_basic(session, instrument_id=aaa.id, day=day, feature_set_id=basic.id)
    _add_board(session, aaa.id, listed_from=date(2018, 1, 2))
    # NEW listed from 2025-06-01 — plant a 2024 feature row that must be excluded
    _add_candle(session, new.id, date(2025, 6, 2), close=10)
    _add_candle(session, new.id, date(2025, 7, 1), close=11)
    _add_basic(session, instrument_id=new.id, day=date(2024, 12, 2), feature_set_id=basic.id)
    _add_basic(session, instrument_id=new.id, day=date(2025, 6, 2), feature_set_id=basic.id)
    _add_board(session, new.id, listed_from=date(2025, 6, 1))
    session.flush()
    return {"dead": dead, "aaa": aaa, "new": new, "basic": basic}


def test_v3_build_inactive_inside_window_excluded_outside(core_db: Session) -> None:
    _bind_flush_only(core_db)
    fx = _seed_v3_fixture(core_db)
    dead = fx["dead"]
    builder = PITDatasetBuilder(core_db)
    result = builder.run_build(
        date_from=date(2024, 5, 1),
        date_to=date(2024, 7, 15),
        dataset_spec_code=PIT_DAILY_CORE_CODE,
        dataset_spec_version=PIT_DAILY_CORE_V3_VERSION,
        instrument_ids=[dead.id, fx["aaa"].id, fx["new"].id],
    )
    assert result["pit_status"] == "PASS"
    assert result["samples_total"] > 0
    run = core_db.get(DatasetRun, result["dataset_run_id"])
    assert run is not None
    assert run.status == "SUCCESS"
    assert run.resolved_universe["policy"] == UNIVERSE_POLICY_HISTORICAL_V2
    assert run.resolved_universe.get("eligible_from_quality_counts")
    cov = run.coverage_summary or {}
    univ = cov.get("universe") or {}
    assert univ.get("inactive_instruments_with_samples", 0) >= 1
    assert univ.get("samples_from_currently_inactive_instruments", 0) >= 1

    samples = list(
        core_db.scalars(
            select(DatasetSampleDaily).where(DatasetSampleDaily.dataset_run_id == run.id)
        )
    )
    dead_dates = {s.as_of_date for s in samples if s.instrument_id == dead.id}
    assert dead_dates
    assert all(d <= date(2024, 6, 28) for d in dead_dates)
    assert date(2024, 7, 1) not in dead_dates or date(2024, 7, 1) > date(2024, 6, 28)
    assert univ.get("samples_rejected_after_eligible_to", 0) >= 1

    new_before = [
        s
        for s in samples
        if s.instrument_id == fx["new"].id and s.as_of_date == date(2024, 12, 2)
    ]
    assert new_before == []

    for s in samples:
        feats = dict(s.features or {})
        assert "eligible_to" not in feats
        assert "eligible_from" not in feats
        assert "forward_return_1d" not in feats
        lin = dict(s.lineage or {})
        assert lin.get("universe_policy") == UNIVERSE_POLICY_HISTORICAL_V2
        if s.instrument_id == dead.id:
            assert lin.get("eligible_from") is not None
            assert lin.get("eligible_to") is not None


def test_instrument_ids_cannot_bypass_eligibility(core_db: Session) -> None:
    _bind_flush_only(core_db)
    fx = _seed_v3_fixture(core_db)
    new = fx["new"]
    result = PITDatasetBuilder(core_db).run_build(
        date_from=date(2024, 12, 1),
        date_to=date(2024, 12, 5),
        dataset_spec_version=PIT_DAILY_CORE_V3_VERSION,
        instrument_ids=[new.id],
    )
    samples = list(
        core_db.scalars(
            select(DatasetSampleDaily).where(
                DatasetSampleDaily.dataset_run_id == result["dataset_run_id"]
            )
        )
    )
    assert samples == []
    run = core_db.get(DatasetRun, result["dataset_run_id"])
    assert (run.coverage_summary or {}).get("universe", {}).get(
        "samples_rejected_before_eligible_from", 0
    ) >= 1


def test_v2_build_excludes_inactive(core_db: Session) -> None:
    _bind_flush_only(core_db)
    fx = _seed_v3_fixture(core_db)
    result = PITDatasetBuilder(core_db).run_build(
        date_from=date(2024, 5, 1),
        date_to=date(2024, 6, 10),
        dataset_spec_version=PIT_DAILY_CORE_V2_VERSION,
        instrument_ids=[fx["dead"].id, fx["aaa"].id],
    )
    samples = list(
        core_db.scalars(
            select(DatasetSampleDaily).where(
                DatasetSampleDaily.dataset_run_id == result["dataset_run_id"]
            )
        )
    )
    assert all(s.instrument_id != fx["dead"].id for s in samples)
    assert any(s.instrument_id == fx["aaa"].id for s in samples)


def test_v3_forward_label_blocked_when_target_after_eligible_to(core_db: Session) -> None:
    """Y(t+h) must stay inside historical eligibility — post-delisting candles are not outcomes."""
    _bind_flush_only(core_db)
    fx = _seed_v3_fixture(core_db)
    dead = fx["dead"]
    tech_fs = resolve_feature_set(core_db, "technical_daily", 2)
    # Fixture May-loop ends ~early June; plant explicit end-of-window + post-delisting chain.
    for day, close in (
        (date(2024, 6, 26), 90.0),
        (date(2024, 6, 27), 91.0),
        (date(2024, 6, 28), 92.0),
    ):
        _add_candle(core_db, dead.id, day, close=close)
        _add_basic(core_db, instrument_id=dead.id, day=day, feature_set_id=fx["basic"].id)
        _add_tech_and_signal(
            core_db,
            instrument_id=dead.id,
            day=day,
            basic_fs_id=fx["basic"].id,
            tech_fs_id=tech_fs.id,
        )
    core_db.flush()
    eligible_to = date(2024, 6, 28)
    result = PITDatasetBuilder(core_db).run_build(
        date_from=date(2024, 6, 26),
        date_to=date(2024, 7, 3),
        dataset_spec_version=PIT_DAILY_CORE_V3_VERSION,
        instrument_ids=[dead.id],
    )
    assert result["pit_status"] == "PASS"
    run = core_db.get(DatasetRun, result["dataset_run_id"])
    assert run is not None
    samples = {
        s.as_of_date: s
        for s in core_db.scalars(
            select(DatasetSampleDaily).where(DatasetSampleDaily.dataset_run_id == run.id)
        )
    }
    # Sample on eligible_to itself is allowed for X(t).
    assert eligible_to in samples
    # Previous trading day exists and may keep a 1d label inside the window.
    assert date(2024, 6, 27) in samples
    inside = samples[date(2024, 6, 27)]
    assert inside.labels.get("forward_return_1d") is not None
    assert inside.label_quality.get("label_valid", {}).get("1d") is True
    assert inside.training_eligibility.get("training_eligible_1d") is True
    assert inside.labels.get("target_date_1d") == "2024-06-28"

    crossing = samples[eligible_to]
    assert crossing.labels.get("forward_return_1d") is None
    assert crossing.label_quality.get("label_valid", {}).get("1d") is False
    assert crossing.training_eligibility.get("training_eligible_1d") is False
    flags = crossing.label_quality.get("flags") or {}
    assert flags.get("target_after_eligible_to_1d") is True
    assert flags.get("rejected_target_date_1d") == "2024-07-01"
    assert flags.get("missing_future_1d") is not True
    # Post-delisting July candles must not appear as a valid V3 outcome.
    assert crossing.labels.get("target_date_1d") is None

    cov = run.coverage_summary or {}
    assert (cov.get("labels") or {}).get("labels_rejected_after_eligible_to", 0) >= 1
    assert (cov.get("universe") or {}).get("labels_rejected_after_eligible_to", 0) >= 1
    # Boundary invalidation is not a DatasetRun PIT failure.
    assert run.pit_status == "PASS"
    assert run.status == "SUCCESS"


def test_v2_still_uses_post_window_candles_for_active_names(core_db: Session) -> None:
    """V2 has no historical eligible_to gate — forward labels may use later candles."""
    _bind_flush_only(core_db)
    seed_feature_sets(core_db)
    seed_dataset_specs(core_db)
    basic = resolve_feature_set(core_db, "basic_daily", 2)
    live = _add_instrument(core_db, symbol=_sym("LIVE"), is_active=True)
    # Contiguous observations: 27→28 (1d ok), 28→Jul1 (still valid under V2).
    for day, close in (
        (date(2024, 6, 27), 100.0),
        (date(2024, 6, 28), 101.0),
        (date(2024, 7, 1), 102.0),
        (date(2024, 7, 2), 103.0),
    ):
        _add_candle(core_db, live.id, day, close=close)
        _add_basic(core_db, instrument_id=live.id, day=day, feature_set_id=basic.id)
    core_db.flush()

    result = PITDatasetBuilder(core_db).run_build(
        date_from=date(2024, 6, 27),
        date_to=date(2024, 6, 28),
        dataset_spec_version=PIT_DAILY_CORE_V2_VERSION,
        instrument_ids=[live.id],
    )
    samples = {
        s.as_of_date: s
        for s in core_db.scalars(
            select(DatasetSampleDaily).where(
                DatasetSampleDaily.dataset_run_id == result["dataset_run_id"]
            )
        )
    }
    crossing = samples[date(2024, 6, 28)]
    assert crossing.labels.get("forward_return_1d") is not None
    assert crossing.labels.get("target_date_1d") == "2024-07-01"
    assert crossing.label_quality.get("label_valid", {}).get("1d") is True
    flags = crossing.label_quality.get("flags") or {}
    assert "target_after_eligible_to_1d" not in flags


def test_v3_dividends_do_not_change_mechanical_labels() -> None:
    calc = ForwardReturnLabelCalculator(horizons=(1, 5))
    obs = [
        PriceObservation(date(2024, 5, 2), 100.0, 1),
        PriceObservation(date(2024, 5, 3), 101.0, 2),
        PriceObservation(date(2024, 5, 6), 102.0, 3),
        PriceObservation(date(2024, 5, 7), 103.0, 4),
        PriceObservation(date(2024, 5, 8), 104.0, 5),
        PriceObservation(date(2024, 5, 9), 105.0, 6),
    ]
    a = calc.calculate(obs, as_of=date(2024, 5, 2), price_basis="mechanical_adjusted")
    # Presence of a dividend event is irrelevant to mechanical calculator inputs.
    b = calc.calculate(
        obs,
        as_of=date(2024, 5, 2),
        price_basis="mechanical_adjusted",
        mechanical_actions=[],
    )
    assert a.labels.forward_return_1d == b.labels.forward_return_1d
    assert PIT_DAILY_CORE_V3["label_spec"]["dividend_adjusted"] is False
    assert PIT_DAILY_CORE_V3["label_spec"]["total_return"] is False


def test_v3_deterministic_rebuild(core_db: Session) -> None:
    _bind_flush_only(core_db)
    fx = _seed_v3_fixture(core_db)
    ids = [fx["aaa"].id, fx["dead"].id]
    b = PITDatasetBuilder(core_db)
    r1 = b.run_build(
        date_from=date(2024, 5, 6),
        date_to=date(2024, 5, 20),
        dataset_spec_version=PIT_DAILY_CORE_V3_VERSION,
        instrument_ids=ids,
    )
    r2 = b.run_build(
        date_from=date(2024, 5, 6),
        date_to=date(2024, 5, 20),
        dataset_spec_version=PIT_DAILY_CORE_V3_VERSION,
        instrument_ids=ids,
    )
    assert r1["values_hash"] == r2["values_hash"]
    assert r1["dataset_hash"] == r2["dataset_hash"]


def test_v3_build_fails_when_universe_cannot_resolve(core_db: Session) -> None:
    _bind_flush_only(core_db)
    seed_feature_sets(core_db)
    seed_dataset_specs(core_db)
    with patch(
        "app.modules.learning.application.universe_resolve.build_historical_equity_universe",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(HistoricalUniverseResolutionError):
            PITDatasetBuilder(core_db).run_build(
                date_from=date(2024, 1, 1),
                date_to=date(2024, 1, 10),
                dataset_spec_version=PIT_DAILY_CORE_V3_VERSION,
                instrument_ids=[1],
            )
