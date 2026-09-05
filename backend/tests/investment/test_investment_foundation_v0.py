from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.modules.investment.application.services import (
    CbrHurdleProvider,
    classify_vanilla_rub_fixed_rate,
    key_rate_audit,
)
from app.modules.investment.domain.allocation import (
    AllocationCandidate,
    AssetSleeve,
    allocate_integer_lots,
)
from app.modules.investment.domain.fixed_income import (
    BondCashflowType,
    BondSupportStatus,
    BondType,
    CreditQualityStatus,
    TransactionCostProfile,
    calculate_bond_purchase,
    real_portfolio_eligible,
)
from app.modules.investment.domain.hurdle import (
    BenchmarkVerdict,
    HurdleQuote,
    KnownAtQuality,
    benchmark_metrics,
    horizon_return,
    piecewise_calendar_accrual,
)


def test_hurdle_formula_and_metrics() -> None:
    annual = 0.21
    assert horizon_return(annual, "1y") == pytest.approx(annual)
    assert horizon_return(annual, "20d") == pytest.approx((1 + annual) ** (20 / 252) - 1)
    metrics = benchmark_metrics(
        strategy_return=0.12, hurdle_return=0.08, costs=0.01, periods=252
    )
    assert metrics.excess_return == pytest.approx(0.04)
    assert metrics.excess_after_costs == pytest.approx(0.03)
    assert metrics.verdict is BenchmarkVerdict.BEATS_HURDLE


def test_piecewise_historical_calendar_accrual() -> None:
    quotes = [
        HurdleQuote(
            date(2026, 1, 1),
            0.10,
            date(2026, 1, 1),
            KnownAtQuality.DATE_ONLY,
            "CBR",
        ),
        HurdleQuote(
            date(2026, 1, 11),
            0.20,
            date(2026, 1, 11),
            KnownAtQuality.DATE_ONLY,
            "CBR",
        ),
    ]
    expected = (1.10 ** (10 / 365)) * (1.20 ** (10 / 365)) - 1
    assert piecewise_calendar_accrual(date(2026, 1, 1), date(2026, 1, 21), quotes) == pytest.approx(
        expected
    )


def test_clean_dirty_nkd_and_fees() -> None:
    purchase = calculate_bond_purchase(
        nominal=Decimal("1000"),
        clean_price_percent=Decimal("98.5"),
        accrued_interest_per_bond=Decimal("12.34"),
        lots=2,
        fees=Decimal("3"),
    )
    assert purchase.clean_total == Decimal("1970")
    assert purchase.accrued_interest_total == Decimal("24.68")
    assert purchase.dirty_total == Decimal("1994.68")
    assert purchase.cash_required == Decimal("1997.68")


def test_synthetic_purchase_example_from_spec() -> None:
    purchase = calculate_bond_purchase(
        nominal=Decimal("1000"),
        clean_price_percent=Decimal("98"),
        accrued_interest_per_bond=Decimal("12.50"),
        lots=1,
        lot_size=1,
        fees=Decimal("0"),
    )
    assert purchase.quantity == 1
    assert purchase.clean_total == Decimal("980")
    assert purchase.accrued_interest_total == Decimal("12.50")
    assert purchase.dirty_total == Decimal("992.50")
    assert purchase.cash_required == Decimal("992.50")


def test_faceunit_overrides_currencyid_sur() -> None:
    from app.modules.investment.application.services import resolve_bond_face_currency

    assert resolve_bond_face_currency(face_unit="CNY", currency_id="SUR") == "CNY"
    assert resolve_bond_face_currency(face_unit="RUB", currency_id="SUR") == "RUB"
    status, reasons = classify_vanilla_rub_fixed_rate(
        currency="RUB",
        coupon_type="FIXED",
        has_offer=False,
        nominal=1000,
        maturity_date=date(2030, 1, 1),
        face_unit="USD",
        currency_id="SUR",
    )
    assert status is BondSupportStatus.UNSUPPORTED
    assert "currency_not_rub" in reasons


def test_cashflow_taxonomy_and_offer_is_research_only() -> None:
    assert {value.value for value in BondCashflowType} == {
        "COUPON",
        "AMORTIZATION",
        "REDEMPTION",
        "OFFER",
    }
    status, reasons = classify_vanilla_rub_fixed_rate(
        currency="RUB",
        coupon_type="FIXED",
        has_offer=True,
        nominal=1000,
        maturity_date=date(2030, 1, 1),
    )
    assert status is BondSupportStatus.RESEARCH_ONLY
    assert "offer_requires_policy" in reasons


def test_unknown_corporate_credit_is_not_safe() -> None:
    assert not real_portfolio_eligible(BondType.CORPORATE, CreditQualityStatus.UNKNOWN)


def test_slippage_only_worsens_trades() -> None:
    profile = TransactionCostProfile(Decimal("5"), slippage_bps=Decimal("10"))
    assert profile.execution_price(Decimal("100"), "BUY") == Decimal("100.100")
    assert profile.execution_price(Decimal("100"), "SELL") == Decimal("99.900")
    assert profile.execution_price(Decimal("100"), "COUPON") == Decimal("100")
    assert profile.execution_price(Decimal("100"), "REDEMPTION") == Decimal("100")


def test_100k_integer_lots_fees_and_non_negative_cash() -> None:
    result = allocate_integer_lots(
        [
            AllocationCandidate(
                "AAA", AssetSleeve.EQUITY_ALPHA, Decimal("123.45"), 10, Decimal("0.6")
            ),
            AllocationCandidate(
                "BOND", AssetSleeve.FIXED_INCOME, Decimal("980"), 1, Decimal("0.4")
            ),
        ],
        capital=Decimal("100000"),
        costs=TransactionCostProfile(Decimal("10")),
    )
    assert all(position.units % (10 if position.symbol == "AAA" else 1) == 0 for position in result.positions)
    assert result.fees > 0
    assert result.cash_remainder >= 0
    assert sum((p.cash_used for p in result.positions), Decimal()) + result.cash_remainder == Decimal(
        "100000"
    )


def test_key_rate_audit_without_database(tmp_path) -> None:
    report = key_rate_audit(
        [{"as_of": "2026-09-01", "annual_rate": 0.18}],
        output=tmp_path / "audit.json",
    )
    assert report["rows"] == 1
    assert report["benchmark_type"] == "CBR_KEY_RATE"


class _Result:
    def __init__(self, row: object) -> None:
        self.row = row

    def first(self) -> object:
        return self.row


class _Session:
    def __init__(self, row: object) -> None:
        self.row = row

    def execute(self, statement: object) -> _Result:
        return _Result(self.row)


def test_cbr_provider_same_day_date_only_pit() -> None:
    value = type(
        "Value",
        (),
        {"timestamp": datetime(2026, 9, 5, tzinfo=UTC), "value": Decimal("18")},
    )()
    series = type("Series", (), {"source": "CBR"})()
    quote = CbrHurdleProvider(_Session((value, series))).quote(date(2026, 9, 5))  # type: ignore[arg-type]
    assert quote is not None
    assert quote.as_of == date(2026, 9, 5)
    assert quote.known_at == date(2026, 9, 5)
    assert quote.known_at_quality is KnownAtQuality.DATE_ONLY
    assert quote.annual_rate == pytest.approx(0.18)
