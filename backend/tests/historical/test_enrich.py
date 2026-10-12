"""Deterministic historical enrichment: YoY, industrial ratios, valuation."""

from datetime import date, timedelta

from app.modules.historical.application.enrich import (
    DERIVED_NOT_SOURCE,
    YOY_NORMALIZATION_VERSION,
    derive_valuation,
    enrich,
    industrial_ratio_allowed,
    industrial_ratios,
    year_over_year,
)
from app.modules.historical.domain.evidence import ParsedObservation, RecordQuality

_INDUSTRIAL = {"inn": "7700000001", "issuer_kind": "INDUSTRIAL"}
_OTHER = {"inn": "7700000002", "issuer_kind": "INDUSTRIAL"}
_BANK = {"inn": "7707083893", "issuer_kind": "BANK_FI"}
_YEAR = date(2023, 12, 31)


def _obs(**overrides: object) -> ParsedObservation:
    base: dict[str, object] = {
        "metric_id": "REVENUE",
        "source_id": "FNS-01",
        "content_hash": "hash-revenue-2023",
        "normalization_version": "fns_ras_v1",
        "quality_status": RecordQuality.ACCEPTED,
        "value": 100.0,
        "unit": "RUB",
        "currency": "RUB",
        "period": "2023",
        "period_end": _YEAR,
        "reporting_standard": "RAS",
        "issuer_identity": dict(_INDUSTRIAL),
        "evidence": "statement-row",
        "limitations": (),
        "extra": {},
    }
    base.update(overrides)
    return ParsedObservation(**base)  # type: ignore[arg-type]


def _later(days: int, **overrides: object) -> ParsedObservation:
    end = _YEAR + timedelta(days=days)
    payload: dict[str, object] = {
        "content_hash": f"hash-revenue-{days}",
        "value": 110.0,
        "period": "2024",
        "period_end": end,
    }
    payload.update(overrides)
    return _obs(**payload)


def test_industrial_ratio_allowed_is_false_for_banks() -> None:
    assert industrial_ratio_allowed(_BANK) is False
    assert industrial_ratio_allowed({"issuer_kind": " bank_fi "}) is False
    assert industrial_ratio_allowed(_INDUSTRIAL) is True
    assert industrial_ratio_allowed({"inn": "7700000001"}) is True
    assert industrial_ratio_allowed({}) is True


def test_year_over_year_for_same_issuer_inside_window() -> None:
    prior = _obs()
    current = _later(365)
    derived = year_over_year((prior, current))

    assert len(derived) == 1
    row = derived[0]
    assert row.metric_id == "REVENUE.yoy"
    assert row.normalization_version == YOY_NORMALIZATION_VERSION
    assert row.value == 0.1
    assert row.limitations == (DERIVED_NOT_SOURCE,)
    assert row.extra["input_hashes"] == (prior.content_hash, current.content_hash)
    assert row.issuer_identity == _INDUSTRIAL
    assert row.period_end == current.period_end
    assert row.quality_errors() == ()
    assert prior.metric_id == "REVENUE"
    assert current.metric_id == "REVENUE"
    assert row not in (prior, current)


def test_year_over_year_accepts_window_edges_and_rejects_outside() -> None:
    prior = _obs()
    assert len(year_over_year((prior, _later(350)))) == 1
    assert len(year_over_year((prior, _later(380)))) == 1
    assert year_over_year((prior, _later(349))) == ()
    assert year_over_year((prior, _later(381))) == ()


def test_year_over_year_does_not_cross_issuers() -> None:
    prior = _obs(content_hash="left-prior")
    other_current = _later(365, issuer_identity=dict(_OTHER), content_hash="right-current", value=999.0)
    assert year_over_year((prior, other_current)) == ()

    left_current = _later(365, content_hash="left-current", value=150.0)
    right_prior = _obs(
        issuer_identity=dict(_OTHER),
        content_hash="right-prior",
        value=200.0,
    )
    right_current = _later(
        365,
        issuer_identity=dict(_OTHER),
        content_hash="right-current",
        value=250.0,
    )
    derived = year_over_year((prior, left_current, right_prior, right_current))
    by_issuer = {row.issuer_identity["inn"]: row.value for row in derived}
    assert by_issuer == {"7700000001": 0.5, "7700000002": 0.25}


def test_year_over_year_does_not_cross_metrics() -> None:
    revenue = _obs()
    ebitda = _later(365, metric_id="EBITDA", content_hash="ebitda-2024", value=40.0)
    assert year_over_year((revenue, ebitda)) == ()


def test_missing_or_zero_prior_emits_no_yoy_row() -> None:
    current = _later(365)
    assert year_over_year((_obs(value=None, content_hash="missing"), current)) == ()
    assert year_over_year((current, _obs(value=None, period_end=current.period_end))) == ()
    zero_prior = _obs(value=0.0, limitations=("explicit_zero",), content_hash="zero-prior")
    derived = year_over_year((zero_prior, current))
    assert derived == ()
    assert all(row.value != 0 for row in derived)


def test_true_zero_change_is_marked_explicit() -> None:
    prior = _obs(value=80.0, content_hash="flat-prior")
    current = _later(365, value=80.0, content_hash="flat-current")
    row = year_over_year((prior, current))[0]
    assert row.value == 0.0
    assert DERIVED_NOT_SOURCE in row.limitations
    assert "explicit_zero" in row.limitations
    assert row.quality_errors() == ()


def test_closest_prior_to_365_days_wins() -> None:
    current_end = _YEAR + timedelta(days=365)
    current = _obs(
        content_hash="current",
        value=200.0,
        period="2024",
        period_end=current_end,
    )
    near = _obs(content_hash="near", value=100.0, period_end=_YEAR)
    far = _obs(
        content_hash="far",
        value=50.0,
        period_end=current_end - timedelta(days=380),
        period="2022",
    )
    row = year_over_year((far, near, current))[0]
    assert row.value == 1.0
    assert row.extra["input_hashes"] == ("near", "current")


def test_bank_refuses_industrial_ratios() -> None:
    rows = (
        _obs(metric_id="EBITDA", issuer_identity=dict(_BANK), value=30.0, content_hash="e"),
        _obs(metric_id="REVENUE", issuer_identity=dict(_BANK), value=100.0, content_hash="r"),
        _obs(metric_id="TOTAL_DEBT", issuer_identity=dict(_BANK), value=40.0, content_hash="d"),
    )
    assert industrial_ratios(rows) == ()


def test_industrial_ratios_require_both_inputs() -> None:
    revenue = _obs(metric_id="REVENUE", value=100.0, content_hash="revenue")
    ebitda = _obs(metric_id="EBITDA", value=25.0, content_hash="ebitda")
    debt = _obs(metric_id="TOTAL_DEBT", value=50.0, content_hash="debt")
    derived = industrial_ratios((revenue, ebitda, debt))
    by_metric = {row.metric_id: row for row in derived}
    assert set(by_metric) == {
        "EBITDA.over.REVENUE",
        "TOTAL_DEBT.over.EBITDA",
        "TOTAL_DEBT.over.REVENUE",
    }
    assert by_metric["EBITDA.over.REVENUE"].value == 0.25
    assert by_metric["TOTAL_DEBT.over.EBITDA"].value == 2.0
    assert by_metric["TOTAL_DEBT.over.REVENUE"].value == 0.5
    assert by_metric["EBITDA.over.REVENUE"].extra["input_hashes"] == ("ebitda", "revenue")
    assert all(DERIVED_NOT_SOURCE in row.limitations for row in derived)
    assert all(row.quality_errors() == () for row in derived)

    partial = industrial_ratios((revenue, ebitda))
    assert tuple(row.metric_id for row in partial) == ("EBITDA.over.REVENUE",)
    assert industrial_ratios((revenue, _obs(metric_id="EBITDA", value=None, content_hash="no-ebitda"))) == ()

    zero_ebitda = _obs(
        metric_id="EBITDA",
        value=0.0,
        limitations=("explicit_zero",),
        content_hash="zero-ebitda",
    )
    with_zero_ebitda = {row.metric_id: row for row in industrial_ratios((revenue, zero_ebitda, debt))}
    assert set(with_zero_ebitda) == {"EBITDA.over.REVENUE", "TOTAL_DEBT.over.REVENUE"}
    assert with_zero_ebitda["EBITDA.over.REVENUE"].value == 0.0
    assert "explicit_zero" in with_zero_ebitda["EBITDA.over.REVENUE"].limitations


def test_zero_denominator_does_not_invent_a_ratio() -> None:
    revenue = _obs(metric_id="REVENUE", value=0.0, limitations=("explicit_zero",), content_hash="zero-rev")
    ebitda = _obs(metric_id="EBITDA", value=10.0, content_hash="ebitda")
    assert industrial_ratios((revenue, ebitda)) == ()


def test_insufficient_inputs_do_not_emit_a_valuation() -> None:
    cap = _obs(metric_id="MARKET_CAP", value=1_000.0, content_hash="cap")
    assert derive_valuation((cap,)) == ()
    assert derive_valuation((cap, _obs(metric_id="NET_INCOME", value=None, content_hash="missing-ni"))) == ()
    zero_income = _obs(
        metric_id="NET_INCOME",
        value=0.0,
        limitations=("explicit_zero",),
        content_hash="zero-ni",
    )
    assert derive_valuation((cap, zero_income)) == ()
    negative_income = _obs(metric_id="NET_INCOME", value=-20.0, content_hash="loss")
    assert derive_valuation((cap, negative_income)) == ()
    assert all(row.metric_id != "valuation.pe" or row.value != 0 for row in derive_valuation((cap, zero_income)))


def test_valuation_when_market_cap_and_net_income_exist() -> None:
    cap = _obs(metric_id="MARKET_CAP", value=1_000.0, content_hash="cap")
    income = _obs(metric_id="NET_INCOME", value=100.0, content_hash="income")
    derived = derive_valuation((cap, income))
    assert len(derived) == 1
    row = derived[0]
    assert row.metric_id == "valuation.pe"
    assert row.normalization_version == "valuation_v1"
    assert row.value == 10.0
    assert row.limitations == (DERIVED_NOT_SOURCE,)
    assert row.extra["input_hashes"] == ("cap", "income")
    assert row.quality_errors() == ()


def test_enrich_returns_new_rows_without_overwriting_inputs() -> None:
    prior = _obs(content_hash="rev-2023", value=100.0)
    current = _later(366, content_hash="rev-2024", value=120.0)
    ebitda_prior = _obs(metric_id="EBITDA", value=20.0, content_hash="ebitda-2023")
    ebitda_current = _later(366, metric_id="EBITDA", value=30.0, content_hash="ebitda-2024")
    cap = _later(366, metric_id="MARKET_CAP", value=500.0, content_hash="cap-2024")
    income = _later(366, metric_id="NET_INCOME", value=25.0, content_hash="ni-2024")
    rows = [prior, current, ebitda_prior, ebitda_current, cap, income]
    snapshot = [(row.metric_id, row.value, row.normalization_version, row.content_hash) for row in rows]

    derived = enrich(rows)

    assert [(row.metric_id, row.value, row.normalization_version, row.content_hash) for row in rows] == snapshot
    assert all(source not in derived for source in rows)
    assert {row.metric_id for row in derived} >= {
        "REVENUE.yoy",
        "EBITDA.yoy",
        "EBITDA.over.REVENUE",
        "valuation.pe",
    }
    assert all(DERIVED_NOT_SOURCE in row.limitations for row in derived)
    again = enrich((*rows, *derived))
    assert again == derived


def test_bank_enrichment_keeps_non_industrial_yoy_and_skips_ratios() -> None:
    prior = _obs(
        metric_id="NET_PROFIT",
        issuer_identity=dict(_BANK),
        value=10.0,
        content_hash="np-2023",
    )
    current = _later(
        365,
        metric_id="NET_PROFIT",
        issuer_identity=dict(_BANK),
        value=12.0,
        content_hash="np-2024",
    )
    ebitda = _obs(metric_id="EBITDA", issuer_identity=dict(_BANK), value=5.0, content_hash="e")
    revenue = _obs(metric_id="REVENUE", issuer_identity=dict(_BANK), value=9.0, content_hash="r")
    derived = enrich((prior, current, ebitda, revenue))
    assert [row.metric_id for row in derived] == ["NET_PROFIT.yoy"]
    assert derived[0].value == 0.2
    assert industrial_ratio_allowed(derived[0].issuer_identity) is False


def test_conflicting_values_for_one_period_are_not_averaged() -> None:
    first = _obs(value=100.0, content_hash="a")
    second = _obs(value=180.0, content_hash="b")
    current = _later(365, value=110.0)
    assert year_over_year((first, second, current)) == ()
