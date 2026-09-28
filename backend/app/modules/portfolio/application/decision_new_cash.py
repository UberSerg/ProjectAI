"""Decision V2 — read-only hypothetical new-capital scenario planning.

Does not write journal, cash, contributed capital, or operations.
Does not route Dataset V3 into USER decisions.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.modules.investment.application.equity_lot_size import resolve_equity_lot_sizes
from app.modules.portfolio.application.personal_portfolio_service import PersonalPortfolioSnapshot
from app.modules.portfolio.domain.personal_ledger import ZERO, money
from app.modules.portfolio.domain.valuation import latest_eod_close

WEIGHT_EPS = Decimal("0.02")
VALUE_EPS = Decimal("1")


def _d(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _f(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _candidate_stale(compare: dict[str, Any] | None) -> bool:
    if not compare:
        return False
    return bool(compare.get("candidate_stale"))


def _candidate_freshness_known(compare: dict[str, Any] | None) -> bool:
    if not compare:
        return False
    # Older fixtures may omit the field — treat missing as known only when not stale.
    if "candidate_freshness_known" not in compare:
        return not bool(compare.get("candidate_stale"))
    return bool(compare.get("candidate_freshness_known"))


def _precise_candidate_blocked(compare: dict[str, Any] | None) -> str | None:
    """Return limitation code if Candidate cannot drive precise lot plans."""
    if not compare:
        return "CANDIDATE_OR_VALUATION_UNAVAILABLE"
    if _candidate_stale(compare):
        return "CANDIDATE_STALE"
    if not _candidate_freshness_known(compare):
        return "CANDIDATE_FRESHNESS_UNKNOWN"
    return None


def _confidence(
    *,
    snap: PersonalPortfolioSnapshot,
    compare: dict[str, Any] | None,
    research: dict[str, Any] | None,
    allow_precise: bool,
    new_cash: Decimal,
) -> dict[str, Any]:
    reasons: list[str] = []
    if not snap.valuation_complete or snap.valuation_partial:
        reasons.append("valuation_incomplete")
    if not allow_precise:
        reasons.append("precise_compare_unavailable")
    if compare is None:
        reasons.append("candidate_unavailable")
    if _candidate_stale(compare):
        reasons.append("candidate_stale")
    if compare is not None and not _candidate_freshness_known(compare):
        reasons.append("candidate_freshness_unknown")
    if research is None:
        reasons.append("research_decision_unavailable")
    if snap.missing_price_count:
        reasons.append("missing_prices")

    if not reasons:
        status = "SUFFICIENT"
    elif new_cash > ZERO:
        incomplete = "valuation_incomplete" in reasons
        no_candidate = "candidate_unavailable" in reasons
        # Explicit: LOW when valuation is incomplete, or when candidate is missing
        # while new cash is being planned. Other gaps stay PARTIAL.
        status = "LOW" if (incomplete or no_candidate) else "PARTIAL"
    else:
        status = "PARTIAL"
    return {
        "status": status,
        "reasons": reasons,
        "note": "Qualitative confidence from data completeness — not a probability.",
    }


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
    data_confidence = _confidence(
        snap=snap,
        compare=compare,
        research=research,
        allow_precise=allow_precise,
        new_cash=new_cash,
    )

    if new_cash <= ZERO:
        return None, [], data_confidence, limitations

    instruments = _batch_instruments(session, snap=snap, compare=compare)

    scenarios: list[dict[str, Any]] = [
        _do_nothing_scenario(nav=nav, cash=cash, new_cash=new_cash),
        _hold_cash_scenario(nav=nav, cash=cash, new_cash=new_cash, hyp_nav=hyp_nav, research=research),
    ]

    stale = _candidate_stale(compare)
    freshness_block: str | None = None
    if compare is not None:
        if stale:
            freshness_block = "CANDIDATE_STALE"
        elif not _candidate_freshness_known(compare):
            freshness_block = "CANDIDATE_FRESHNESS_UNKNOWN"
    # Precise Candidate lots only when freshness is known AND not stale.
    precise_ok = allow_precise and freshness_block is None
    underweight = _target_underweight_plan(
        session,
        snap=snap,
        new_cash=new_cash,
        hyp_nav=hyp_nav,
        compare=compare,
        allow_precise=precise_ok,
        block_reason=freshness_block,
        instruments=instruments,
    )
    scenarios.append(underweight)

    kraken = _kraken_allocation_plan(
        session,
        snap=snap,
        new_cash=new_cash,
        hyp_nav=hyp_nav,
        compare=compare,
        research=research,
        allow_precise=precise_ok,
        block_reason=freshness_block,
        instruments=instruments,
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
        "selected_scenario_hint": _hint_scenario(scenarios, data_confidence),
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


def _hint_scenario(scenarios: list[dict[str, Any]], confidence: dict[str, Any]) -> str | None:
    """Hint only when status/confidence justify it; never manufacture certainty."""
    if confidence.get("status") == "LOW":
        hold = next((s for s in scenarios if s["id"] == "HOLD_CASH" and s.get("status") == "available"), None)
        return "HOLD_CASH" if hold is not None else "DO_NOTHING"
    for sid in ("TARGET_UNDERWEIGHTS", "KRAKEN_ALLOCATION"):
        row = next((s for s in scenarios if s["id"] == sid), None)
        if row is None or row.get("status") != "available":
            continue
        lims = row.get("limitations") or []
        if "CANDIDATE_STALE" in lims or "CANDIDATE_FRESHNESS_UNKNOWN" in lims:
            continue
        executable = money(row.get("executable_notional_rub") or ZERO)
        if executable > ZERO:
            return sid
    hold = next((s for s in scenarios if s["id"] == "HOLD_CASH" and s.get("status") == "available"), None)
    if hold is not None:
        return "HOLD_CASH"
    return "DO_NOTHING"


def _do_nothing_scenario(*, nav: Decimal, cash: Decimal, new_cash: Decimal) -> dict[str, Any]:
    cash_share = _f(money(cash) / nav) if nav > ZERO else None
    return {
        "id": "DO_NOTHING",
        "title": "Не распределять",
        "status": "available",
        "deployed_rub": "0",
        "target_allocation_rub": "0",
        "executable_notional_rub": "0",
        "advisory_only_rub": "0",
        "residual_cash_rub": "0",
        "external_unallocated_rub": str(new_cash),
        "portfolio_nav_after_rub": str(nav),
        "cash_share": cash_share,
        "equity_share": None,
        "fixed_income_share": None,
        "purchases": [],
        "facts": [
            f"Новый капитал {new_cash} ₽ остаётся вне портфеля.",
            f"NAV портфеля без изменений: {nav} ₽.",
            "Доля кэша считается от текущего NAV, не от NAV+новый капитал.",
        ],
        "limitations": [],
    }


def _hold_cash_scenario(
    *,
    nav: Decimal,
    cash: Decimal,
    new_cash: Decimal,
    hyp_nav: Decimal,
    research: dict[str, Any] | None,
) -> dict[str, Any]:
    cash_after = money(cash + new_cash)
    return {
        "id": "HOLD_CASH",
        "title": "Оставить кэшем",
        "status": "available",
        "deployed_rub": "0",
        "target_allocation_rub": "0",
        "executable_notional_rub": "0",
        "advisory_only_rub": "0",
        "residual_cash_rub": str(new_cash),
        "portfolio_cash_after_rub": str(cash_after),
        "portfolio_nav_after_rub": str(hyp_nav),
        "cash_share": _f(cash_after / hyp_nav) if hyp_nav > ZERO else None,
        "purchases": [],
        "facts": [
            f"Гипотетически кэш портфеля: {cash} → {cash_after} ₽.",
            f"NAV после: {hyp_nav} ₽.",
            "Ценные бумаги не покупаются.",
        ],
        "limitations": ["Гипотетический сценарий — журнал не меняется."],
        "cbr_context": _cbr_context(research),
    }


def _lot_suggestion(
    session: Session,
    *,
    symbol: str,
    instrument_id: int | None,
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
        "executable_estimated_notional_rub": None,
        "lot_rounding_residual_rub": str(money(target_rub)),
        "residual_cash_rub": str(money(target_rub)),
        "lot_size": None,
        "execution_status": "RUB_ONLY",
    }
    if instrument_id is None or instrument_id <= 0:
        row["limitations"] = ["INSTRUMENT_UNRESOLVED"]
        row["status"] = "unresolved"
        return row
    if (asset_class or "").lower() == "bond":
        row["limitations"] = ["ADVISORY_ONLY_BOND_TRADE"]
        row["status"] = "advisory_sleeve"
        row["execution_status"] = "ADVISORY_ONLY"
        row["executable_estimated_notional_rub"] = "0"
        row["residual_unexecuted_rub"] = str(money(target_rub))
        return row
    price = unit_price
    if price is None or price <= ZERO:
        close, _ts = latest_eod_close(session, int(instrument_id))
        price = close
    if price is None or price <= ZERO:
        row["limitations"] = ["PRICE_MISSING"]
        return row

    inst = session.get(Instrument, instrument_id)
    lot_size = None
    if inst is not None:
        resolved = resolve_equity_lot_sizes(session, [inst], fetch_missing=False)
        res = resolved.get(int(instrument_id))
        lot_size = res.lot_size if res else None
    if lot_size is None or lot_size <= 0:
        # Catalog metadata may live on MOEX_ISS (or other) sources; do not invent lot=1.
        from app.infrastructure.market.models import InstrumentSource

        sources = list(
            session.scalars(
                select(InstrumentSource).where(InstrumentSource.instrument_id == int(instrument_id))
            )
        )
        for src in sources:
            meta = dict(src.source_metadata or {})
            raw = meta.get("LOTSIZE")
            if raw is None:
                continue
            try:
                parsed = int(raw)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                lot_size = parsed
                break
    row["lot_size"] = lot_size
    row["unit_price"] = str(money(price))
    if lot_size is None or lot_size <= 0:
        row["limitations"] = ["LOT_SIZE_UNKNOWN"]
        return row

    lot_notional = money(price * Decimal(lot_size))
    if lot_notional <= ZERO:
        row["limitations"] = ["PRICE_MISSING"]
        return row
    lots = int(money(target_rub) // lot_notional)
    units = Decimal(lots * lot_size)
    notional = money(units * price)
    residual = money(target_rub - notional)
    row.update(
        {
            "lots": lots if lots > 0 else 0,
            "units": float(units),
            "estimated_notional": str(notional),
            "executable_estimated_notional_rub": str(notional),
            "lot_rounding_residual_rub": str(residual),
            "residual_cash_rub": str(residual),
            "execution_status": "LOT_ESTIMATE" if lots > 0 else "RUB_ONLY",
        }
    )
    return row


def _batch_instruments(
    session: Session,
    *,
    snap: PersonalPortfolioSnapshot,
    compare: dict[str, Any] | None,
) -> dict[str, Instrument]:
    """Unique MOEX Instrument by upper(symbol); skip ambiguous duplicates."""
    symbols: set[str] = {p.symbol.upper() for p in snap.positions if p.symbol}
    for row in (compare or {}).get("comparisons") or []:
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            symbols.add(symbol)
    if not symbols:
        return {}
    rows = list(
        session.scalars(select(Instrument).where(func.upper(Instrument.symbol).in_(sorted(symbols))))
    )
    grouped: dict[str, list[Instrument]] = {}
    for inst in rows:
        grouped.setdefault(inst.symbol.upper(), []).append(inst)
    unique: dict[str, Instrument] = {}
    for symbol, items in grouped.items():
        if len(items) == 1:
            unique[symbol] = items[0]
    return unique


def _shortfalls(
    *,
    snap: PersonalPortfolioSnapshot,
    compare: dict[str, Any] | None,
    hyp_nav: Decimal,
    instruments: dict[str, Instrument],
) -> list[dict[str, Any]]:
    if not compare:
        return []
    pos_by_sym = {p.symbol.upper(): p for p in snap.positions if p.symbol}
    out: list[dict[str, Any]] = []
    for row in compare.get("comparisons") or []:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        cw = row.get("candidate_weight")
        if cw is None:
            continue
        cand = _d(cw)
        if cand <= ZERO:
            continue
        pos = pos_by_sym.get(symbol)
        current_mv = ZERO
        if row.get("current_market_value") is not None:
            current_mv = money(_d(row["current_market_value"]))
        elif pos is not None and pos.market_value is not None:
            current_mv = money(pos.market_value)
        target_value = money(cand * hyp_nav)
        shortfall = money(target_value - current_mv)
        if shortfall <= VALUE_EPS:
            continue
        instrument_id = row.get("instrument_id")
        if instrument_id in (None, 0, "0"):
            if pos is not None:
                instrument_id = pos.instrument_id
            elif symbol in instruments:
                instrument_id = instruments[symbol].id
            else:
                instrument_id = None
        else:
            instrument_id = int(instrument_id)
        asset = row.get("asset_class")
        if not asset and pos is not None:
            asset = pos.asset_class
        if not asset and symbol in instruments:
            asset = instruments[symbol].asset_class
        price = pos.unit_price if pos is not None else None
        out.append(
            {
                "symbol": symbol,
                "candidate_weight": cand,
                "current_mv": current_mv,
                "target_value": target_value,
                "shortfall": shortfall,
                "instrument_id": instrument_id,
                "asset_class": asset or "equity",
                "unit_price": price,
            }
        )
    return out


def _allocate_shortfalls(
    session: Session,
    *,
    items: list[dict[str, Any]],
    budget: Decimal,
) -> tuple[list[dict[str, Any]], Decimal, Decimal, Decimal]:
    """Return purchases, executable, advisory, unused residual of budget."""
    if budget <= ZERO or not items:
        return [], ZERO, ZERO, money(budget)
    total_short = sum((it["shortfall"] for it in items), ZERO)
    if total_short <= ZERO:
        return [], ZERO, ZERO, money(budget)
    scale = Decimal("1")
    if total_short > budget:
        scale = budget / total_short
    purchases: list[dict[str, Any]] = []
    executable = ZERO
    advisory = ZERO
    remaining = money(budget)
    for it in sorted(items, key=lambda x: -x["shortfall"]):
        target_rub = money(it["shortfall"] * scale)
        if target_rub <= ZERO or remaining <= ZERO:
            continue
        target_rub = min(target_rub, remaining)
        sug = _lot_suggestion(
            session,
            symbol=it["symbol"],
            instrument_id=it.get("instrument_id"),
            asset_class=str(it.get("asset_class") or "equity"),
            unit_price=it.get("unit_price"),
            target_rub=target_rub,
        )
        purchases.append(sug)
        if (it.get("asset_class") or "").lower() == "bond" or "ADVISORY_ONLY_BOND_TRADE" in (
            sug.get("limitations") or []
        ):
            advisory = money(advisory + target_rub)
            remaining = money(remaining - target_rub)
            continue
        used = money(sug.get("executable_estimated_notional_rub") or ZERO)
        executable = money(executable + used)
        remaining = money(remaining - used)
        # Unresolved / missing price keeps target in residual (remaining already only reduced by lots).
        if used <= ZERO:
            remaining = money(remaining - ZERO)
    residual = money(remaining)
    return purchases, executable, advisory, residual


def _target_underweight_plan(
    session: Session,
    *,
    snap: PersonalPortfolioSnapshot,
    new_cash: Decimal,
    hyp_nav: Decimal,
    compare: dict[str, Any] | None,
    allow_precise: bool,
    block_reason: str | None,
    instruments: dict[str, Instrument],
) -> dict[str, Any]:
    if block_reason in {"CANDIDATE_STALE", "CANDIDATE_FRESHNESS_UNKNOWN"}:
        return {
            "id": "TARGET_UNDERWEIGHTS",
            "title": "Направить в недовесы",
            "status": "unavailable",
            "reason": block_reason,
            "purchases": [],
            "limitations": [block_reason],
            "target_allocation_rub": "0",
            "executable_notional_rub": "0",
            "advisory_only_rub": "0",
            "residual_cash_rub": str(new_cash),
        }
    if not allow_precise or compare is None:
        return {
            "id": "TARGET_UNDERWEIGHTS",
            "title": "Направить в недовесы",
            "status": "unavailable",
            "reason": "Нет надёжного сравнения с кандидатом или оценка неполная.",
            "purchases": [],
            "limitations": ["CANDIDATE_OR_VALUATION_UNAVAILABLE"],
            "target_allocation_rub": "0",
            "executable_notional_rub": "0",
            "advisory_only_rub": "0",
            "residual_cash_rub": str(new_cash),
        }

    items = [
        it
        for it in _shortfalls(snap=snap, compare=compare, hyp_nav=hyp_nav, instruments=instruments)
        if (it.get("asset_class") or "equity").lower() != "bond"
    ]
    total_short = sum((it["shortfall"] for it in items), ZERO)
    if not items:
        return {
            "id": "TARGET_UNDERWEIGHTS",
            "title": "Направить в недовесы",
            "status": "available",
            "deployed_rub": "0",
            "target_allocation_rub": "0",
            "executable_notional_rub": "0",
            "advisory_only_rub": "0",
            "residual_cash_rub": str(new_cash),
            "portfolio_nav_after_rub": str(hyp_nav),
            "purchases": [],
            "facts": ["Существенных RUB-недовесов относительно кандидата нет."],
            "limitations": [],
        }

    target_alloc = min(total_short, new_cash)
    purchases, executable, advisory, residual = _allocate_shortfalls(
        session, items=items, budget=new_cash
    )
    return {
        "id": "TARGET_UNDERWEIGHTS",
        "title": "Направить в недовесы",
        "status": "available",
        "deployed_rub": str(executable),
        "target_allocation_rub": str(target_alloc),
        "executable_notional_rub": str(executable),
        "advisory_only_rub": str(advisory),
        "residual_cash_rub": str(residual),
        "portfolio_nav_after_rub": str(hyp_nav),
        "cash_share": _f(money(snap.cash_rub + residual) / hyp_nav) if hyp_nav > ZERO else None,
        "purchases": purchases,
        "facts": [
            f"Недовесов: {len(items)}; сумма недовеса {total_short} ₽.",
            f"Целевой объём нового капитала: {target_alloc} ₽.",
            f"Можно оценить по лотам: {executable} ₽; остаётся: {residual} ₽.",
            "Новый капитал не создаёт принудительную продажу существующих позиций.",
            "Избыточный вес не получает новый капитал.",
        ],
        "limitations": ["Нет принудительных продаж из сценария нового капитала."],
    }


def _kraken_allocation_plan(
    session: Session,
    *,
    snap: PersonalPortfolioSnapshot,
    new_cash: Decimal,
    hyp_nav: Decimal,
    compare: dict[str, Any] | None,
    research: dict[str, Any] | None,
    allow_precise: bool,
    block_reason: str | None,
    instruments: dict[str, Instrument],
) -> dict[str, Any]:
    if research is None:
        return {
            "id": "KRAKEN_ALLOCATION",
            "title": "Текущий план Kraken",
            "status": "unavailable",
            "reason": "Research decision недоступен или данные неполны.",
            "purchases": [],
            "limitations": ["RESEARCH_DECISION_UNAVAILABLE"],
            "target_allocation_rub": "0",
            "executable_notional_rub": "0",
            "advisory_only_rub": "0",
            "residual_cash_rub": str(new_cash),
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
            "target_allocation_rub": "0",
            "executable_notional_rub": "0",
            "advisory_only_rub": "0",
            "residual_cash_rub": str(new_cash),
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
    executable = ZERO
    advisory = ZERO
    limitations = ["Гипотетический план; не приказ брокеру."]
    blocked = block_reason in {"CANDIDATE_STALE", "CANDIDATE_FRESHNESS_UNKNOWN"}
    if blocked and block_reason:
        limitations.append(block_reason)

    if deploy_fi > ZERO:
        purchases.append(
            {
                "symbol": None,
                "sleeve": "fixed_income",
                "target_rub": str(deploy_fi),
                "lots": None,
                "units": None,
                "estimated_notional": None,
                "executable_estimated_notional_rub": "0",
                "execution_status": "ADVISORY_ONLY",
                "residual_unexecuted_rub": str(deploy_fi),
                "limitations": ["ADVISORY_ONLY_BOND_TRADE", "NO_FAKE_OFZ_TICKER"],
                "note": "fixed-income sleeve — конкретный тикер OFZ не выдумывается.",
            }
        )
        advisory = money(advisory + deploy_fi)

    if allow_precise and compare is not None and not blocked and deploy_eq > ZERO:
        equity_items = [
            it
            for it in _shortfalls(snap=snap, compare=compare, hyp_nav=hyp_nav, instruments=instruments)
            if (it.get("asset_class") or "equity").lower() != "bond"
        ]
        eq_purchases, eq_exec, eq_adv, _eq_res = _allocate_shortfalls(
            session, items=equity_items, budget=deploy_eq
        )
        purchases.extend(eq_purchases)
        executable = money(executable + eq_exec)
        advisory = money(advisory + eq_adv)
    elif deploy_eq > ZERO and (blocked or not allow_precise or compare is None):
        limitations.append("EQUITY_INSTRUMENTS_DEGRADED")

    residual = money(new_cash - executable - advisory)
    if residual < ZERO:
        residual = ZERO
    status = "available" if (not blocked or deploy_fi > ZERO or keep_cash > ZERO) else "degraded"
    if blocked and executable <= ZERO:
        status = "degraded"
        reason = block_reason
    else:
        reason = None
    return {
        "id": "KRAKEN_ALLOCATION",
        "title": "Текущий план Kraken",
        "status": status,
        "reason": reason,
        "deployed_rub": str(executable),
        "target_allocation_rub": str(money(deploy_eq + deploy_fi)),
        "executable_notional_rub": str(executable),
        "advisory_only_rub": str(advisory),
        "residual_cash_rub": str(residual),
        "portfolio_nav_after_rub": str(hyp_nav),
        "sleeve_targets": {
            "equity_weight": _f(eq),
            "cash_weight": _f(cash_target),
            "fixed_income_weight": _f(fi),
        },
        "purchases": purchases,
        "facts": [
            f"Доля equity/cash/FI в research: {_f(eq)} / {_f(cash_target)} / {_f(fi)}.",
            f"Целевой equity: {deploy_eq} ₽; FI ориентир: {deploy_fi} ₽ (не executable).",
            f"Можно оценить по лотам: {executable} ₽; остаётся: {residual} ₽.",
            "Инструменты equity следуют недовесам кандидата, не равным долям текущих позиций.",
        ],
        "limitations": limitations,
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
        if decision.get("cbr_hurdle_annual") is None and research.get("cbr_hurdle_annual") is None:
            return None
    return {
        "id": "FIXED_INCOME_ALTERNATIVE",
        "title": "Ориентир по fixed-income",
        "status": "advisory",
        "deployed_rub": "0",
        "target_allocation_rub": str(new_cash),
        "executable_notional_rub": "0",
        "advisory_only_rub": str(new_cash),
        "residual_cash_rub": "0",
        "residual_unexecuted_rub": str(new_cash),
        "execution_status": "ADVISORY_ONLY",
        "purchases": [
            {
                "sleeve": "fixed_income",
                "target_rub": str(new_cash),
                "symbol": None,
                "lots": None,
                "estimated_notional": None,
                "executable_estimated_notional_rub": "0",
                "execution_status": "ADVISORY_ONLY",
                "residual_unexecuted_rub": str(new_cash),
                "limitations": ["ADVISORY_ONLY_BOND_TRADE", "NO_FAKE_OFZ_TICKER"],
                "note": "Конкретный OFZ тикер не выдумывается без данных кандидата.",
            }
        ],
        "facts": [
            "Ориентир по fixed-income sleeve — не исполняемая сделка.",
            "Полный ACTIVE bond BUY/SELL учёт ещё заблокирован.",
        ],
        "limitations": ["ADVISORY_ONLY_BOND_TRADE"],
        "cbr_context": _cbr_context(research),
    }
