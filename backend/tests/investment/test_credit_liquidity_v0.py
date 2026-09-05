"""Credit quality & liquidity foundation V0 tests."""

from __future__ import annotations

from datetime import date

from app.modules.investment.domain.credit_quality import (
    CreditStatus,
    assess_credit_from_observed,
)
from app.modules.investment.domain.investment_eligibility import (
    EligibilityStatus,
    assess_investment_eligibility,
)
from app.modules.investment.domain.liquidity import (
    LiquidityStatus,
    assess_liquidity,
)


def test_credit_no_rating_unknown() -> None:
    cal = assess_credit_from_observed(
        instrument_id=1,
        issuer_id=None,
        bond_type="Corporate",
        stored_credit_status="UNKNOWN",
        raw_fields={},
        as_of=date(2026, 9, 5),
    )
    assert cal.credit_status is CreditStatus.UNKNOWN
    assert "CREDIT_UNKNOWN" in cal.risk_flags
    assert "CORPORATE_WITHOUT_RATING" in cal.risk_flags


def test_credit_rating_available() -> None:
    cal = assess_credit_from_observed(
        instrument_id=2,
        issuer_id=10,
        bond_type="Corporate",
        stored_credit_status="UNKNOWN",
        raw_fields={"RATING": "A-", "RATINGAGENCY": "ACRA", "RATINGDATE": "2026-01-15"},
        as_of=date(2026, 9, 5),
    )
    assert cal.credit_status is CreditStatus.AVAILABLE
    assert cal.rating_value == "A-"
    assert cal.agency == "ACRA"


def test_credit_stale_rating() -> None:
    cal = assess_credit_from_observed(
        instrument_id=3,
        issuer_id=10,
        bond_type="Corporate",
        stored_credit_status="UNKNOWN",
        raw_fields={"RATING": "BBB", "RATINGAGENCY": "Expert RA", "RATINGDATE": "2020-01-01"},
        as_of=date(2026, 9, 5),
        stale_after_days=365,
    )
    assert cal.credit_status is CreditStatus.STALE
    assert "DATA_STALE" in cal.risk_flags


def test_credit_not_rated() -> None:
    cal = assess_credit_from_observed(
        instrument_id=4,
        issuer_id=None,
        bond_type="Corporate",
        stored_credit_status="NOT_RATED",
        raw_fields={},
        as_of=date(2026, 9, 5),
    )
    assert cal.credit_status is CreditStatus.NOT_RATED


def test_liquidity_recent_trade_good() -> None:
    liq = assess_liquidity(
        instrument_id=1,
        as_of=date(2026, 9, 5),
        last_trade_date=date(2026, 9, 5),
        volume=1000,
        trade_count=12,
    )
    assert liq.liquidity_status is LiquidityStatus.GOOD


def test_liquidity_stale_price_low() -> None:
    liq = assess_liquidity(
        instrument_id=1,
        as_of=date(2026, 9, 5),
        last_trade_date=date(2026, 8, 1),
        volume=10,
    )
    assert liq.liquidity_status is LiquidityStatus.LOW
    assert "STALE_PRICE" in liq.reasons


def test_liquidity_no_volume_unknown_or_downgraded() -> None:
    liq = assess_liquidity(
        instrument_id=1,
        as_of=date(2026, 9, 5),
        last_trade_date=date(2026, 9, 5),
        volume=0,
    )
    assert liq.liquidity_status in {LiquidityStatus.MEDIUM, LiquidityStatus.LOW}
    assert "LOW_VOLUME" in liq.reasons


def test_liquidity_unknown() -> None:
    liq = assess_liquidity(
        instrument_id=1,
        as_of=date(2026, 9, 5),
        last_trade_date=None,
    )
    assert liq.liquidity_status is LiquidityStatus.UNKNOWN


def test_eligibility_accounting_ok_credit_unknown() -> None:
    credit = assess_credit_from_observed(
        instrument_id=1,
        issuer_id=None,
        bond_type="Corporate",
        stored_credit_status="UNKNOWN",
        raw_fields={},
        as_of=date(2026, 9, 5),
    )
    liq = assess_liquidity(
        instrument_id=1,
        as_of=date(2026, 9, 5),
        last_trade_date=date(2026, 9, 4),
        volume=100,
    )
    el = assess_investment_eligibility(
        instrument_id=1,
        support_status="SUPPORTED",
        credit=credit,
        liquidity=liq,
        bond_type="Corporate",
    )
    assert el.accounting_supported is True
    assert el.eligible is False
    assert el.status is EligibilityStatus.RESEARCH_ONLY


def test_eligibility_credit_good_liquidity_bad() -> None:
    credit = assess_credit_from_observed(
        instrument_id=1,
        issuer_id=1,
        bond_type="Corporate",
        stored_credit_status="UNKNOWN",
        raw_fields={"RATING": "AA", "RATINGAGENCY": "ACRA", "RATINGDATE": "2026-06-01"},
        as_of=date(2026, 9, 5),
    )
    liq = assess_liquidity(
        instrument_id=1,
        as_of=date(2026, 9, 5),
        last_trade_date=date(2026, 1, 1),
        volume=0,
    )
    el = assess_investment_eligibility(
        instrument_id=1,
        support_status="SUPPORTED",
        credit=credit,
        liquidity=liq,
        bond_type="Corporate",
    )
    assert credit.credit_status is CreditStatus.AVAILABLE
    assert liq.liquidity_status is LiquidityStatus.LOW
    assert el.status is EligibilityStatus.RESEARCH_ONLY
    assert el.eligible is False


def test_eligibility_all_checks_pass() -> None:
    credit = assess_credit_from_observed(
        instrument_id=1,
        issuer_id=1,
        bond_type="Government",
        stored_credit_status="UNKNOWN",
        raw_fields={"RATING": "AAA", "RATINGAGENCY": "ACRA", "RATINGDATE": "2026-08-01"},
        as_of=date(2026, 9, 5),
    )
    liq = assess_liquidity(
        instrument_id=1,
        as_of=date(2026, 9, 5),
        last_trade_date=date(2026, 9, 5),
        volume=5000,
        trade_count=40,
    )
    el = assess_investment_eligibility(
        instrument_id=1,
        support_status="SUPPORTED",
        credit=credit,
        liquidity=liq,
        bond_type="Government",
    )
    assert el.status is EligibilityStatus.REAL_PORTFOLIO_CANDIDATE
    assert el.eligible is True
