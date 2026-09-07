"""Orchestrate concrete instrument composition into Portfolio Candidate."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.investment.application.portfolio_composition_service import (
    compose_instrument_selections,
    revalidate_actual_weights,
)
from app.modules.investment.application.risk_opportunity_service import run_investment_decision
from app.modules.investment.domain.allocation import (
    AllocationCandidate,
    AssetSleeve,
    allocate_integer_lots,
)
from app.modules.investment.domain.composition_config import (
    CONCRETE_CANDIDATE_VERSION,
    DEFAULT_COMPOSITION_CONFIG,
    CompositionConfig,
)
from app.modules.investment.domain.equity_composition import equity_reason_ru
from app.modules.investment.domain.fixed_income import TransactionCostProfile
from app.modules.investment.domain.fixed_income_composition import fi_reason_ru
from app.modules.investment.domain.portfolio_candidate import (
    CandidatePosition,
    CashBreakdown,
    RejectedCandidate,
    build_sleeve_money,
    classify_candidate_status,
    diff_candidates,
    human_confidence_label,
    new_candidate_id,
    parse_as_of,
    utc_now_iso,
)
from app.modules.investment.domain.risk_budget import BALANCED_BUDGET

CANDIDATE_VERSION = CONCRETE_CANDIDATE_VERSION


def build_portfolio_candidate(
    session: Session,
    *,
    capital: Decimal = Decimal("100000"),
    profile_id: str = BALANCED_BUDGET.profile_id,
    equity_expected_excess_return: float | None = 0.0,
    equity_price: Decimal = Decimal("300"),
    equity_lot_size: int = 10,
    bond_price: Decimal = Decimal("980"),
    bond_lot_size: int = 1,
    cost_bps: Decimal | None = None,
    stale_after_days: int | None = None,
    persist: bool = False,
    config: CompositionConfig = DEFAULT_COMPOSITION_CONFIG,
) -> dict[str, Any]:
    """Opportunity → Sleeve Allocation → Concrete Selection → Risk Gate → Lots → Candidate."""
    _ = (equity_price, equity_lot_size, bond_price, bond_lot_size)  # legacy API compat
    cost = Decimal(str(cost_bps if cost_bps is not None else config.cost_bps))
    stale_days = stale_after_days if stale_after_days is not None else config.stale_after_days

    decision_pack = run_investment_decision(
        session,
        profile_id=profile_id,
        capital=capital,
        equity_expected_excess_return=equity_expected_excess_return,
        cost_bps=cost,
    )
    decision = decision_pack.get("decision") or {}
    target_eq = float(decision.get("equity_weight") or 0.0)
    target_fi = float(decision.get("fixed_income_weight") or 0.0)
    target_cash = float(decision.get("cash_weight") or 0.0)

    conf = decision_pack.get("equity_confidence") or {}
    confidence_unknown = str(conf.get("confidence_level") or "UNKNOWN").upper() in {
        "UNKNOWN",
        "INSUFFICIENT_SAMPLE",
    }

    composed = compose_instrument_selections(
        session,
        capital=capital,
        equity_sleeve_weight=target_eq,
        fi_sleeve_weight=target_fi,
        profile_id=profile_id,
        confidence_unknown=confidence_unknown,
        config=config,
    )
    equity_sel = composed["equity"]
    fi_sel = composed["fixed_income"]

    rejected: list[RejectedCandidate] = []
    for raw in list(equity_sel.rejected) + list(fi_sel.rejected):
        rejected.append(RejectedCandidate(**raw))
    for raw in composed["equity_meta"].get("unknown_lot_size") or []:
        rejected.append(
            RejectedCandidate(
                symbol=str(raw["symbol"]),
                display_name=str(raw.get("display_name") or raw["symbol"]),
                sleeve="EQUITY_ALPHA",
                opportunity_hint="LOTSIZE unknown",
                risk_status="INSUFFICIENT_DATA",
                reason_ru=str(
                    raw.get("reason_ru")
                    or "Неизвестен размер лота (LOTSIZE) — позиция не включается."
                ),
            )
        )

    # Unrealized sleeve weight → cash (composer may not change economic policy, only fail soft).
    realized_eq_target = equity_sel.equal_weight * len(equity_sel.selected)
    realized_fi_target = fi_sel.equal_weight * len(fi_sel.selected)
    adj_eq = realized_eq_target
    adj_fi = realized_fi_target
    adj_cash = max(0.0, 1.0 - adj_eq - adj_fi)
    # Keep strategic cash at least the decision cash target when possible.
    if adj_cash < target_cash:
        # already denser market risk than requested — leave as is from failed realization
        pass

    lot_candidates: list[AllocationCandidate] = []
    eq_by_sym = {r.symbol: r for r in equity_sel.selected}
    fi_by_sym = {r.symbol: r for r in fi_sel.selected}
    for row in equity_sel.selected:
        if row.lot_size is None or row.lot_size <= 0:
            continue
        lot_candidates.append(
            AllocationCandidate(
                symbol=row.symbol,
                sleeve=AssetSleeve.EQUITY_ALPHA,
                price=row.reference_price,
                lot_size=int(row.lot_size),
                target_weight=Decimal(str(equity_sel.equal_weight)),
            )
        )
    for row in fi_sel.selected:
        lot_candidates.append(
            AllocationCandidate(
                symbol=row.symbol,
                sleeve=AssetSleeve.FIXED_INCOME,
                price=row.dirty_price_per_bond,
                lot_size=row.lot_size,
                target_weight=Decimal(str(fi_sel.equal_weight)),
            )
        )

    lot_result = allocate_integer_lots(
        lot_candidates,
        capital=capital,
        costs=TransactionCostProfile(cost),
    )

    draft_positions: list[dict[str, Any]] = []
    invested_eq = Decimal("0")
    invested_fi = Decimal("0")
    fees_eq = Decimal("0")
    fees_fi = Decimal("0")

    for pos in lot_result.positions:
        if pos.symbol in eq_by_sym:
            row = eq_by_sym[pos.symbol]
            invested_eq += pos.cash_used
            fees_eq += pos.fees
            actual_w = float(pos.cash_used / capital) if capital else 0.0
            draft_positions.append(
                {
                    "symbol": row.symbol,
                    "display_name": row.display_name,
                    "sleeve": "EQUITY_ALPHA",
                    "asset_class": "equity",
                    "instrument_id": row.instrument_id,
                    "lots": pos.lots,
                    "units": pos.units,
                    "lot_size": row.lot_size,
                    "reference_price": pos.execution_price,
                    "estimated_notional": pos.notional,
                    "estimated_fees": pos.fees,
                    "target_weight": equity_sel.equal_weight,
                    "actual_weight": actual_w,
                    "selection_rank": row.rank,
                    "selection_reason": equity_reason_ru(row, semantic=row.signal_semantic),
                    "reason_ru": equity_reason_ru(row, semantic=row.signal_semantic),
                    "warnings_ru": [],
                    "confidence_label_ru": human_confidence_label(conf.get("confidence_level")),
                    "eligibility": "RESEARCH_ONLY" if confidence_unknown else "REAL_PORTFOLIO_CANDIDATE",
                    "signal_semantic": row.signal_semantic,
                    "signal_value": row.signal_value,
                    "data_quality": "READY",
                    "support_status": "SUPPORTED",
                    "risk_flags": ("equity_confidence_unknown",) if confidence_unknown else (),
                    "lot_size_provenance": row.lot_size_provenance,
                }
            )
        elif pos.symbol in fi_by_sym:
            row = fi_by_sym[pos.symbol]
            invested_fi += pos.cash_used
            fees_fi += pos.fees
            actual_w = float(pos.cash_used / capital) if capital else 0.0
            warn = list(row.warnings)
            if str(row.credit_status).upper() in {"UNKNOWN", "NOT_RATED"}:
                warn.append("Кредитное качество не подтверждено.")
            draft_positions.append(
                {
                    "symbol": row.symbol,
                    "display_name": row.display_name,
                    "sleeve": "FIXED_INCOME",
                    "asset_class": "bond",
                    "instrument_id": row.instrument_id,
                    "lots": pos.lots,
                    "units": pos.units,
                    "lot_size": row.lot_size,
                    "reference_price": pos.execution_price,
                    "dirty_price": row.dirty_price_per_bond,
                    "nkd": row.accrued_interest,
                    "estimated_notional": pos.notional,
                    "estimated_fees": pos.fees,
                    "target_weight": fi_sel.equal_weight,
                    "actual_weight": actual_w,
                    "selection_reason": fi_reason_ru(row),
                    "reason_ru": fi_reason_ru(row),
                    "warnings_ru": warn,
                    "credit_status": row.credit_status,
                    "liquidity_status": row.liquidity_status,
                    "eligibility": row.investment_eligibility,
                    "bond_type": row.bond_type,
                    "coupon_rate": row.coupon_rate,
                    "maturity_date": row.maturity_date,
                    "yield_value": row.yield_value,
                    "data_quality": "READY" if row.support_status == "SUPPORTED" else "PARTIAL",
                    "support_status": row.support_status,
                    "risk_flags": row.risk_flags,
                }
            )

    kept, final_rejected = revalidate_actual_weights(
        draft_positions, capital=capital, profile_id=profile_id
    )
    for raw in final_rejected:
        rejected.append(
            RejectedCandidate(
                symbol=str(raw["symbol"]),
                display_name=str(raw.get("display_name") or raw["symbol"]),
                sleeve=str(raw.get("sleeve") or "UNKNOWN"),
                opportunity_hint=raw.get("opportunity_hint"),
                risk_status=str(raw.get("risk_status") or "BLOCKED"),
                reason_ru=str(raw.get("reason_ru") or "Финальная проверка после лотов."),
            )
        )

    # If final gate dropped positions, reclaim cash (do not silently reallocate).
    positions: list[CandidatePosition] = []
    invested_eq = Decimal("0")
    invested_fi = Decimal("0")
    total_fees = Decimal("0")
    fees_eq = Decimal("0")
    fees_fi = Decimal("0")
    for p in kept:
        notional = Decimal(str(p["estimated_notional"]))
        fees = Decimal(str(p["estimated_fees"]))
        cash_used = notional + fees
        if p["sleeve"] == "EQUITY_ALPHA":
            invested_eq += cash_used
            fees_eq += fees
        else:
            invested_fi += cash_used
            fees_fi += fees
        total_fees += fees
        positions.append(
            CandidatePosition(
                symbol=p["symbol"],
                display_name=p["display_name"],
                sleeve=p["sleeve"],
                asset_class=p["asset_class"],
                lots=int(p["lots"]),
                units=int(p["units"]),
                reference_price=Decimal(str(p["reference_price"])),
                estimated_notional=notional,
                estimated_fees=fees,
                target_weight=float(p["target_weight"]),
                actual_weight=float(cash_used / capital) if capital else 0.0,
                risk_status=str(p["risk_status"]),
                executable=bool(p["executable"]),
                reason_ru=str(p["reason_ru"]),
                warnings_ru=tuple(p.get("warnings_ru") or ()),
                credit_status=p.get("credit_status"),
                liquidity_status=p.get("liquidity_status"),
                confidence_label_ru=p.get("confidence_label_ru"),
                instrument_id=p.get("instrument_id"),
                selection_rank=p.get("selection_rank"),
                lot_size=p.get("lot_size"),
                eligibility=p.get("eligibility"),
                bond_type=p.get("bond_type"),
                dirty_price=Decimal(str(p["dirty_price"])) if p.get("dirty_price") is not None else None,
                nkd=Decimal(str(p["nkd"])) if p.get("nkd") is not None else None,
                coupon_rate=p.get("coupon_rate"),
                maturity_date=p.get("maturity_date"),
                yield_value=p.get("yield_value"),
                signal_semantic=p.get("signal_semantic"),
                signal_value=p.get("signal_value"),
                extra={
                    "selection_reason": p.get("selection_reason"),
                    "final_gate_explanations_ru": p.get("final_gate_explanations_ru"),
                    "lot_size_provenance": p.get("lot_size_provenance"),
                },
            )
        )

    # Ensure no synthetic sleeves leaked.
    positions = [p for p in positions if p.symbol not in {"EQUITY_SLEEVE", "FI_SLEEVE"}]

    strategic_cash_rub = (capital * Decimal(str(target_cash))).quantize(Decimal("0.01"))
    invested = invested_eq + invested_fi
    total_cash = (capital - invested).quantize(Decimal("0.01"))
    if total_cash < 0:
        total_cash = Decimal("0")
    tech_remainder = max(Decimal("0"), total_cash - strategic_cash_rub)
    cash = CashBreakdown(
        strategic_target_rub=strategic_cash_rub,
        strategic_target_weight=target_cash,
        lot_remainder_rub=tech_remainder.quantize(Decimal("0.01")),
        total_cash_rub=total_cash,
    )

    allocation = {
        "equity": {
            **build_sleeve_money(capital=capital, target_weight=target_eq, actual_rub=invested_eq).to_dict(),
            "unallocated_rub": str(
                max(Decimal("0"), (capital * Decimal(str(target_eq)) - invested_eq)).quantize(Decimal("0.01"))
            ),
            "positions_count": sum(1 for p in positions if p.sleeve == "EQUITY_ALPHA"),
        },
        "fixed_income": {
            **build_sleeve_money(capital=capital, target_weight=target_fi, actual_rub=invested_fi).to_dict(),
            "unallocated_rub": str(
                max(Decimal("0"), (capital * Decimal(str(target_fi)) - invested_fi)).quantize(Decimal("0.01"))
            ),
            "positions_count": sum(1 for p in positions if p.sleeve == "FIXED_INCOME"),
        },
        "cash": {
            **build_sleeve_money(capital=capital, target_weight=target_cash, actual_rub=total_cash).to_dict(),
        },
        "adjusted_after_composition": {
            "equity_weight": float(invested_eq / capital) if capital else 0.0,
            "fixed_income_weight": float(invested_fi / capital) if capital else 0.0,
            "cash_weight": float(total_cash / capital) if capital else 1.0,
        },
    }

    cal = decision_pack.get("calibration") or {}
    as_of = composed.get("as_of") or decision_pack.get("as_of")
    as_of_date = parse_as_of(as_of)
    stale = False
    if as_of_date is not None:
        from datetime import date as date_cls

        stale = (date_cls.today() - as_of_date).days > stale_days

    research_only = [p.symbol for p in positions if p.risk_status == "RESEARCH_ONLY"]
    executable = [p.symbol for p in positions if p.executable]
    approved = [p.symbol for p in positions if p.risk_status in {"APPROVED", "APPROVED_WITH_WARNINGS"}]
    gate_status = (
        "RESEARCH_ONLY"
        if research_only and not executable
        else ("APPROVED_WITH_WARNINGS" if executable else ("INSUFFICIENT_DATA" if not positions else "RESEARCH_ONLY"))
    )
    insufficient = not positions and (target_eq > 0 or target_fi > 0) and not (
        composed["equity_meta"].get("status") == "OK" or composed["fi_meta"].get("status") == "OK"
    )
    partial = bool(positions) and (
        float(allocation["equity"]["unallocated_rub"]) > 1
        or float(allocation["fixed_income"]["unallocated_rub"]) > 1
    )
    status = classify_candidate_status(
        gate_status=gate_status,
        has_positions=bool(positions),
        stale=stale,
        insufficient=bool(insufficient),
    )
    if partial and status.value == "READY_FOR_RESEARCH":
        from app.modules.investment.domain.portfolio_candidate import PortfolioCandidateStatus

        status = PortfolioCandidateStatus.PARTIAL

    reasons = list(decision.get("explanations") or [])[:3]
    if equity_sel.selected:
        reasons.append(
            f"В equity sleeve включено {len([p for p in positions if p.sleeve == 'EQUITY_ALPHA'])} тикеров "
            f"(из {equity_sel.available_count} сигналов)."
        )
    if fi_sel.selected:
        reasons.append(
            f"В FI sleeve включено {len([p for p in positions if p.sleeve == 'FIXED_INCOME'])} облигаций "
            f"по политике качества данных, не по max YTM."
        )
    if not positions:
        reasons.append(
            "Kraken сейчас не нашёл достаточно подтверждённых возможностей, чтобы принимать дополнительный риск."
        )

    warnings = list(decision.get("warnings") or [])
    if decision_pack.get("bond_safety_reminder"):
        warnings.append(decision_pack["bond_safety_reminder"])
    for p in positions:
        warnings.extend(p.warnings_ru)
    seen: set[str] = set()
    warnings_unique: list[str] = []
    for w in warnings:
        if w and w not in seen:
            seen.add(w)
            warnings_unique.append(w)

    readiness_reasons = [
        f"Equity confidence: {human_confidence_label(conf.get('confidence_level'))}",
        "Taxes: не моделируются",
        "Broker execution: не подключён",
    ]
    if any((p.credit_status or "").upper() in {"UNKNOWN", "NOT_RATED"} for p in positions):
        readiness_reasons.insert(1, "Corporate credit: частично неизвестно")

    candidate_id = new_candidate_id()
    generated_at = utc_now_iso()
    payload: dict[str, Any] = {
        "candidate_id": candidate_id,
        "version": CANDIDATE_VERSION,
        "as_of": as_of,
        "generated_at": generated_at,
        "capital": str(capital),
        "currency": "RUB",
        "status": status.value,
        "title_ru": "Кандидат портфеля Kraken",
        "subtitle_ru": "Исследовательский портфель на основе текущих данных и правил риска.",
        "summary": {
            "positions_count": len(positions),
            "equity_positions": sum(1 for p in positions if p.sleeve == "EQUITY_ALPHA"),
            "fixed_income_positions": sum(1 for p in positions if p.sleeve == "FIXED_INCOME"),
            "equity_rub": str(invested_eq.quantize(Decimal("0.01"))),
            "fixed_income_rub": str(invested_fi.quantize(Decimal("0.01"))),
            "cash_rub": str(total_cash),
            "research_only_count": len(research_only),
            "executable_count": len(executable),
        },
        "readiness": {
            "mode_ru": "Исследовательский режим",
            "ready_for_real_money": False,
            "banner_ru": "Не готов для автоматического использования реальных денег.",
            "reasons_ru": readiness_reasons,
        },
        "allocation": allocation,
        "positions": [p.to_dict() for p in positions],
        "cash": cash.to_dict(),
        "rejected_candidates": [r.to_dict() for r in rejected[: config.max_rejected_shown]],
        "warnings": warnings_unique[:12],
        "reasons_ru": reasons[:5],
        "money": {
            "starting_capital": str(capital),
            "invested": str(invested.quantize(Decimal("0.01"))),
            "equity_invested": str(invested_eq.quantize(Decimal("0.01"))),
            "fixed_income_invested": str(invested_fi.quantize(Decimal("0.01"))),
            "fees": str(total_fees.quantize(Decimal("0.01"))),
            "equity_fees": str(fees_eq.quantize(Decimal("0.01"))),
            "fixed_income_fees": str(fees_fi.quantize(Decimal("0.01"))),
            "strategic_cash": str(cash.strategic_target_rub),
            "lot_remainder": str(cash.lot_remainder_rub),
            "ending_preview_cash": str(cash.total_cash_rub),
            "tax_note_ru": "После расчётных торговых издержек, до налогов. Налоги пока не включены.",
            "broker_note_ru": (
                "Расчёт использует исследовательский профиль торговых издержек, "
                "а не тариф конкретного брокера."
            ),
        },
        "benchmark": {
            "cbr_hurdle_annual": decision_pack.get("cbr_hurdle_annual"),
            "hurdle_1y": decision_pack.get("hurdle_1y"),
            "hurdle_20d": decision_pack.get("hurdle_20d"),
            "horizon": "1y",
            "note_ru": (
                "Kraken берёт рыночный риск только тогда, когда видит основания ожидать "
                "премию относительно стоимости денег. Ставка ЦБ ≠ депозит."
            ),
        },
        "decision_quality": {
            "equity_confidence_level": conf.get("confidence_level"),
            "equity_confidence_label_ru": human_confidence_label(conf.get("confidence_level")),
            "equity_confidence_reason_ru": conf.get("reason_ru")
            or cal.get("uncertainty_note")
            or "Пока недостаточно завершённых прогнозов.",
            "calibration_status": cal.get("calibration_status"),
            "sample_size": conf.get("sample_size") or cal.get("sample_size"),
            "gate_status": gate_status,
        },
        "composition": {
            "equity": {
                "available": equity_sel.available_count,
                "after_gate": equity_sel.after_gate_count,
                "selected": len(equity_sel.selected),
                "provenance": equity_sel.provenance,
                "meta": composed["equity_meta"],
            },
            "fixed_income": {
                "available": fi_sel.available_count,
                "after_filters": fi_sel.after_filters_count,
                "selected": len(fi_sel.selected),
                "provenance": fi_sel.provenance,
                "meta": composed["fi_meta"],
            },
        },
        "provenance": {
            "profile_id": profile_id,
            "candidate_version": CANDIDATE_VERSION,
            "equity_policy": config.equity_policy_version,
            "fixed_income_policy": config.fixed_income_policy_version,
            "pipeline": (
                "Opportunity → Sleeve Allocation → Concrete Instrument Selection → "
                "Per-Instrument Risk Gate → Integer Lots → Final Risk Validation → Portfolio Candidate"
            ),
            "lot_mode": lot_result.mode,
            "cost_bps": str(cost),
            "config": {
                "max_equity_positions": config.max_equity_positions,
                "max_fixed_income_positions": config.max_fixed_income_positions,
                "min_position_rub": config.min_position_rub,
                "max_single_position_weight": config.max_single_position_weight,
                "equity_lot_size_policy": "MOEX_ISS_ONLY_NO_DEFAULT",
            },
        },
        "freshness": {
            "market_as_of": as_of,
            "generated_at": generated_at,
            "stale": stale,
            "stale_after_days": stale_days,
            "stale_note_ru": (
                "Кандидат построен на устаревших рыночных данных." if stale else None
            ),
        },
        "level_explanations": {
            "level_1_ru": reasons[0] if reasons else "Kraken собрал конкретный исследовательский состав.",
            "level_2_ru": (
                "Сначала выбирается доля акций/облигаций, затем конкретные инструменты "
                "внутри sleeve с проверкой риска и целыми лотами."
            ),
            "level_3": {
                "gate_status": gate_status,
                "calibration_status": cal.get("calibration_status"),
                "sample_size": cal.get("sample_size"),
                "version": CANDIDATE_VERSION,
                "equity_meta": composed["equity_meta"],
            },
        },
        "risk_assessment_summary": {
            "status": gate_status,
            "approved": approved,
            "approved_with_warnings": [
                p.symbol for p in positions if p.risk_status == "APPROVED_WITH_WARNINGS"
            ],
            "research_only": research_only,
            "blocked": [r.symbol for r in rejected if r.risk_status == "BLOCKED"],
            "summary_ru": (
                f"Research-only: {len(research_only)}; executable: {len(executable)}; "
                f"отклонено: {len(rejected)}."
            ),
        },
        "empty_states": _empty_states(target_eq, target_fi, positions, conf, equity_sel, fi_sel),
        "disclaimers_ru": [
            "В исследовательский кандидат включено — это не приказ «Купить».",
            "Candidate ≠ Historical Simulator ≠ Shadow.",
        ],
    }

    previous = get_latest_candidate_snapshot(session)
    payload["diff"] = diff_candidates(previous.get("payload") if previous else None, payload)

    if persist:
        saved_id = save_candidate_snapshot(session, payload)
        payload["candidate_id"] = saved_id or candidate_id
        payload["persisted"] = True
    else:
        payload["persisted"] = False

    return payload


def preview_portfolio_candidate(session: Session, **kwargs: Any) -> dict[str, Any]:
    return build_portfolio_candidate(session, persist=False, **kwargs)


def create_portfolio_candidate_snapshot(session: Session, **kwargs: Any) -> dict[str, Any]:
    return build_portfolio_candidate(session, persist=True, **kwargs)


def get_latest_candidate_snapshot(session: Session) -> dict[str, Any] | None:
    if not _snapshots_ready(session):
        return None
    row = session.execute(
        text(
            """
            SELECT candidate_id, as_of, generated_at, capital, status, payload
            FROM investment.portfolio_candidates
            ORDER BY generated_at DESC
            LIMIT 1
            """
        )
    ).mappings().first()
    return dict(row) if row else None


def get_candidate_by_id(session: Session, candidate_id: str) -> dict[str, Any] | None:
    if not _snapshots_ready(session):
        return None
    row = session.execute(
        text(
            """
            SELECT candidate_id, as_of, generated_at, capital, status, payload
            FROM investment.portfolio_candidates
            WHERE candidate_id = :cid
            LIMIT 1
            """
        ),
        {"cid": candidate_id},
    ).mappings().first()
    return dict(row) if row else None


def list_candidate_history(session: Session, *, limit: int = 20) -> list[dict[str, Any]]:
    if not _snapshots_ready(session):
        return []
    rows = session.execute(
        text(
            """
            SELECT candidate_id, as_of, generated_at, capital, status,
                   payload -> 'allocation' AS allocation,
                   payload -> 'summary' AS summary,
                   payload -> 'decision_quality' AS decision_quality
            FROM investment.portfolio_candidates
            ORDER BY generated_at DESC
            LIMIT :lim
            """
        ),
        {"lim": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


def save_candidate_snapshot(session: Session, payload: dict[str, Any]) -> str | None:
    if not _snapshots_ready(session):
        return None
    import json

    cid = str(payload["candidate_id"])
    session.execute(
        text(
            """
            INSERT INTO investment.portfolio_candidates
                (candidate_id, as_of, generated_at, capital, currency, status, version, payload)
            VALUES
                (:candidate_id, CAST(:as_of AS date), CAST(:generated_at AS timestamptz),
                 CAST(:capital AS numeric), :currency, :status, :version,
                 CAST(:payload AS jsonb))
            """
        ),
        {
            "candidate_id": cid,
            "as_of": payload.get("as_of"),
            "generated_at": payload.get("generated_at"),
            "capital": payload.get("capital"),
            "currency": payload.get("currency") or "RUB",
            "status": payload.get("status"),
            "version": payload.get("version") or CANDIDATE_VERSION,
            "payload": json.dumps(payload, ensure_ascii=False, default=str),
        },
    )
    session.commit()
    return cid


def _snapshots_ready(session: Session) -> bool:
    try:
        return bool(
            session.execute(
                text("SELECT to_regclass('investment.portfolio_candidates') IS NOT NULL")
            ).scalar_one()
        )
    except Exception:  # noqa: BLE001
        return False


def _empty_states(
    target_eq: float,
    target_fi: float,
    positions: list[CandidatePosition],
    conf: dict[str, Any],
    equity_sel: Any,
    fi_sel: Any,
) -> dict[str, str]:
    out: dict[str, str] = {}
    if target_fi > 0 and not any(p.sleeve == "FIXED_INCOME" for p in positions):
        out["no_fi_ru"] = (
            "Сейчас Kraken не нашёл облигаций, которые прошли все проверки риска."
        )
    if target_eq > 0 and not any(p.sleeve == "EQUITY_ALPHA" for p in positions):
        out["no_equity_ru"] = (
            "Equity sleeve не удалось развернуть в конкретные тикеры "
            f"(доступно сигналов: {getattr(equity_sel, 'available_count', 0)})."
        )
    if (conf.get("confidence_level") or "UNKNOWN").upper() in {"UNKNOWN", "INSUFFICIENT_SAMPLE"}:
        out["equity_confidence_ru"] = (
            "Пока недостаточно завершённых прогнозов для уверенной оценки equity-сигнала."
        )
    if not positions:
        out["all_cash_ru"] = (
            "Kraken пока не видит достаточно подтверждённых возможностей для принятия рыночного риска."
        )
    return out
