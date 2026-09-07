"""Manual Portfolio V1 application services."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.infrastructure.market.models import Instrument
from app.modules.fundamentals.infrastructure.models import Issuer, SecurityIssuerMapping
from app.modules.investment.application.equity_lot_size import resolve_equity_lot_sizes
from app.modules.investment.application.portfolio_candidate_service import (
    get_latest_candidate_snapshot,
    preview_portfolio_candidate,
)
from app.modules.investment.domain.fixed_income import TransactionCostProfile
from app.modules.investment.infrastructure.models import BondTerm
from app.modules.market.application.instrument_capabilities import resolve_instrument_capabilities
from app.modules.market.application.research_universe import is_research_member
from app.modules.portfolio.domain.lots import LotValidationError, assert_lot_compatible
from app.modules.portfolio.domain.valuation import PositionValuation, value_position
from app.modules.portfolio.infrastructure.models import ManualPortfolio, ManualPosition
from app.modules.shadow.domain.lot_plan import PlanInstrument, build_lot_order_plan

PRIMARY_NAME = "Primary Manual Portfolio"


def _d(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def get_or_create_primary(session: Session) -> ManualPortfolio:
    row = session.scalar(
        select(ManualPortfolio)
        .options(selectinload(ManualPortfolio.positions))
        .order_by(ManualPortfolio.id.asc())
        .limit(1)
    )
    if row is not None:
        return row
    row = ManualPortfolio(
        name=PRIMARY_NAME,
        source="MANUAL",
        base_currency="RUB",
        cash_rub=Decimal("0"),
        version=1,
    )
    session.add(row)
    session.flush()
    return row


def portfolio_to_dict(portfolio: ManualPortfolio) -> dict[str, Any]:
    return {
        "id": portfolio.id,
        "name": portfolio.name,
        "source": portfolio.source,
        "base_currency": portfolio.base_currency,
        "cash_rub": float(portfolio.cash_rub),
        "version": portfolio.version,
        "created_at": portfolio.created_at.isoformat() if portfolio.created_at else None,
        "updated_at": portfolio.updated_at.isoformat() if portfolio.updated_at else None,
        "positions": [
            {
                "id": p.id,
                "instrument_id": p.instrument_id,
                "units": float(p.units),
                "average_price": float(p.average_price) if p.average_price is not None else None,
                "note": p.note,
                "non_standard_lot": bool(p.non_standard_lot),
            }
            for p in (portfolio.positions or [])
        ],
    }


def update_cash(session: Session, cash_rub: Decimal) -> ManualPortfolio:
    portfolio = get_or_create_primary(session)
    if cash_rub < 0:
        raise ValueError("cash_rub must be non-negative")
    portfolio.cash_rub = _d(cash_rub)
    portfolio.updated_at = datetime.now(UTC)
    portfolio.version = int(portfolio.version or 1) + 1
    session.flush()
    return portfolio


def _resolve_lot_size(session: Session, instrument: Instrument) -> int | None:
    if (instrument.asset_class or "").lower() == "bond":
        term = session.scalar(select(BondTerm).where(BondTerm.instrument_id == instrument.id))
        if term is None or term.lot_size is None:
            return None
        return int(term.lot_size)
    lots = resolve_equity_lot_sizes(session, [instrument], fetch_missing=False)
    res = lots.get(int(instrument.id))
    return res.lot_size if res else None


def add_position(
    session: Session,
    *,
    instrument_id: int,
    units: Decimal,
    average_price: Decimal | None = None,
    note: str | None = None,
    non_standard_lot: bool = False,
) -> ManualPosition:
    portfolio = get_or_create_primary(session)
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise LookupError("instrument_not_found")
    units_d = _d(units)
    if units_d <= 0:
        raise ValueError("units must be positive")
    lot_size = _resolve_lot_size(session, instrument)
    assert_lot_compatible(units_d, lot_size, non_standard_lot=non_standard_lot)

    existing = session.scalar(
        select(ManualPosition).where(
            ManualPosition.portfolio_id == portfolio.id,
            ManualPosition.instrument_id == instrument_id,
        )
    )
    now = datetime.now(UTC)
    if existing is not None:
        existing.units = units_d
        existing.average_price = average_price
        existing.note = note
        existing.non_standard_lot = non_standard_lot
        existing.updated_at = now
        pos = existing
    else:
        pos = ManualPosition(
            portfolio_id=portfolio.id,
            instrument_id=instrument_id,
            units=units_d,
            average_price=average_price,
            note=note,
            non_standard_lot=non_standard_lot,
        )
        session.add(pos)
    portfolio.updated_at = now
    portfolio.version = int(portfolio.version or 1) + 1
    session.flush()

    # P0 enrichment for newly added / updated bond positions.
    if (instrument.asset_class or "").lower() == "bond":
        try:
            from app.modules.investment.application.enrichment_service import enqueue_fi_kinds
            from app.modules.investment.domain.enrichment import EnrichmentPriority

            enqueue_fi_kinds(session, int(instrument.id), EnrichmentPriority.P0_PORTFOLIO)
        except Exception:  # noqa: BLE001
            pass
    return pos


def patch_position(
    session: Session,
    position_id: int,
    *,
    units: Decimal | None = None,
    average_price: Decimal | None = None,
    note: str | None = None,
    non_standard_lot: bool | None = None,
) -> ManualPosition:
    portfolio = get_or_create_primary(session)
    pos = session.get(ManualPosition, position_id)
    if pos is None or pos.portfolio_id != portfolio.id:
        raise LookupError("position_not_found")
    instrument = session.get(Instrument, pos.instrument_id)
    if instrument is None:
        raise LookupError("instrument_not_found")

    new_units = _d(units) if units is not None else _d(pos.units)
    flag = bool(pos.non_standard_lot) if non_standard_lot is None else bool(non_standard_lot)
    if units is not None or non_standard_lot is not None:
        lot_size = _resolve_lot_size(session, instrument)
        assert_lot_compatible(new_units, lot_size, non_standard_lot=flag)
        pos.units = new_units
        pos.non_standard_lot = flag
    if average_price is not None:
        pos.average_price = average_price
    if note is not None:
        pos.note = note
    pos.updated_at = datetime.now(UTC)
    portfolio.updated_at = pos.updated_at
    portfolio.version = int(portfolio.version or 1) + 1
    session.flush()
    return pos


def delete_position(session: Session, position_id: int) -> None:
    portfolio = get_or_create_primary(session)
    pos = session.get(ManualPosition, position_id)
    if pos is None or pos.portfolio_id != portfolio.id:
        raise LookupError("position_not_found")
    session.delete(pos)
    portfolio.updated_at = datetime.now(UTC)
    portfolio.version = int(portfolio.version or 1) + 1
    session.flush()


def _issuer_key(session: Session, instrument_id: int, symbol: str) -> tuple[str, str]:
    mapping = session.scalar(
        select(SecurityIssuerMapping)
        .where(
            SecurityIssuerMapping.instrument_id == instrument_id,
            SecurityIssuerMapping.issuer_id.is_not(None),
        )
        .limit(1)
    )
    if mapping is not None and mapping.issuer_id is not None:
        issuer = session.get(Issuer, mapping.issuer_id)
        title = issuer.title if issuer is not None else f"issuer:{mapping.issuer_id}"
        return f"issuer:{mapping.issuer_id}", title
    # Fallback: strip preferred suffix for crude issuer aggregate.
    base = symbol[:-1] if symbol.endswith("P") and len(symbol) > 1 else symbol
    return f"symbol_family:{base}", base


def analyze_manual_portfolio(session: Session) -> dict[str, Any]:
    portfolio = get_or_create_primary(session)
    cash = _d(portfolio.cash_rub)
    valuations: list[PositionValuation] = []
    findings: list[dict[str, Any]] = []
    rows_out: list[dict[str, Any]] = []
    issuer_mv: dict[str, dict[str, Any]] = {}

    for pos in portfolio.positions or []:
        instrument = session.get(Instrument, pos.instrument_id)
        if instrument is None:
            findings.append(
                {
                    "code": "MISSING_INSTRUMENT",
                    "severity": "WARN",
                    "instrument_id": pos.instrument_id,
                    "message": "Position references missing instrument",
                }
            )
            continue
        val = value_position(session, instrument, _d(pos.units))
        valuations.append(val)
        caps = resolve_instrument_capabilities(session, instrument)
        suggested = _suggest_action(val, caps, candidate_weight=None)
        ikey, ititle = _issuer_key(session, int(instrument.id), instrument.symbol)
        if val.market_value is not None:
            bucket = issuer_mv.setdefault(
                ikey, {"issuer_key": ikey, "issuer_title": ititle, "market_value": Decimal("0")}
            )
            bucket["market_value"] = _d(bucket["market_value"]) + val.market_value
        rows_out.append(
            {
                "position_id": pos.id,
                "instrument_id": instrument.id,
                "symbol": instrument.symbol,
                "units": float(pos.units),
                "market_value": float(val.market_value) if val.market_value is not None else None,
                "unit_price": float(val.unit_price) if val.unit_price is not None else None,
                "quality": val.quality,
                "price_source": val.price_source,
                "supported": val.supported,
                "detail": val.detail,
                "capabilities": caps.to_dict(),
                "suggested_action": suggested,
                "research_member": is_research_member(session, int(instrument.id)),
            }
        )
        if not val.supported:
            findings.append(
                {
                    "code": "UNSUPPORTED_VALUATION",
                    "severity": "WARN",
                    "symbol": instrument.symbol,
                    "message": "Position cannot be valued; not treated as zero",
                    "detail": val.detail,
                }
            )

    supported_mv = sum((_d(v.market_value) for v in valuations if v.market_value is not None), Decimal("0"))
    unsupported = sum(1 for v in valuations if not v.supported)
    nav = cash + supported_mv
    allocation = []
    for row in rows_out:
        mv = row["market_value"]
        weight = (Decimal(str(mv)) / nav) if mv is not None and nav > 0 else None
        row["weight"] = float(weight) if weight is not None else None
        if weight is not None:
            allocation.append({"symbol": row["symbol"], "weight": float(weight), "sleeve": row.get("symbol")})

    concentration = []
    for bucket in issuer_mv.values():
        mv = _d(bucket["market_value"])
        w = (mv / nav) if nav > 0 else Decimal("0")
        concentration.append(
            {
                "issuer_key": bucket["issuer_key"],
                "issuer_title": bucket["issuer_title"],
                "market_value": float(mv),
                "weight": float(w),
            }
        )
        if w >= Decimal("0.25"):
            findings.append(
                {
                    "code": "ISSUER_CONCENTRATION",
                    "severity": "WARN",
                    "issuer": bucket["issuer_title"],
                    "weight": float(w),
                    "message": "Issuer aggregate weight >= 25% (advisory)",
                }
            )

    qualities = {v.quality for v in valuations}
    if not valuations:
        quality = "LIVE"
    elif "UNSUPPORTED" in qualities and supported_mv == 0:
        quality = "STALE"
    elif "UNSUPPORTED" in qualities or "STALE" in qualities or "PARTIAL" in qualities:
        quality = "PARTIAL"
    else:
        quality = "LIVE"

    total_positions = len(portfolio.positions or [])
    coverage_pct = (
        100.0 * (total_positions - unsupported) / total_positions if total_positions else 100.0
    )

    return {
        "portfolio": portfolio_to_dict(portfolio),
        "cash_rub": float(cash),
        "market_value_supported": float(supported_mv),
        "nav": float(nav),
        "positions": rows_out,
        "allocation": allocation,
        "concentration_by_issuer": sorted(concentration, key=lambda x: -x["weight"]),
        "risk_findings": findings,
        "coverage_pct": coverage_pct,
        "quality": quality,
        "unsupported_count": unsupported,
        "advisory": True,
        "note": "Risk findings are advisory; not a BLOCKED gate",
    }


def _suggest_action(
    val: PositionValuation,
    caps: Any,
    *,
    candidate_weight: Decimal | None,
) -> str:
    if not val.supported:
        return "REVIEW"
    if candidate_weight is None:
        return "NO_VIEW"
    if candidate_weight <= 0 and val.units > 0:
        return "EXIT"
    # Weight comparison done in compare/rebalance paths.
    return "KEEP"


def compare_to_candidate(session: Session) -> dict[str, Any]:
    analysis = analyze_manual_portfolio(session)
    nav = _d(analysis["nav"])
    latest = get_latest_candidate_snapshot(session)
    if latest and latest.get("payload"):
        candidate = dict(latest["payload"])
        candidate_source = "snapshot"
    else:
        candidate = preview_portfolio_candidate(session, capital=max(nav, Decimal("100000")))
        candidate_source = "live_preview"

    cand_positions = candidate.get("positions") or candidate.get("payload", {}).get("positions") or []
    if isinstance(candidate.get("payload"), dict) and not cand_positions:
        cand_positions = candidate["payload"].get("positions") or []

    cand_weights: dict[str, Decimal] = {}
    for row in cand_positions:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or row.get("ticker") or "").upper()
        w = row.get("weight") or row.get("target_weight")
        if not symbol or w is None:
            continue
        cand_weights[symbol] = _d(w)

    manual_weights = {
        str(r["symbol"]).upper(): _d(r["weight"])
        for r in analysis["positions"]
        if r.get("weight") is not None
    }

    comparisons = []
    all_symbols = sorted(set(manual_weights) | set(cand_weights))
    for symbol in all_symbols:
        mw = manual_weights.get(symbol)
        cw = cand_weights.get(symbol)
        status = "BOTH"
        if mw is None:
            status = "NOT_IN_MANUAL"
        elif cw is None:
            status = "NOT_IN_CANDIDATE"  # ≠ SELL
        action = "NO_VIEW"
        if status == "NOT_IN_CANDIDATE":
            action = "REVIEW"
        elif status == "NOT_IN_MANUAL":
            action = "INCREASE"
        elif mw is not None and cw is not None:
            delta = mw - cw
            if abs(delta) < Decimal("0.02"):
                action = "KEEP"
            elif delta > 0:
                action = "REDUCE"
            else:
                action = "INCREASE"
        comparisons.append(
            {
                "symbol": symbol,
                "manual_weight": float(mw) if mw is not None else None,
                "candidate_weight": float(cw) if cw is not None else None,
                "status": status,
                "suggested_action": action,
                "note": (
                    "NOT_IN_CANDIDATE does not imply SELL"
                    if status == "NOT_IN_CANDIDATE"
                    else None
                ),
            }
        )

    return {
        "nav": float(nav),
        "candidate_source": candidate_source,
        "candidate_id": candidate.get("candidate_id"),
        "comparisons": comparisons,
        "manual_analysis": {
            "coverage_pct": analysis["coverage_pct"],
            "quality": analysis["quality"],
            "risk_findings": analysis["risk_findings"],
        },
    }


def advisory_rebalance(session: Session) -> dict[str, Any]:
    analysis = analyze_manual_portfolio(session)
    nav = _d(analysis["nav"])
    cash = _d(analysis["cash_rub"])
    compare = compare_to_candidate(session)
    cand_weights = {
        c["symbol"]: _d(c["candidate_weight"])
        for c in compare["comparisons"]
        if c.get("candidate_weight") is not None
    }
    # Scale candidate weights to sum ~1 over overlapping + candidate-only names.
    weight_sum = sum(cand_weights.values(), Decimal("0"))
    scaled = {
        s: (w / weight_sum if weight_sum > 0 else Decimal("0"))
        for s, w in cand_weights.items()
    }

    plan_instruments: list[PlanInstrument] = []
    review_rows: list[dict[str, Any]] = []
    portfolio = get_or_create_primary(session)
    pos_by_symbol: dict[str, ManualPosition] = {}
    for pos in portfolio.positions or []:
        inst = session.get(Instrument, pos.instrument_id)
        if inst is None:
            continue
        pos_by_symbol[inst.symbol.upper()] = pos

    symbols = sorted(set(scaled) | set(pos_by_symbol))
    for idx, symbol in enumerate(symbols):
        instrument = session.scalar(
            select(Instrument).where(Instrument.symbol == symbol, Instrument.exchange == "MOEX")
        )
        if instrument is None:
            review_rows.append({"symbol": symbol, "reason": "MISSING_INSTRUMENT", "action": "REVIEW"})
            continue
        pos = pos_by_symbol.get(symbol)
        current_units = _d(pos.units) if pos else Decimal("0")
        val = value_position(session, instrument, current_units if current_units > 0 else Decimal("1"))
        price = val.unit_price
        lot_size = _resolve_lot_size(session, instrument)
        tw = scaled.get(symbol, Decimal("0"))
        asset = (instrument.asset_class or "").lower()
        if asset == "bond" and pos is not None and tw > 0:
            # FI exact mismatch → REVIEW not forced swap
            review_rows.append(
                {
                    "symbol": symbol,
                    "reason": "FIXED_INCOME_REVIEW",
                    "action": "REVIEW",
                    "manual_units": float(current_units),
                    "target_weight": float(tw),
                }
            )
            continue
        if price is None or price <= 0:
            review_rows.append(
                {"symbol": symbol, "reason": "NO_PRICE", "action": "REVIEW", "target_weight": float(tw)}
            )
            continue
        plan_instruments.append(
            PlanInstrument(
                instrument_id=int(instrument.id),
                ticker=symbol,
                target_weight=tw,
                current_units=current_units,
                price=price,
                lot_size=lot_size,
                rank=idx + 1,
                priority=idx + 1,
            )
        )

    costs = TransactionCostProfile(broker_bps=Decimal("0"))
    plan = build_lot_order_plan(
        plan_instruments,
        cash=cash,
        nav=nav if nav > 0 else Decimal("1"),
        costs=costs,
        strategic_cash_reserve=Decimal("0"),
    )
    return {
        "advisory": True,
        "persisted_orders": False,
        "nav": float(nav),
        "cash": float(cash),
        "projected_cash": float(plan.projected_cash),
        "plan_rows": [
            {
                "instrument_id": r.instrument_id,
                "ticker": r.ticker,
                "action": r.action,
                "lots_delta": r.lots_delta,
                "units_delta": float(r.units_delta),
                "target_weight": float(r.target_weight),
                "current_weight": float(r.current_weight),
                "estimated_price": float(r.estimated_price) if r.estimated_price is not None else None,
                "estimated_notional": float(r.estimated_notional),
                "lot_size": r.lot_size,
                "reason": r.reason,
            }
            for r in plan.rows
        ],
        "review_rows": review_rows,
        "diagnostics": plan.diagnostics,
        "cash_safe": plan.projected_cash >= 0,
    }


__all__ = [
    "LotValidationError",
    "add_position",
    "advisory_rebalance",
    "analyze_manual_portfolio",
    "compare_to_candidate",
    "delete_position",
    "get_or_create_primary",
    "patch_position",
    "portfolio_to_dict",
    "update_cash",
]
