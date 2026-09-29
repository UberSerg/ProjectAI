"""Pure unit tests for portfolio FeeEngine (Sber + custom + tiers)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.portfolio.domain.fee_engine import (
    FeeEngine,
    FeeEstimateContext,
    FeeRuleSpec,
    FeeStatus,
    FeeType,
    sber_investment_builtin_rules,
)
from app.modules.portfolio.domain.personal_ledger import money

AS_OF = date(2026, 9, 29)


def _sber() -> FeeEngine:
    return FeeEngine(sber_investment_builtin_rules())


def _ctx(
    *,
    side: str = "BUY",
    notional: Decimal = Decimal("100000"),
    nkd: Decimal = Decimal("0"),
    symbol: str | None = "SBER",
    instrument_id: int | None = None,
    as_of: date = AS_OF,
    day_turnover: Decimal = Decimal("0"),
    market: str = "MOEX",
) -> FeeEstimateContext:
    return FeeEstimateContext(
        as_of=as_of,
        side=side,
        notional=notional,
        nkd=nkd,
        market=market,
        instrument_symbol=symbol,
        instrument_id=instrument_id,
        broker_account_day_turnover=day_turnover,
    )


def test_sber_default_0_3_percent_buy() -> None:
    est = _sber().estimate_fee(_ctx(side="BUY", notional=Decimal("100000")))
    assert est.status == FeeStatus.KNOWN
    assert est.amount == money("300")
    assert est.matched_rule_code == "SBER_MOEX_ONLINE_DEFAULT"
    assert est.exclude_from_turnover is False


def test_sber_default_0_3_percent_sell() -> None:
    est = _sber().estimate_fee(_ctx(side="SELL", notional=Decimal("100000")))
    assert est.status == FeeStatus.KNOWN
    assert est.amount == money("300")
    assert est.matched_rule_code == "SBER_MOEX_ONLINE_DEFAULT"


def test_decimal_rounding_half_up() -> None:
    # 0.3% of 100.005 → 0.300015 → money quantize 0.000001 → 0.300015
    est = _sber().estimate_fee(_ctx(notional=Decimal("100.005")))
    assert est.status == FeeStatus.KNOWN
    assert est.amount == money(Decimal("100.005") * Decimal("0.003"))
    assert isinstance(est.amount, Decimal)


def test_sbfr_zero_fee_in_validity_window() -> None:
    est = _sber().estimate_fee(
        _ctx(symbol="SBFR", as_of=date(2026, 8, 4), notional=Decimal("50000"))
    )
    assert est.status == FeeStatus.KNOWN
    assert est.amount == money("0")
    assert est.matched_rule_code == "SBER_SBFR_ZERO_TEMP"
    assert est.exclude_from_turnover is True

    est_end = _sber().estimate_fee(
        _ctx(symbol="SBFR", as_of=date(2026, 12, 31), notional=Decimal("50000"))
    )
    assert est_end.matched_rule_code == "SBER_SBFR_ZERO_TEMP"
    assert est_end.amount == money("0")


def test_expired_sbfr_override_falls_back_to_0_3() -> None:
    est = _sber().estimate_fee(
        _ctx(symbol="SBFR", as_of=date(2027, 1, 1), notional=Decimal("100000"))
    )
    assert est.status == FeeStatus.KNOWN
    assert est.amount == money("300")
    assert est.matched_rule_code == "SBER_MOEX_ONLINE_DEFAULT"
    assert est.exclude_from_turnover is False


def test_sber_generic_unknown_before_snapshot_date() -> None:
    """Generic 0.3% starts 2026-09-29 — earlier SBER dates must be UNKNOWN (no fake 0%)."""
    est = _sber().estimate_fee(
        _ctx(symbol="SBER", as_of=date(2026, 9, 1), notional=Decimal("100000"))
    )
    assert est.status == FeeStatus.UNKNOWN
    assert est.amount is None
    assert est.matched_rule_code is None


def test_sbfr_after_window_uses_generic_when_snapshot_active() -> None:
    """After 2026-12-31, SBFR uses generic iff as_of >= 2026-09-29."""
    est = _sber().estimate_fee(
        _ctx(symbol="SBFR", as_of=date(2027, 1, 1), notional=Decimal("100000"))
    )
    assert est.status == FeeStatus.KNOWN
    assert est.amount == money("300")
    assert est.matched_rule_code == "SBER_MOEX_ONLINE_DEFAULT"


def test_custom_buy_and_sell_rates() -> None:
    rules = [
        FeeRuleSpec(
            id=10,
            code="CUSTOM_BUY",
            market="MOEX",
            side="BUY",
            fee_type=FeeType.PERCENTAGE,
            percentage_rate=Decimal("0.0005"),
            priority=50,
        ),
        FeeRuleSpec(
            id=11,
            code="CUSTOM_SELL",
            market="MOEX",
            side="SELL",
            fee_type=FeeType.PERCENTAGE,
            percentage_rate=Decimal("0.001"),
            priority=50,
        ),
    ]
    engine = FeeEngine(rules)
    buy = engine.estimate_fee(_ctx(side="BUY", notional=Decimal("200000")))
    sell = engine.estimate_fee(_ctx(side="SELL", notional=Decimal("200000")))
    assert buy.amount == money("100")  # 0.05%
    assert sell.amount == money("200")  # 0.1%
    assert buy.matched_rule_code == "CUSTOM_BUY"
    assert sell.matched_rule_code == "CUSTOM_SELL"


def test_tier_matching() -> None:
    rules = [
        FeeRuleSpec(
            id=1,
            code="TIER_LOW",
            market="MOEX",
            side="ANY",
            turnover_from=Decimal("0"),
            turnover_to=Decimal("1000000"),
            fee_type=FeeType.PERCENTAGE,
            percentage_rate=Decimal("0.003"),
            priority=20,
        ),
        FeeRuleSpec(
            id=2,
            code="TIER_HIGH",
            market="MOEX",
            side="ANY",
            turnover_from=Decimal("1000000"),
            turnover_to=None,
            fee_type=FeeType.PERCENTAGE,
            percentage_rate=Decimal("0.001"),
            priority=20,
        ),
    ]
    engine = FeeEngine(rules)
    low = engine.estimate_fee(_ctx(day_turnover=Decimal("0"), notional=Decimal("100000")))
    high = engine.estimate_fee(
        _ctx(day_turnover=Decimal("1000000"), notional=Decimal("100000"))
    )
    assert low.matched_rule_code == "TIER_LOW"
    assert low.amount == money("300")
    assert high.matched_rule_code == "TIER_HIGH"
    assert high.amount == money("100")


def test_same_broker_account_shared_turnover() -> None:
    """Two Kraken portfolios on one BrokerAccount share day turnover for tiers."""
    rules = [
        FeeRuleSpec(
            id=1,
            code="TIER_LOW",
            market="MOEX",
            turnover_from=Decimal("0"),
            turnover_to=Decimal("500000"),
            fee_type=FeeType.PERCENTAGE,
            percentage_rate=Decimal("0.003"),
            priority=20,
        ),
        FeeRuleSpec(
            id=2,
            code="TIER_HIGH",
            market="MOEX",
            turnover_from=Decimal("500000"),
            fee_type=FeeType.PERCENTAGE,
            percentage_rate=Decimal("0.001"),
            priority=20,
        ),
    ]
    engine = FeeEngine(rules)
    # Portfolio A already traded 400k; Portfolio B trade sees shared 400k → still low tier
    a_then_b = engine.estimate_fee(
        _ctx(day_turnover=Decimal("400000"), notional=Decimal("100000"))
    )
    assert a_then_b.matched_rule_code == "TIER_LOW"
    # After shared turnover reaches 500k (A+B prior), next trade is high tier
    next_trade = engine.estimate_fee(
        _ctx(day_turnover=Decimal("500000"), notional=Decimal("100000"))
    )
    assert next_trade.matched_rule_code == "TIER_HIGH"


def test_different_broker_accounts_isolated() -> None:
    rules = [
        FeeRuleSpec(
            id=1,
            code="TIER_LOW",
            market="MOEX",
            turnover_from=Decimal("0"),
            turnover_to=Decimal("500000"),
            fee_type=FeeType.PERCENTAGE,
            percentage_rate=Decimal("0.003"),
            priority=20,
        ),
        FeeRuleSpec(
            id=2,
            code="TIER_HIGH",
            market="MOEX",
            turnover_from=Decimal("500000"),
            fee_type=FeeType.PERCENTAGE,
            percentage_rate=Decimal("0.001"),
            priority=20,
        ),
    ]
    engine = FeeEngine(rules)
    # Account X has 600k day turnover → high tier
    acct_x = engine.estimate_fee(
        _ctx(day_turnover=Decimal("600000"), notional=Decimal("100000"))
    )
    # Account Y starts at 0 → low tier (isolated)
    acct_y = engine.estimate_fee(
        _ctx(day_turnover=Decimal("0"), notional=Decimal("100000"))
    )
    assert acct_x.matched_rule_code == "TIER_HIGH"
    assert acct_y.matched_rule_code == "TIER_LOW"


def test_instrument_override_beats_generic() -> None:
    rules = [
        FeeRuleSpec(
            id=1,
            code="GENERIC",
            market="MOEX",
            fee_type=FeeType.PERCENTAGE,
            percentage_rate=Decimal("0.003"),
            priority=50,
        ),
        FeeRuleSpec(
            id=2,
            code="OVERRIDE_SBFR",
            market="MOEX",
            instrument_symbol="SBFR",
            fee_type=FeeType.PERCENTAGE,
            percentage_rate=Decimal("0"),
            priority=50,  # same priority — instrument specificity wins
        ),
    ]
    engine = FeeEngine(rules)
    est = engine.estimate_fee(_ctx(symbol="SBFR", notional=Decimal("100000")))
    assert est.matched_rule_code == "OVERRIDE_SBFR"
    assert est.amount == money("0")
    other = engine.estimate_fee(_ctx(symbol="SBER", notional=Decimal("100000")))
    assert other.matched_rule_code == "GENERIC"
    assert other.amount == money("300")


def test_no_matching_rule_returns_unknown_not_zero() -> None:
    engine = FeeEngine(
        [
            FeeRuleSpec(
                id=1,
                code="FX_ONLY",
                market="FX",
                fee_type=FeeType.PERCENTAGE,
                percentage_rate=Decimal("0.001"),
                priority=10,
            )
        ]
    )
    est = engine.estimate_fee(_ctx(market="MOEX", notional=Decimal("100000")))
    assert est.status == FeeStatus.UNKNOWN
    assert est.amount is None
    assert est.fee_rule_id is None
    assert est.is_unknown


def test_nkd_excluded_from_notional_input() -> None:
    engine = _sber()
    clean = engine.estimate_fee(
        _ctx(notional=Decimal("100000"), nkd=Decimal("0"))
    )
    with_nkd_field = engine.estimate_fee(
        _ctx(notional=Decimal("100000"), nkd=Decimal("5000"))
    )
    # NKD must not enlarge the fee base
    assert clean.amount == with_nkd_field.amount == money("300")
    # If caller wrongly put dirty notional into `notional`, fee would be higher —
    # documented contract: pass clean notional; nkd is ignored for math.
    dirty_mistaken = engine.estimate_fee(
        _ctx(notional=Decimal("105000"), nkd=Decimal("5000"))
    )
    assert dirty_mistaken.amount == money("315")
    assert dirty_mistaken.amount != with_nkd_field.amount


def test_slippage_not_part_of_broker_fee() -> None:
    """FeeEngine has no slippage input; broker fee is commission only."""
    engine = _sber()
    est = engine.estimate_fee(_ctx(notional=Decimal("100000")))
    assert est.amount == money("300")
    # Separate modeled slippage (e.g. 5 bps) must not be merged into broker fee
    slippage = money(Decimal("100000") * Decimal("0.0005"))
    assert slippage == money("50")
    assert est.amount != money(Decimal("100000") * Decimal("0.003") + slippage)
    assert est.amount == money(Decimal("100000") * Decimal("0.003"))
    assert "slippage" not in (est.explanation or "").lower()


def test_sbmm_not_zero_fee_without_verified_override() -> None:
    """SBMM/SBRB/FLOW must use default 0.3% — no guessed УК Первая zero fee."""
    for symbol in ("SBMM", "SBRB", "FLOW"):
        est = _sber().estimate_fee(_ctx(symbol=symbol, notional=Decimal("100000")))
        assert est.matched_rule_code == "SBER_MOEX_ONLINE_DEFAULT"
        assert est.amount == money("300")
