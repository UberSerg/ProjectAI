"""Orchestrate existing investment services into Portfolio Candidate V1."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.investment.application.portfolio_risk_service import assess_portfolio_risk_gate
from app.modules.investment.application.risk_opportunity_service import run_investment_decision
from app.modules.investment.domain.allocation import (
    AllocationCandidate,
    AssetSleeve,
    allocate_integer_lots,
)
from app.modules.investment.domain.fixed_income import TransactionCostProfile
from app.modules.investment.domain.portfolio_candidate import (
    CANDIDATE_VERSION,
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
    cost_bps: Decimal = Decimal("5"),
    stale_after_days: int = 10,
    persist: bool = False,
) -> dict[str, Any]:
    """Aggregate Opportunity → Allocation → Risk Gate → Lots into one candidate."""
    decision_pack = run_investment_decision(
        session,
        profile_id=profile_id,
        capital=capital,
        equity_expected_excess_return=equity_expected_excess_return,
        equity_price=equity_price,
        equity_lot_size=equity_lot_size,
        bond_price=bond_price,
        bond_lot_size=bond_lot_size,
        cost_bps=cost_bps,
    )
    risk_pack = assess_portfolio_risk_gate(
        session,
        capital=capital,
        profile_id=profile_id,
        equity_expected_excess_return=equity_expected_excess_return,
        equity_price=equity_price,
        equity_lot_size=equity_lot_size,
        bond_price=bond_price,
        bond_lot_size=bond_lot_size,
        cost_bps=cost_bps,
    )

    decision = decision_pack.get("decision") or {}
    risk = risk_pack.get("risk_assessment") or {}
    gate_by_symbol = {p["symbol"]: p for p in risk.get("positions") or []}

    target_eq = float(decision.get("equity_weight") or 0.0)
    target_fi = float(decision.get("fixed_income_weight") or 0.0)
    target_cash = float(decision.get("cash_weight") or 0.0)

    eq_gate = gate_by_symbol.get("EQUITY_SLEEVE")
    fi_gate = gate_by_symbol.get("FI_SLEEVE")

    rejected: list[RejectedCandidate] = []
    adj_eq, adj_fi, adj_cash = target_eq, target_fi, target_cash

    # Blocked sleeves: divert weight to cash (no fake FI fallback).
    if eq_gate and eq_gate.get("status") in {"BLOCKED", "INSUFFICIENT_DATA"}:
        rejected.append(
            RejectedCandidate(
                symbol="EQUITY_SLEEVE",
                display_name="Акции (sleeve)",
                sleeve="EQUITY_ALPHA",
                opportunity_hint=_opp_hint(decision_pack.get("equity_opportunity")),
                risk_status=str(eq_gate.get("status")),
                reason_ru="; ".join(eq_gate.get("explanations_ru") or ["Акции заблокированы Risk Gate."]),
            )
        )
        adj_cash += adj_eq
        adj_eq = 0.0
    if fi_gate and fi_gate.get("status") in {"BLOCKED", "INSUFFICIENT_DATA"}:
        fi_opp = decision_pack.get("fixed_income_opportunity") or {}
        rejected.append(
            RejectedCandidate(
                symbol=str((fi_gate.get("reason_codes") or ["FI_SLEEVE"])[0]),
                display_name="Облигации (sleeve)",
                sleeve="FIXED_INCOME",
                opportunity_hint=(
                    f"Доходность ~{float(fi_opp['expected_yield']) * 100:.1f}%"
                    if fi_opp.get("expected_yield") is not None
                    else "FI opportunity"
                ),
                risk_status=str(fi_gate.get("status")),
                reason_ru="; ".join(
                    fi_gate.get("explanations_ru")
                    or ["Облигации не прошли Risk Gate. Капитал остаётся в Cash."]
                ),
            )
        )
        adj_cash += adj_fi
        adj_fi = 0.0

    # Normalize tiny float drift.
    total = adj_eq + adj_fi + adj_cash
    if total > 0 and abs(total - 1.0) > 1e-9:
        adj_eq, adj_fi, adj_cash = adj_eq / total, adj_fi / total, adj_cash / total

    lot_candidates: list[AllocationCandidate] = []
    if adj_eq > 0:
        lot_candidates.append(
            AllocationCandidate(
                symbol="EQUITY_SLEEVE",
                sleeve=AssetSleeve.EQUITY_ALPHA,
                price=equity_price,
                lot_size=equity_lot_size,
                target_weight=Decimal(str(adj_eq)),
            )
        )
    if adj_fi > 0:
        lot_candidates.append(
            AllocationCandidate(
                symbol="FI_SLEEVE",
                sleeve=AssetSleeve.FIXED_INCOME,
                price=bond_price,
                lot_size=bond_lot_size,
                target_weight=Decimal(str(adj_fi)),
            )
        )

    lot_result = allocate_integer_lots(
        lot_candidates,
        capital=capital,
        costs=TransactionCostProfile(cost_bps),
    )

    positions: list[CandidatePosition] = []
    invested_eq = Decimal("0")
    invested_fi = Decimal("0")
    for pos in lot_result.positions:
        gate = gate_by_symbol.get(pos.symbol) or {}
        status = str(gate.get("status") or "RESEARCH_ONLY")
        executable = status in {"APPROVED", "APPROVED_WITH_WARNINGS"}
        if pos.sleeve == AssetSleeve.EQUITY_ALPHA:
            invested_eq += pos.cash_used
            reason = decision.get("why_equity_ru") or "Equity research sleeve."
            if isinstance(decision.get("explanations"), list) and not decision.get("why_equity_ru"):
                reason = decision["explanations"][0] if decision["explanations"] else reason
            conf = decision_pack.get("equity_confidence") or {}
            positions.append(
                CandidatePosition(
                    symbol=pos.symbol,
                    display_name="Акции (research sleeve)",
                    sleeve=pos.sleeve.value,
                    asset_class="equity",
                    lots=pos.lots,
                    units=pos.units,
                    reference_price=pos.execution_price,
                    estimated_notional=pos.notional,
                    estimated_fees=pos.fees,
                    target_weight=adj_eq,
                    actual_weight=float(pos.cash_used / capital) if capital else 0.0,
                    risk_status=status,
                    executable=executable,
                    reason_ru=str(reason),
                    warnings_ru=tuple(gate.get("warnings_ru") or ()),
                    confidence_label_ru=human_confidence_label(conf.get("confidence_level")),
                    extra={"diagnostic": pos.diagnostic},
                )
            )
        else:
            invested_fi += pos.cash_used
            fi_opp = decision_pack.get("fixed_income_opportunity") or {}
            credit = fi_opp.get("credit_quality") or fi_opp.get("credit_status") or "UNKNOWN"
            reason = decision.get("why_fixed_income_ru") or "Fixed Income research sleeve."
            warn = list(gate.get("warnings_ru") or ())
            if str(credit).upper() in {"UNKNOWN", "NOT_RATED"}:
                warn.append("Кредитное качество не подтверждено.")
            positions.append(
                CandidatePosition(
                    symbol=pos.symbol,
                    display_name="Облигации (research sleeve)",
                    sleeve=pos.sleeve.value,
                    asset_class="bond",
                    lots=pos.lots,
                    units=pos.units,
                    reference_price=pos.execution_price,
                    estimated_notional=pos.notional,
                    estimated_fees=pos.fees,
                    target_weight=adj_fi,
                    actual_weight=float(pos.cash_used / capital) if capital else 0.0,
                    risk_status=status,
                    executable=executable,
                    reason_ru=str(reason),
                    warnings_ru=tuple(warn),
                    credit_status=str(credit),
                    liquidity_status=str(fi_opp.get("liquidity") or fi_opp.get("liquidity_status") or "UNKNOWN"),
                    extra={
                        "yield_hint": fi_opp.get("expected_yield"),
                        "support_status": fi_opp.get("support_status"),
                        "diagnostic": pos.diagnostic,
                    },
                )
            )

    # Rejected from explicit risk buckets (single-name style messages).
    for sym in risk.get("blocked") or []:
        if sym in {"EQUITY_SLEEVE", "FI_SLEEVE", "CASH"}:
            continue
        if any(r.symbol == sym for r in rejected):
            continue
        rejected.append(
            RejectedCandidate(
                symbol=sym,
                display_name=sym,
                sleeve="UNKNOWN",
                opportunity_hint=None,
                risk_status="BLOCKED",
                reason_ru="Исключено Risk Gate.",
            )
        )

    strategic_cash_rub = (capital * Decimal(str(adj_cash))).quantize(Decimal("0.01"))
    # Total cash = capital - invested (fees included in cash_used).
    # Separate strategic target vs technical remainder beyond strategic.
    invested = invested_eq + invested_fi
    total_cash = (capital - invested).quantize(Decimal("0.01"))
    tech_remainder = max(Decimal("0"), total_cash - strategic_cash_rub)

    cash = CashBreakdown(
        strategic_target_rub=strategic_cash_rub,
        strategic_target_weight=adj_cash,
        lot_remainder_rub=tech_remainder.quantize(Decimal("0.01")),
        total_cash_rub=total_cash,
    )

    allocation = {
        "equity": build_sleeve_money(capital=capital, target_weight=target_eq, actual_rub=invested_eq).to_dict(),
        "fixed_income": build_sleeve_money(
            capital=capital, target_weight=target_fi, actual_rub=invested_fi
        ).to_dict(),
        "cash": {
            **build_sleeve_money(capital=capital, target_weight=target_cash, actual_rub=total_cash).to_dict(),
            "adjusted_target_weight_after_gate": adj_cash,
        },
        "adjusted_after_gate": {
            "equity_weight": adj_eq,
            "fixed_income_weight": adj_fi,
            "cash_weight": adj_cash,
        },
    }

    conf = decision_pack.get("equity_confidence") or {}
    cal = decision_pack.get("calibration") or {}
    as_of = decision_pack.get("as_of")
    as_of_date = parse_as_of(as_of)
    stale = False
    if as_of_date is not None:
        from datetime import date as date_cls

        stale = (date_cls.today() - as_of_date).days > stale_after_days

    gate_status = str(risk.get("status") or "INSUFFICIENT_DATA")
    insufficient = gate_status == "INSUFFICIENT_DATA" and not positions
    status = classify_candidate_status(
        gate_status=gate_status,
        has_positions=bool(positions),
        stale=stale,
        insufficient=insufficient,
    )

    reasons = list(decision.get("explanations") or [])[:5]
    if not reasons and decision.get("explanation_ru"):
        reasons = [decision["explanation_ru"]]
    warnings = list(decision.get("warnings") or []) + list(risk.get("warnings_ru") or [])
    if decision_pack.get("bond_safety_reminder"):
        warnings.append(decision_pack["bond_safety_reminder"])
    # Deduplicate preserving order
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
    if any((p.credit_status or "").upper() == "UNKNOWN" for p in positions):
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
        "readiness": {
            "mode_ru": "Исследовательский режим",
            "ready_for_real_money": False,
            "banner_ru": "Не готов для автоматического использования реальных денег.",
            "reasons_ru": readiness_reasons,
        },
        "allocation": allocation,
        "positions": [p.to_dict() for p in positions],
        "cash": cash.to_dict(),
        "rejected_candidates": [r.to_dict() for r in rejected],
        "warnings": warnings_unique[:12],
        "reasons_ru": reasons,
        "money": {
            "starting_capital": str(capital),
            "invested": str(invested.quantize(Decimal("0.01"))),
            "fees": str(lot_result.fees),
            "strategic_cash": str(cash.strategic_target_rub),
            "lot_remainder": str(cash.lot_remainder_rub),
            "ending_preview_cash": str(cash.total_cash_rub),
            "tax_note_ru": "До налогов. Налоги пока не включены в расчёт.",
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
            "fi_credit": (decision_pack.get("fixed_income_opportunity") or {}).get("credit_quality"),
            "fi_liquidity": (decision_pack.get("fixed_income_opportunity") or {}).get("liquidity"),
            "gate_status": gate_status,
        },
        "provenance": {
            "profile_id": profile_id,
            "decision_mode": decision_pack.get("mode"),
            "risk_mode": risk_pack.get("mode"),
            "pipeline": "Opportunity → CBR Hurdle → Allocation → Risk Gate → Lots → Portfolio Candidate",
            "lot_mode": lot_result.mode,
            "cost_bps": str(cost_bps),
        },
        "freshness": {
            "market_as_of": as_of,
            "generated_at": generated_at,
            "stale": stale,
            "stale_after_days": stale_after_days,
            "stale_note_ru": (
                "Кандидат построен на устаревших рыночных данных." if stale else None
            ),
        },
        "level_explanations": {
            "level_1_ru": reasons[0] if reasons else "Kraken собрал исследовательский кандидат портфеля.",
            "level_2_ru": conf.get("reason_ru")
            or "Смотрите confidence, hurdle и Risk Gate ниже.",
            "level_3": {
                "gate_status": gate_status,
                "calibration_status": cal.get("calibration_status"),
                "sample_size": cal.get("sample_size"),
                "version": CANDIDATE_VERSION,
            },
        },
        "risk_assessment_summary": {
            "status": gate_status,
            "approved": risk.get("approved") or [],
            "approved_with_warnings": risk.get("approved_with_warnings") or [],
            "research_only": risk.get("research_only") or [],
            "blocked": risk.get("blocked") or [],
            "summary_ru": risk.get("summary_ru"),
        },
        "empty_states": _empty_states(adj_eq, adj_fi, positions, conf),
        "disclaimers_ru": [
            "Это не рекомендация к покупке и не приказ брокеру.",
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


def _opp_hint(eq: dict[str, Any] | None) -> str | None:
    if not eq:
        return None
    excess = eq.get("expected_excess_return")
    if excess is None:
        return "Equity opportunity"
    return f"Excess vs CBR: {float(excess) * 100:.2f}%"


def _empty_states(
    adj_eq: float,
    adj_fi: float,
    positions: list[CandidatePosition],
    conf: dict[str, Any],
) -> dict[str, str]:
    out: dict[str, str] = {}
    if adj_fi <= 0:
        out["no_fi_ru"] = (
            "Сейчас Kraken не нашёл облигаций, которые прошли все проверки риска."
        )
    if (conf.get("confidence_level") or "UNKNOWN").upper() in {"UNKNOWN", "INSUFFICIENT_SAMPLE"}:
        out["equity_confidence_ru"] = (
            "Пока недостаточно завершённых прогнозов для уверенной оценки equity-сигнала."
        )
    if not positions and adj_eq <= 0 and adj_fi <= 0:
        out["all_cash_ru"] = (
            "Kraken пока не видит достаточно подтверждённых возможностей для принятия рыночного риска."
        )
    return out
