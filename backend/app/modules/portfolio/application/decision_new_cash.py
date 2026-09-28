"""Decision V2 — read-only hypothetical new-capital scenario planning.

Does not write journal, cash, contributed capital, or operations.
Does not route Dataset V3 into USER decisions.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.modules.investment.application.equity_lot_size import resolve_equity_lot_sizes
from app.modules.portfolio.application.personal_portfolio_service import PersonalPortfolioSnapshot
from app.modules.portfolio.domain.personal_ledger import ZERO, money

WEIGHT_EPS = Decimal("0.02")


def _d(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _f(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def build_new_cash_scenarios(
    session: Session,
    *,
    snap: PersonalPortfolioSnapshot,
    new_cash_rub: Decimal,
    compare: dict[str, Any] | None,
    research: dict[str, Any] | None,
    allow_precise: bool,
    degradations: list[str],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any], list[str]]:
    """Return (new_cash_plan, scenario_comparison, data_confidence, extra_limitations)."""
    limitations: list[str] = []
    new_cash = money(new_cash_rub)
    if new_cash < ZERO:
        raise ValueError("new_cash_rub must be >= 0")

    nav = money(snap.known_nav_rub) if snap.known_nav_rub is not None else ZERO
    cash = money(snap.cash_rub)
    hyp_nav = money(nav + new_cash)

    confidence_reasons: list[str] = []
    if not snap.valuation_complete or snap.valuation_partial:
        confidence_reasons.append("valuation_incomplete")
    if not allow_precise:
        confidence_reasons.append("precise_compare_unavailable")
    if compare is None:
        confidence_reasons.append("candidate_unavailable")
    if research is None:
        confidence_reasons.append("research_decision_unavailable")
    if snap.missing_price_count:
        confidence_reasons.append("missing_prices")

    status = "SUFFICIENT"
    if confidence_reasons:
        status = "LOW" if (
            "valuation_incomplete" in confidence_reasons
            or "candidate_unavailable" in confidence_reasons
            and new_cash > ZERO
        ) else "PARTIAL"

    data_confidence = {
        "status": status if new_cash > ZERO else ("SUFFICIENT" if not confidence_reasons else "PARTIAL"),
        "reasons": confidence_reasons,
        "note": "Qualitative confidence from data completeness — not a probability.",
    }

    if new_cash <= ZERO:
        return None, [], data_confidence, limitations

    # --- Scenario A: DO_NOTHING ---
    scenarios: list[dict[str, Any]] = [
        {
            "id": "DO_NOTHING",
            "title": "Не распределять",
            "status": "available",
            "deployed_rub": "0",
            "residual_cash_rub": str(new_cash),
            "cash_share": _f(money(cash) / hyp_nav) if hyp_nav > ZERO else None,
            "equity_share": None,
            "fixed_income_share": None,
            "purchases": [],
            "facts": [
                f"Новый капитал {new_cash} ₽ остаётся вне портфеля.",
                f"Текущий NAV {nav} ₽ без изменений.",
            ],
            "limitations": [],
        }
    ]

    # --- Scenario B: HOLD_CASH ---
    cash_after = money(cash + new_cash)
    scenarios.append(
        {
            "id": "HOLD_CASH",
            "title": "Оставить кэшем",
            "status": "available",
            "deployed_rub": "0",
            "residual_cash_rub": str(new_cash),
            "portfolio_cash_after_rub": str(cash_after),
            "cash_share": _f(cash_after / hyp_nav) if hyp_nav > ZERO else None,
            "purchases": [],
            "facts": [
                f"Гипотетически кэш портфеля: {cash} → {cash_after} ₽.",
                "Ценные бумаги не покупаются.",
            ],
            "limitations": ["Гипотетический сценарий — журнал не меняется."],
            "cbr_context": _cbr_context(research),
        }
    )

    underweight = _target_underweight_plan(
        session,
        snap=snap,
        new_cash=new_cash,
        hyp_nav=hyp_nav,
        compare=compare,
        allow_precise=allow_precise,
    )
    scenarios.append(underweight)

    kraken = _kraken_allocation_plan(
        session,
        snap=snap,
        new_cash=new_cash,
        hyp_nav=hyp_nav,
        research=research,
        allow_precise=allow_precise,
    )
    scenarios.append(kraken)

    fi = _fixed_income_alternative(research=research, new_cash=new_cash)
    if fi is not None:
        scenarios.append(fi)

    if snap.journal_state == "DRAFT":
        limitations.append("Предварительный план — состав портфеля ещё не зафиксирован.")
    limitations.append("READ_ONLY_HYPOTHETICAL — без записи в журнал и без изменения кэша.")
    limitations.extend(degradations[:5])

    plan = {
        "requested_new_cash_rub": str(new_cash),
        "current_nav_rub": str(nav),
        "current_cash_rub": str(cash),
        "hypothetical_total_capital_rub": str(hyp_nav),
        "selected_scenario_hint": _hint_scenario(scenarios),
        "note": "Сценарии сравнимы фактически; ожидаемая доходность не выдумывается.",
    }
    return plan, scenarios, data_confidence, limitations


def _cbr_context(research: dict[str, Any] | None) -> dict[str, Any] | None:
    if not research:
        return None
    decision = research.get("decision") or {}
    annual = decision.get("cbr_hurdle_annual") or research.get("cbr_hurdle_annual")
    if annual is None:
        return None
    return {
        "cbr_hurdle_annual": annual,
        "wording": (
            "Безрисковый/денежный ориентир на основе существующего CBR hurdle контекста. "
            "Это не гарантия доходности депозита и не ставка, которую кэш зарабатывает автоматически."
        ),
    }


def _hint_scenario(scenarios: list[dict[str, Any]]) -> str | None:
    for sid in ("TARGET_UNDERWEIGHTS", "KRAKEN_ALLOCATION", "HOLD_CASH"):
        row = next((s for s in scenarios if s["id"] == sid and s.get("status") == "available"), None)
        if row is not None:
            return sid
    return "DO_NOTHING"


def _lot_suggestion(
    session: Session,
    *,
    symbol: str,
    instrument_id: int,
    asset_class: str | None,
    unit_price: Decimal | None,
    target_rub: Decimal,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "symbol": symbol,
        "instrument_id": instrument_id,
        "target_rub": str(money(target_rub)),
        "lots": None,
        "units": None,
        "estimated_notional": None,
        "residual_cash_rub": str(money(target_rub)),
        "lot_size": None,
    }
    if (asset_class or "").lower() == "bond":
        row["limitations"] = ["ADVISORY_ONLY_BOND_TRADE"]
        row["status"] = "advisory_sleeve"
        return row
    if unit_price is None or unit_price <= ZERO:
        row["limitations"] = ["PRICE_MISSING"]
        return row

    from app.infrastructure.market.models import Instrument

    inst = session.get(Instrument, instrument_id)
    lot_size = None
    if inst is not None:
        resolved = resolve_equity_lot_sizes(session, [inst], fetch_missing=False)
        res = resolved.get(int(instrument_id))
        lot_size = res.lot_size if res else None
    row["lot_size"] = lot_size
    if lot_size is None or lot_size <= 0:
        row["limitations"] = ["LOT_SIZE_UNKNOWN"]
        return row

    lot_notional = money(unit_price * Decimal(lot_size))
    if lot_notional <= ZERO:
        row["limitations"] = ["PRICE_MISSING"]
        return row
    lots = int(money(target_rub) // lot_notional)
    units = Decimal(lots * lot_size)
    notional = money(units * unit_price)
    residual = money(target_rub - notional)
    row.update(
        {
            "lots": lots if lots > 0 else 0,
            "units": float(units),
            "estimated_notional": str(notional),
            "residual_cash_rub": str(residual),
            "unit_price": str(money(unit_price)),
        }
    )
    return row


def _target_underweight_plan(
    session: Session,
    *,
    snap: PersonalPortfolioSnapshot,
    new_cash: Decimal,
    hyp_nav: Decimal,
    compare: dict[str, Any] | None,
    allow_precise: bool,
) -> dict[str, Any]:
    if not allow_precise or compare is None:
        return {
            "id": "TARGET_UNDERWEIGHTS",
            "title": "Направить в недовесы",
            "status": "unavailable",
            "reason": "Нет надёжного сравнения с кандидатом или оценка неполная.",
            "purchases": [],
            "limitations": ["CANDIDATE_OR_VALUATION_UNAVAILABLE"],
        }

    comparisons = list(compare.get("comparisons") or [])
    underweights: list[tuple[str, Decimal, dict[str, Any]]] = []
    for row in comparisons:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        mw = row.get("manual_weight")
        cw = row.get("candidate_weight")
        if cw is None:
            continue
        manual = _d(mw) if mw is not None else ZERO
        cand = _d(cw)
        gap = cand - manual
        if gap >= WEIGHT_EPS:
            underweights.append((symbol, gap, row))

    # Do not add to overweights: only positive gaps.
    if not underweights:
        return {
            "id": "TARGET_UNDERWEIGHTS",
            "title": "Направить в недовесы",
            "status": "available",
            "deployed_rub": "0",
            "residual_cash_rub": str(new_cash),
            "purchases": [],
            "facts": ["Существенных недовесов относительно кандидата нет."],
            "limitations": [],
        }

    gap_sum = sum((g for _, g, _ in underweights), ZERO)
    purchases: list[dict[str, Any]] = []
    deployed = ZERO
    remaining = new_cash
    pos_by_sym = {p.symbol.upper(): p for p in snap.positions if p.symbol}

    for symbol, gap, crow in sorted(underweights, key=lambda x: -x[1]):
        if remaining <= ZERO or gap_sum <= ZERO:
            break
        share = gap / gap_sum
        target_rub = money(new_cash * share)
        if target_rub <= ZERO:
            continue
        pos = pos_by_sym.get(symbol)
        instrument_id = int(crow.get("instrument_id") or (pos.instrument_id if pos else 0) or 0)
        if instrument_id <= 0:
            purchases.append(
                {
                    "symbol": symbol,
                    "target_rub": str(target_rub),
                    "lots": None,
                    "limitations": ["INSTRUMENT_UNRESOLVED"],
                }
            )
            continue
        asset = (pos.asset_class if pos else crow.get("asset_class")) or "equity"
        price = pos.unit_price if pos else None
        sug = _lot_suggestion(
            session,
            symbol=symbol,
            instrument_id=instrument_id,
            asset_class=str(asset),
            unit_price=price,
            target_rub=min(target_rub, remaining),
        )
        if (asset or "").lower() == "bond":
            sug["limitations"] = list(sug.get("limitations") or []) + ["ADVISORY_ONLY_BOND_TRADE"]
        purchases.append(sug)
        used = money(sug.get("estimated_notional") or ZERO)
        deployed = money(deployed + used)
        remaining = money(remaining - used)

    return {
        "id": "TARGET_UNDERWEIGHTS",
        "title": "Направить в недовесы",
        "status": "available",
        "deployed_rub": str(deployed),
        "residual_cash_rub": str(remaining),
        "cash_share": _f(money(snap.cash_rub + remaining) / hyp_nav) if hyp_nav > ZERO else None,
        "purchases": purchases,
        "facts": [
            f"Недовесов: {len(underweights)}.",
            f"Оценочно к размещению: {deployed} ₽; остаток нового капитала: {remaining} ₽.",
            "Новый капитал не создаёт принудительную продажу существующих позиций.",
        ],
        "limitations": ["Нет принудительных продаж из сценария нового капитала."],
    }


def _kraken_allocation_plan(
    session: Session,
    *,
    snap: PersonalPortfolioSnapshot,
    new_cash: Decimal,
    hyp_nav: Decimal,
    research: dict[str, Any] | None,
    allow_precise: bool,
) -> dict[str, Any]:
    if not allow_precise or research is None:
        return {
            "id": "KRAKEN_ALLOCATION",
            "title": "Текущий план Kraken",
            "status": "unavailable",
            "reason": "Research decision недоступен или данные неполны.",
            "purchases": [],
            "limitations": ["RESEARCH_DECISION_UNAVAILABLE"],
        }

    decision = research.get("decision") or {}
    sleeves = decision.get("sleeve_weights") or decision.get("sleeves") or {}
    equity_w = decision.get("equity_weight")
    cash_w = decision.get("cash_weight")
    fi_w = decision.get("fixed_income_weight") or decision.get("fi_weight")

    if equity_w is None and not sleeves:
        return {
            "id": "KRAKEN_ALLOCATION",
            "title": "Текущий план Kraken",
            "status": "degraded",
            "reason": "Нет весов рукавов в research decision.",
            "purchases": [],
            "limitations": ["SLEEVE_WEIGHTS_MISSING"],
            "cbr_context": _cbr_context(research),
        }

    eq = _d(equity_w) if equity_w is not None else ZERO
    cash_target = _d(cash_w) if cash_w is not None else ZERO
    fi = _d(fi_w) if fi_w is not None else ZERO
    deploy_eq = money(new_cash * eq)
    deploy_fi = money(new_cash * fi)
    keep_cash = money(new_cash * cash_target)
    if deploy_eq + deploy_fi + keep_cash < new_cash:
        keep_cash = money(new_cash - deploy_eq - deploy_fi)

    purchases: list[dict[str, Any]] = []
    if deploy_fi > ZERO:
        purchases.append(
            {
                "symbol": None,
                "sleeve": "fixed_income",
                "target_rub": str(deploy_fi),
                "lots": None,
                "units": None,
                "limitations": ["ADVISORY_ONLY_BOND_TRADE", "NO_FAKE_OFZ_TICKER"],
                "note": "fixed-income sleeve — конкретный тикер OFZ не выдумывается.",
            }
        )

    # Prefer existing underweight equities in portfolio for the equity sleeve portion.
    eq_left = deploy_eq
    for pos in snap.positions:
        if eq_left <= ZERO:
            break
        if (pos.asset_class or "").lower() != "equity":
            continue
        # Skip obvious concentration adds: if position already > 25% of hyp nav, skip.
        if pos.market_value is not None and hyp_nav > ZERO:
            w = money(pos.market_value) / hyp_nav
            if w >= Decimal("0.25"):
                continue
        equity_n = len(
            [p for p in snap.positions if (p.asset_class or "").lower() == "equity"]
        )
        denom = max(Decimal(equity_n), Decimal("1"))
        chunk = money(min(eq_left, deploy_eq / denom))
        if chunk <= ZERO or not pos.symbol:
            continue
        sug = _lot_suggestion(
            session,
            symbol=pos.symbol.upper(),
            instrument_id=int(pos.instrument_id),
            asset_class=pos.asset_class,
            unit_price=pos.unit_price,
            target_rub=chunk,
        )
        purchases.append(sug)
        used = money(sug.get("estimated_notional") or ZERO)
        eq_left = money(eq_left - used)

    deployed = money(deploy_eq + deploy_fi - eq_left)
    residual = money(new_cash - deployed)

    return {
        "id": "KRAKEN_ALLOCATION",
        "title": "Текущий план Kraken",
        "status": "available",
        "deployed_rub": str(deployed),
        "residual_cash_rub": str(residual),
        "sleeve_targets": {
            "equity_weight": _f(eq),
            "cash_weight": _f(cash_target),
            "fixed_income_weight": _f(fi),
        },
        "purchases": purchases,
        "facts": [
            f"Доля equity/cash/FI в research: {_f(eq)} / {_f(cash_target)} / {_f(fi)}.",
            f"Оценочно размещено: {deployed} ₽; остаток: {residual} ₽.",
        ],
        "limitations": ["Гипотетический план; не приказ брокеру."],
        "cbr_context": _cbr_context(research),
    }


def _fixed_income_alternative(
    *,
    research: dict[str, Any] | None,
    new_cash: Decimal,
) -> dict[str, Any] | None:
    if research is None:
        return None
    decision = research.get("decision") or {}
    fi_w = decision.get("fixed_income_weight") or decision.get("fi_weight")
    if fi_w is None and not decision.get("fixed_income"):
        # Still show honest FI alternative as sleeve-level if CBR context exists.
        if decision.get("cbr_hurdle_annual") is None and research.get("cbr_hurdle_annual") is None:
            return None
    return {
        "id": "FIXED_INCOME_ALTERNATIVE",
        "title": "Альтернатива: fixed-income sleeve",
        "status": "available",
        "deployed_rub": str(new_cash),
        "residual_cash_rub": "0",
        "purchases": [
            {
                "sleeve": "fixed_income",
                "target_rub": str(new_cash),
                "symbol": None,
                "lots": None,
                "limitations": ["ADVISORY_ONLY_BOND_TRADE", "NO_FAKE_OFZ_TICKER"],
                "note": "Конкретный OFZ тикер не выдумывается без данных кандидата.",
            }
        ],
        "facts": [
            "Направить новый капитал в fixed-income sleeve (если pipeline поддерживает).",
            "Полный ACTIVE bond BUY/SELL учёт ещё заблокирован.",
        ],
        "limitations": ["ADVISORY_ONLY_BOND_TRADE"],
        "cbr_context": _cbr_context(research),
    }
