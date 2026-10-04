"""Focused tests for ResearchDataSnapshotV1, campaign window, and audit-only refresh."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from app.modules.research_evidence.campaign_refresh import inspect_campaign_coverage, refresh_campaign_data
from app.modules.research_evidence.campaign_snapshot import (
    ALLOWED_AVAILABILITY,
    MISSING_COVERAGE,
    SNAPSHOT_VERSION,
    build_research_data_snapshot,
    data_snapshot_hash,
    write_research_data_snapshot,
)
from app.modules.research_evidence.campaign_window import (
    PRIMARY_DATE_FROM,
    STATUS_INSUFFICIENT,
    STATUS_OK,
    expanding_oos_fold_count,
    latest_mature_20d_as_of,
    resolve_campaign_window,
    sessions_on_calendar,
)


def _weekdays(start: date, count: int) -> list[date]:
    day = start
    out: list[date] = []
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


class _EmptyResult:
    def all(self) -> list[Any]:
        return []

    def mappings(self) -> _EmptyResult:
        return self

    def first(self) -> None:
        return None


class _FakeSession:
    def __init__(self, *, scalar: int | None = 0) -> None:
        self._scalar = scalar

    def scalar(self, _stmt: Any) -> int | None:
        return self._scalar

    def execute(self, _stmt: Any) -> _EmptyResult:
        return _EmptyResult()


class _WeekdayCalendar:
    def is_trading_day(self, day: date) -> bool:
        return day.weekday() < 5


def test_primary_date_from_is_predeclared() -> None:
    assert PRIMARY_DATE_FROM == date(2022, 4, 1)


def test_latest_mature_is_session_count_not_returns() -> None:
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(21)]
    assert latest_mature_20d_as_of(days) == days[0]
    assert latest_mature_20d_as_of(days[:20]) is None
    longer = days + [date(2024, 2, 1)]
    assert latest_mature_20d_as_of(longer) == longer[-21]


def test_calendar_intersection_uses_trading_days_only() -> None:
    priced = [date(2024, 1, 5), date(2024, 1, 6), date(2024, 1, 7)]  # Fri, Sat, Sun
    assert sessions_on_calendar(priced, _WeekdayCalendar()) == [date(2024, 1, 5)]


def test_window_insufficient_when_mature_before_2024_04_01() -> None:
    sessions = _weekdays(date(2022, 4, 1), 80)
    payload = resolve_campaign_window(sessions)
    assert payload["status"] == STATUS_INSUFFICIENT
    assert date.fromisoformat(payload["latest_mature_20d_as_of"]) < date(2024, 4, 1)
    assert "latest_mature_20d_as_of_before_min_viable" in payload["reasons"]
    assert "ic" in payload["derivation"]["excluded"]
    assert payload["primary"]["date_from"] == "2022-04-01"
    assert payload["full_history_diagnostic"]["replaces_primary"] is False


def test_window_insufficient_when_too_short_for_expanding_oos() -> None:
    sessions = _weekdays(date(2022, 4, 1), 560)
    payload = resolve_campaign_window(sessions)
    mature = date.fromisoformat(payload["latest_mature_20d_as_of"])
    assert mature >= date(2024, 4, 1)
    assert expanding_oos_fold_count(date_from=PRIMARY_DATE_FROM, date_to=mature) == 0
    assert payload["status"] == STATUS_INSUFFICIENT
    assert "too_short_for_expanding_oos" in payload["reasons"]
    assert payload["expanding_oos"]["shortened_training"] is False


def test_window_ok_when_mature_allows_existing_expanding_folds() -> None:
    sessions = _weekdays(date(2022, 4, 1), 1100)
    payload = resolve_campaign_window(sessions)
    assert payload["status"] == STATUS_OK
    assert payload["expanding_oos"]["fold_count"] >= 1
    assert payload["primary"]["role"] == "PRIMARY"
    assert payload["full_history_diagnostic"]["role"] == "FULL_HISTORY_DIAGNOSTIC"


def test_snapshot_hash_ignores_created_at_and_timings() -> None:
    base = {
        "schema": SNAPSHOT_VERSION,
        "prices": {"daily_equity_candles": 10},
        "domains": [{"code": "prices", "status": "READY"}],
    }
    a = {**base, "created_at": "2026-01-01T00:00:00+00:00", "query_timing_ms": 12.5, "timings": {"q": 1}}
    b = {**base, "created_at": "2099-12-31T23:59:59+00:00", "query_timing_ms": 99.0, "timings": {"q": 9}}
    assert data_snapshot_hash(a) == data_snapshot_hash(b)
    assert data_snapshot_hash(a) != data_snapshot_hash({**base, "prices": {"daily_equity_candles": 11}})


def test_snapshot_hash_is_key_order_independent() -> None:
    payload = {"schema": SNAPSHOT_VERSION, "prices": {"a": 1, "b": 2}, "created_at": "t"}
    reversed_payload = {"created_at": "t", "prices": {"b": 2, "a": 1}, "schema": SNAPSHOT_VERSION}
    assert data_snapshot_hash(payload) == data_snapshot_hash(reversed_payload)


def test_nan_inf_disk_true_hash(tmp_path: Path) -> None:
    payload = {
        "schema": SNAPSHOT_VERSION,
        "created_at": "2026-10-03T00:00:00+00:00",
        "prices": {"weird": float("nan"), "cap": float("inf"), "n": 3},
    }
    written = write_research_data_snapshot(tmp_path / "snap.json", payload)
    import json

    on_disk = json.loads((tmp_path / "snap.json").read_text(encoding="utf-8"))
    assert on_disk["prices"]["weird"] is None
    assert on_disk["prices"]["cap"] is None
    assert written["data_snapshot_hash"] == data_snapshot_hash(on_disk)
    assert written["data_snapshot_hash"] == on_disk["data_snapshot_hash"]


@patch("app.modules.fundamentals.infrastructure.models.fundamentals_schema_ready", return_value=False)
@patch(
    "app.modules.market.application.historical_universe.summarize_historical_universe",
    return_value={"version": "historical_equity_universe_v2", "members": 4, "instrument_count": 4},
)
@patch("app.modules.fundamentals.application.dividend_provider.get_dividend_provider")
def test_missing_schema_does_not_coerce_to_zero(
    provider_factory: MagicMock,
    _universe: MagicMock,
    _schema: MagicMock,
) -> None:
    provider_factory.return_value.readiness.return_value = {
        "status": "NOT_READY",
        "accepted": False,
        "provider": "NOT_READY",
    }
    window = resolve_campaign_window(_weekdays(date(2022, 4, 1), 1100))
    session = _FakeSession(scalar=None)
    snapshot = build_research_data_snapshot(
        session,  # type: ignore[arg-type]
        created_at=datetime(2026, 10, 3, tzinfo=UTC),
        window=window,
        query_timing_ms=3.14,
    )
    events = snapshot["events"]
    assert events["stored_dividend_disclosures"] is None
    assert events["stored_dividend_disclosures"] != 0
    assert events["empty_store_means"] == MISSING_COVERAGE
    assert "zero dividend" not in str(snapshot).lower()
    domains = {d["code"]: d for d in snapshot["domains"]}
    assert domains["events"]["status"] == "NOT_READY"
    assert domains["fundamentals"]["evidence"]["empty_report_store_means"] == MISSING_COVERAGE
    assert snapshot["data_snapshot_hash"] == data_snapshot_hash({**snapshot, "created_at": "other"})


@patch("app.modules.fundamentals.infrastructure.models.fundamentals_schema_ready", return_value=True)
@patch(
    "app.modules.market.application.historical_universe.summarize_historical_universe",
    return_value={"version": "historical_equity_universe_v2", "members": 8},
)
@patch("app.modules.fundamentals.application.coverage_service.FundamentalCoverageService")
@patch("app.modules.fundamentals.application.dividend_provider.get_dividend_provider")
def test_empty_dividend_rows_are_missing_coverage_not_zero_dividends(
    provider_factory: MagicMock,
    coverage_cls: MagicMock,
    _universe: MagicMock,
    _schema: MagicMock,
) -> None:
    provider_factory.return_value.readiness.return_value = {
        "status": "NOT_READY",
        "accepted": False,
        "provider": "NOT_READY",
    }
    coverage_cls.return_value.store_summary.return_value = {"fns_gir_bo_reports": 0, "ras_reports": 0}
    coverage_cls.return_value.cohort_table.return_value = {
        "industrial_with_reports": 0,
        "bank_unsupported": 2,
        "unmapped": 3,
        "rows": [{"secid": "SBER"}],
    }
    window = resolve_campaign_window(_weekdays(date(2022, 4, 1), 1100))
    snapshot = build_research_data_snapshot(
        _FakeSession(scalar=0),  # type: ignore[arg-type]
        created_at=datetime(2026, 10, 3, tzinfo=UTC),
        window=window,
    )
    assert snapshot["events"]["stored_dividend_disclosures"] == 0
    assert snapshot["events"]["empty_store_means"] == MISSING_COVERAGE
    assert snapshot["events"]["not_implied"] == "NOT_ZERO_OBSERVATION"
    assert snapshot["empty_dividend_rows_mean"] == MISSING_COVERAGE
    assert snapshot["total_return"]["verdict"] == "NOT_READY"
    assert "rows" not in snapshot["fundamentals"]["industrial_report_coverage"]
    statuses = {d["status"] for d in snapshot["domains"]}
    assert statuses <= ALLOWED_AVAILABILITY
    assert "UNKNOWN" not in statuses
    banks = next(d for d in snapshot["domains"] if d["code"] == "fundamentals_banks")
    assert banks["status"] == "NOT_READY"
    for domain in snapshot["domains"]:
        assert domain["alpha_judgment"] is False
        assert domain["availability_only"] is True


@patch("app.modules.fundamentals.infrastructure.models.fundamentals_schema_ready", return_value=True)
@patch(
    "app.modules.market.application.historical_universe.summarize_historical_universe",
    return_value={"version": "historical_equity_universe_v2", "members": 0},
)
@patch("app.modules.fundamentals.application.coverage_service.FundamentalCoverageService")
@patch("app.modules.fundamentals.application.dividend_provider.get_dividend_provider")
def test_insufficient_window_marks_overall_not_ready(
    provider_factory: MagicMock,
    coverage_cls: MagicMock,
    _universe: MagicMock,
    _schema: MagicMock,
) -> None:
    provider_factory.return_value.readiness.return_value = {"status": "NOT_READY", "accepted": False}
    coverage_cls.return_value.store_summary.return_value = {"fns_gir_bo_reports": 1}
    coverage_cls.return_value.cohort_table.return_value = {"industrial_with_reports": 1, "rows": []}
    session = _FakeSession(scalar=5)
    snapshot = build_research_data_snapshot(
        session,  # type: ignore[arg-type]
        window=resolve_campaign_window(_weekdays(date(2022, 4, 1), 40)),
    )
    assert snapshot["campaign_window_status"] == STATUS_INSUFFICIENT
    assert snapshot["overall_availability"] == "NOT_READY"
    assert snapshot["schema"] == SNAPSHOT_VERSION


def test_refresh_dry_run_does_not_call_workflows() -> None:
    called: list[str] = []

    def _boom(_session: Any) -> dict[str, Any]:
        called.append("ran")
        raise AssertionError("dry-run must not call providers")

    with (
        patch(
            "app.modules.research_evidence.campaign_refresh.inspect_campaign_coverage",
            return_value={"daily_equity_candles": 10, "dividend_events": 0},
        ),
        patch(
            "app.modules.research_evidence.campaign_refresh._default_market_update",
            side_effect=_boom,
        ),
        patch(
            "app.modules.research_evidence.campaign_refresh._default_fns",
            side_effect=_boom,
        ),
    ):
        report = refresh_campaign_data(MagicMock(), dry_run=True)

    assert report["dry_run"] is True
    assert called == []
    assert report["before"] == report["after"]
    assert report["invented_scrapers"] is False
    assert report["fabricated_known_at"] is False
    assert report["paid_vendors"] is False
    assert {step["source"] for step in report["steps"]} >= {
        "MOEX_ISS_CANDLES",
        "FNS_GIR_BO",
        "MOEX_ISS_SPLITS",
        "CBR_SERIES",
    }
    assert all(step["status"] in {"DRY_RUN", "COVERED_BY_MARKET_UPDATE"} for step in report["steps"])
    assert all(step["secrets_recorded"] is False for step in report["steps"])


def test_refresh_records_before_after_with_fake_hooks() -> None:
    coverage = {"daily_equity_candles": 10, "fns_gir_bo_reports": 1, "corporate_actions": 2}

    def _inspect(_session: Any) -> dict[str, Any]:
        return dict(coverage)

    def _market(_session: Any) -> dict[str, Any]:
        coverage["daily_equity_candles"] += 4
        return {"inserted": 4, "updated": 1, "api_key": "must-not-leak"}

    def _fns(_session: Any) -> dict[str, Any]:
        coverage["fns_gir_bo_reports"] += 2
        return {"reports_inserted": 2}

    with patch(
        "app.modules.research_evidence.campaign_refresh.inspect_campaign_coverage",
        side_effect=_inspect,
    ):
        report = refresh_campaign_data(
            MagicMock(),
            dry_run=False,
            market_update=_market,
            fns_sync=_fns,
            splits=lambda _s: {"inserted": 0, "updated": 0},
            instrument_master=lambda _s: {"inserted": 0},
        )

    assert report["dry_run"] is False
    assert report["before"]["daily_equity_candles"] == 10
    assert report["after"]["daily_equity_candles"] == 14
    assert report["coverage_delta"]["daily_equity_candles"]["delta"] == 4
    assert report["coverage_delta"]["fns_gir_bo_reports"]["delta"] == 2
    candles_step = next(s for s in report["steps"] if s["source"] == "MOEX_ISS_CANDLES")
    assert "api_key" not in candles_step["result"]
    assert candles_step["rows_inserted"] == 4


@patch("app.modules.fundamentals.infrastructure.models.fundamentals_schema_ready", return_value=False)
def test_inspect_coverage_uses_session_not_network(_schema: MagicMock) -> None:
    payload = inspect_campaign_coverage(_FakeSession(scalar=3))  # type: ignore[arg-type]
    assert payload["daily_equity_candles"] == 3
    assert payload["dividend_events"] is None
    assert payload["empty_dividend_events_mean"] == MISSING_COVERAGE
    assert payload["fundamentals_schema_ready"] is False


def test_campaign_window_module_does_not_import_oos_or_ic() -> None:
    import inspect

    import app.modules.research_evidence.campaign_window as mod

    source = inspect.getsource(mod)
    assert "cross_sectional_ic" not in source
    assert "research_evidence.oos" not in source
    assert "run_research_economics" not in source
