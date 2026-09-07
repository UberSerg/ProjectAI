"""Load market/signal inputs and run Concrete Portfolio Composition V1."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, Instrument
from app.modules.investment.application.credit_liquidity_service import list_bond_risk_assessments
from app.modules.investment.application.equity_lot_size import resolve_equity_lot_sizes
from app.modules.investment.domain.composition_config import (
    DEFAULT_COMPOSITION_CONFIG,
    CompositionConfig,
)
from app.modules.investment.domain.equity_composition import (
    EquityCandidateRow,
    select_equity_composition,
)
from app.modules.investment.domain.fixed_income import calculate_bond_purchase
from app.modules.investment.domain.fixed_income_composition import (
    FixedIncomeCandidateRow,
    select_fixed_income_composition,
)
from app.modules.investment.domain.portfolio_risk_gate import (
    PortfolioRiskGate,
    PositionRiskInput,
)
from app.modules.investment.domain.risk_budget import get_risk_budget
from app.modules.investment.infrastructure.models import BondCashflow, BondMarketSnapshot, BondTerm
from app.modules.prediction.infrastructure.forward_repository import (
    get_latest_success_batch,
    list_predictions_for_batch,
)


def load_equity_candidates(
    session: Session,
    *,
    config: CompositionConfig = DEFAULT_COMPOSITION_CONFIG,
) -> tuple[list[EquityCandidateRow], dict[str, Any]]:
    """Use latest SUCCESS forward batch (active operational model — do not switch V0↔V1)."""
    batch = get_latest_success_batch(session)
    if batch is None:
        return [], {"status": "NO_FORWARD_BATCH"}

    preds = list_predictions_for_batch(session, batch.id)
    if not preds:
        return [], {"status": "EMPTY_BATCH", "batch_id": batch.id}

    instrument_ids = [int(p.instrument_id) for p in preds]
    instruments = {
        int(i.id): i
        for i in session.scalars(
            select(Instrument).where(
                Instrument.id.in_(instrument_ids),
                Instrument.asset_class == "equity",
                Instrument.is_active.is_(True),
            )
        )
    }
    prices = _latest_closes(session, list(instruments.keys()))
    lot_map = resolve_equity_lot_sizes(session, list(instruments.values()), fetch_missing=True)

    rows: list[EquityCandidateRow] = []
    skipped_unknown_lot: list[dict[str, Any]] = []
    for pred in preds:
        inst = instruments.get(int(pred.instrument_id))
        if inst is None:
            continue
        price = prices.get(int(inst.id))
        if price is None or price <= 0:
            continue
        lot_res = lot_map.get(int(inst.id))
        lot_size = lot_res.lot_size if lot_res is not None else None
        provenance = dict(lot_res.provenance) if lot_res is not None else {"reason": "no_resolution"}
        if lot_size is None or lot_size <= 0:
            skipped_unknown_lot.append(
                {
                    "symbol": inst.symbol,
                    "instrument_id": int(inst.id),
                    "status": lot_res.status if lot_res else "UNKNOWN_LOTSIZE",
                    "reason_ru": (
                        "Неизвестен размер лота (LOTSIZE) по источнику MOEX — "
                        "тикер не включается в состав (без silent default=1)."
                    ),
                    "provenance": provenance,
                }
            )
            continue
        rank = int(pred.rank) if pred.rank is not None else 10_000 + int(pred.instrument_id)
        rows.append(
            EquityCandidateRow(
                instrument_id=int(inst.id),
                symbol=inst.symbol,
                display_name=inst.name or inst.symbol,
                rank=rank,
                signal_value=float(pred.predicted_return_20d),
                signal_semantic=str(batch.prediction_semantic or "EXPECTED_RETURN"),
                reference_price=price,
                lot_size=lot_size,
                model_name=batch.candidate_name,
                model_version=batch.candidate_version,
                batch_id=int(batch.id),
                as_of=batch.as_of_date.isoformat(),
                lot_size_provenance=provenance,
            )
        )
    meta = {
        "status": "OK" if rows else ("NO_PRICED_WITH_LOTSIZE" if preds else "EMPTY_BATCH"),
        "batch_id": batch.id,
        "candidate_name": batch.candidate_name,
        "candidate_version": batch.candidate_version,
        "prediction_semantic": batch.prediction_semantic,
        "as_of": batch.as_of_date.isoformat(),
        "prediction_count": len(preds),
        "priced_count": len(rows),
        "unknown_lot_size_count": len(skipped_unknown_lot),
        "unknown_lot_size": skipped_unknown_lot[: config.max_rejected_shown],
        "lot_size_policy": "MOEX_ISS_ONLY_NO_DEFAULT",
    }
    return rows, meta


def load_fixed_income_candidates(
    session: Session,
    *,
    config: CompositionConfig = DEFAULT_COMPOSITION_CONFIG,
) -> tuple[list[FixedIncomeCandidateRow], dict[str, Any]]:
    from app.modules.market.application.research_universe import (
        RESEARCH_FI_V1,
        research_fi_member_ids,
        seed_research_fi_membership,
    )

    # Ensure pin exists once from current BondTerm sample; never auto-grow later.
    seed_research_fi_membership(session, only_if_empty=True)
    pinned_ids = research_fi_member_ids(session)

    risk_report = list_bond_risk_assessments(
        session, limit=200, universe_code=RESEARCH_FI_V1
    )
    risk_by_id = {int(i["instrument_id"]): i for i in risk_report.get("items") or []}

    terms_q = (
        select(Instrument, BondTerm)
        .join(BondTerm, BondTerm.instrument_id == Instrument.id)
        .where(Instrument.asset_class == "bond")
        .order_by(Instrument.symbol)
    )
    if pinned_ids:
        terms_q = terms_q.where(Instrument.id.in_(pinned_ids))
    else:
        # Empty pin → no Candidate FI pool (safe: do not fall back to all BondTerm).
        terms_q = terms_q.where(Instrument.id.in_([-1]))

    terms = session.execute(terms_q).all()

    cf_counts = dict(
        session.execute(
            select(BondCashflow.instrument_id, func.count())
            .group_by(BondCashflow.instrument_id)
        ).all()
    )

    rows: list[FixedIncomeCandidateRow] = []
    for instrument, term in terms:
        if (term.currency or "RUB").upper() not in {"RUB", "SUR"}:
            continue
        snap = session.scalar(
            select(BondMarketSnapshot)
            .where(BondMarketSnapshot.instrument_id == instrument.id)
            .order_by(desc(BondMarketSnapshot.as_of))
            .limit(1)
        )
        if snap is None or snap.clean_price_percent is None:
            continue
        nominal = Decimal(term.nominal or 0)
        lot_size = int(term.lot_size or 1)
        clean = Decimal(snap.clean_price_percent)
        nkd = Decimal(snap.accrued_interest or 0)
        dirty = calculate_bond_purchase(
            nominal=nominal,
            clean_price_percent=clean,
            accrued_interest_per_bond=nkd,
            lots=1,
            lot_size=1,
        ).dirty_total
        risk = risk_by_id.get(int(instrument.id), {})
        rows.append(
            FixedIncomeCandidateRow(
                instrument_id=int(instrument.id),
                symbol=instrument.symbol,
                display_name=instrument.name or instrument.symbol,
                bond_type=str(term.bond_type),
                support_status=str(term.support_status),
                credit_status=str(risk.get("credit_status") or term.credit_quality_status or "UNKNOWN"),
                liquidity_status=str(risk.get("liquidity_status") or "UNKNOWN"),
                investment_eligibility=str(risk.get("investment_eligibility") or "RESEARCH_ONLY"),
                lot_size=lot_size,
                nominal=nominal,
                clean_price_percent=clean,
                accrued_interest=nkd,
                dirty_price_per_bond=dirty,
                coupon_rate=float(term.coupon_rate) if term.coupon_rate is not None else None,
                maturity_date=term.maturity_date.isoformat() if term.maturity_date else None,
                yield_value=float(snap.yield_value) if snap.yield_value is not None else None,
                cashflow_count=int(cf_counts.get(instrument.id) or 0),
                risk_flags=tuple(risk.get("risk_flags") or ()),
                warnings=tuple(risk.get("warnings") or ()),
            )
        )

    meta = {
        "status": "OK" if rows else "NO_BONDS",
        "audited_count": len(terms),
        "with_snapshot": len(rows),
        "risk_as_of": risk_report.get("as_of"),
        "universe_code": RESEARCH_FI_V1,
        "universe_pinned_count": len(pinned_ids),
        "note": (
            "Candidate FI pool is pinned to research_fi_v1. "
            "Enrichment expands catalog valuation only; strategy universe stays "
            "pinned until an explicit version bump."
        ),
    }
    return rows, meta


def pre_gate_equity(
    rows: list[EquityCandidateRow],
    *,
    sleeve_weight: float,
    profile_id: str,
    confidence_unknown: bool,
) -> dict[str, str]:
    """Per-instrument Risk Gate before sizing (credit/liquidity/eligibility; not lot math)."""
    if not rows or sleeve_weight <= 0:
        return {}
    budget = get_risk_budget(profile_id)
    gate = PortfolioRiskGate(
        max_single_position=budget.max_single_position,
        allow_unknown_credit_research=budget.max_credit_risk != "NONE",
    )
    # Use a concentration-safe probe weight so pre-gate does not false-block the whole sleeve.
    n = min(len(rows), DEFAULT_COMPOSITION_CONFIG.max_equity_positions) or 1
    tw = min(sleeve_weight / n, budget.max_single_position * 0.999)
    out: dict[str, str] = {}
    for row in rows:
        verdict = gate.assess_position(
            PositionRiskInput(
                symbol=row.symbol,
                sleeve="EQUITY_ALPHA",
                target_weight=tw,
                data_quality="READY",
                support_status="SUPPORTED",
                investment_eligibility="RESEARCH_ONLY" if confidence_unknown else "REAL_PORTFOLIO_CANDIDATE",
                liquidity_status="UNKNOWN",
                risk_flags=("equity_confidence_unknown",) if confidence_unknown else (),
            )
        )
        out[row.symbol] = verdict.status.value
    return out


def pre_gate_fixed_income(
    rows: list[FixedIncomeCandidateRow],
    *,
    sleeve_weight: float,
    profile_id: str,
) -> dict[str, str]:
    if not rows or sleeve_weight <= 0:
        return {}
    budget = get_risk_budget(profile_id)
    gate = PortfolioRiskGate(
        max_single_position=budget.max_single_position,
        allow_unknown_credit_research=budget.max_credit_risk != "NONE",
    )
    n = min(len(rows), DEFAULT_COMPOSITION_CONFIG.max_fixed_income_positions) or 1
    tw = min(sleeve_weight / n, budget.max_single_position * 0.999)
    out: dict[str, str] = {}
    for row in rows:
        verdict = gate.assess_position(
            PositionRiskInput(
                symbol=row.symbol,
                sleeve="FIXED_INCOME",
                target_weight=tw,
                data_quality="READY" if row.support_status == "SUPPORTED" else "PARTIAL",
                credit_status=row.credit_status,
                liquidity_status=row.liquidity_status,
                support_status=row.support_status,
                investment_eligibility=row.investment_eligibility,
                expected_yield=row.yield_value,
                risk_flags=row.risk_flags,
            )
        )
        out[row.symbol] = verdict.status.value
    return out


def revalidate_actual_weights(
    positions: list[dict[str, Any]],
    *,
    capital: Decimal,
    profile_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Final Risk Gate on actual post-lot weights; demote/exclude concentrators."""
    budget = get_risk_budget(profile_id)
    gate = PortfolioRiskGate(
        max_single_position=budget.max_single_position,
        allow_unknown_credit_research=budget.max_credit_risk != "NONE",
    )
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for pos in positions:
        actual_w = float(pos.get("actual_weight") or 0.0)
        verdict = gate.assess_position(
            PositionRiskInput(
                symbol=str(pos["symbol"]),
                sleeve=str(pos.get("sleeve") or "EQUITY_ALPHA"),
                target_weight=actual_w,
                notional=Decimal(str(pos.get("estimated_notional") or 0)),
                data_quality=str(pos.get("data_quality") or "READY"),
                credit_status=pos.get("credit_status"),
                liquidity_status=pos.get("liquidity_status"),
                support_status=pos.get("support_status"),
                investment_eligibility=pos.get("eligibility") or pos.get("investment_eligibility"),
                risk_flags=tuple(pos.get("risk_flags") or ()),
            )
        )
        pos = {
            **pos,
            "risk_status": verdict.status.value,
            "executable": verdict.status.value in {"APPROVED", "APPROVED_WITH_WARNINGS"},
            "warnings_ru": list(dict.fromkeys(list(pos.get("warnings_ru") or []) + list(verdict.warnings_ru))),
            "final_gate_explanations_ru": list(verdict.explanations_ru),
        }
        if verdict.status.value in {"BLOCKED", "INSUFFICIENT_DATA"} or not verdict.allowed_in_portfolio:
            rejected.append(
                {
                    "symbol": pos["symbol"],
                    "display_name": pos.get("display_name"),
                    "sleeve": pos.get("sleeve"),
                    "opportunity_hint": pos.get("selection_reason"),
                    "risk_status": verdict.status.value,
                    "reason_ru": "; ".join(verdict.explanations_ru)
                    or "Исключено финальной проверкой после лотов.",
                }
            )
            continue
        kept.append(pos)
    return kept, rejected


def compose_instrument_selections(
    session: Session,
    *,
    capital: Decimal,
    equity_sleeve_weight: float,
    fi_sleeve_weight: float,
    profile_id: str,
    confidence_unknown: bool,
    config: CompositionConfig = DEFAULT_COMPOSITION_CONFIG,
) -> dict[str, Any]:
    equity_rows, equity_meta = load_equity_candidates(session, config=config)
    fi_rows, fi_meta = load_fixed_income_candidates(session, config=config)

    eq_gate = pre_gate_equity(
        equity_rows,
        sleeve_weight=equity_sleeve_weight,
        profile_id=profile_id,
        confidence_unknown=confidence_unknown,
    )
    fi_gate = pre_gate_fixed_income(
        fi_rows, sleeve_weight=fi_sleeve_weight, profile_id=profile_id
    )

    equity_sel = select_equity_composition(
        equity_rows,
        sleeve_weight=equity_sleeve_weight,
        capital=capital,
        gate_status_by_symbol=eq_gate,
        config=config,
    )
    fi_sel = select_fixed_income_composition(
        fi_rows,
        sleeve_weight=fi_sleeve_weight,
        capital=capital,
        gate_status_by_symbol=fi_gate,
        config=config,
    )
    return {
        "equity": equity_sel,
        "fixed_income": fi_sel,
        "equity_meta": equity_meta,
        "fi_meta": fi_meta,
        "pre_gate": {"equity": eq_gate, "fixed_income": fi_gate},
        "as_of": equity_meta.get("as_of") or date.today().isoformat(),
    }


def _latest_closes(session: Session, instrument_ids: list[int]) -> dict[int, Decimal]:
    if not instrument_ids:
        return {}
    out: dict[int, Decimal] = {}
    for iid in instrument_ids:
        candle = session.scalar(
            select(Candle)
            .where(Candle.instrument_id == iid, Candle.timeframe == "1d")
            .order_by(desc(Candle.timestamp))
            .limit(1)
        )
        if candle is not None and candle.close is not None:
            out[iid] = Decimal(str(candle.close))
    return out
