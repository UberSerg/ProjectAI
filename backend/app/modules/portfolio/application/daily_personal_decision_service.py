"""Daily Personal Decision Engine V1 — orchestrates existing Personal analytics.

Deterministic / rule-based. Does not invent candidate composition, valuation,
or broker orders. Actual book always comes from ``load_personal_snapshot``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.modules.portfolio.application.personal_portfolio_service import (
    PersonalPortfolioSnapshot,
    load_personal_snapshot,
)
from app.modules.portfolio.domain.personal_ledger import ZERO, money
from app.modules.portfolio.infrastructure.models import ManualPortfolio

DISCLAIMER = (
    "Модельная рекомендация по текущему личному портфелю. "
    "Это не приказ брокеру и не гарантия результата."
)

MAX_ACTIONS = 5
WEIGHT_EPS = Decimal("0.02")  # material weight delta (~2 pp)

# Precedence for contradiction guard (higher wins).
_ACTION_RANK = {
    "SETUP": 100,
    "ACTIVATE_JOURNAL": 95,
    "DATA_QUALITY": 90,
    "REVIEW": 70,
    "CONSIDER_REDUCE": 50,
    "CONSIDER_INCREASE": 50,
    "KEEP_CASH": 30,
    "HOLD": 10,
}

_ACTION_TITLE_RU = {
    "SETUP": "Добавить текущий портфель",
    "ACTIVATE_JOURNAL": "Начать учёт с текущего состояния",
    "DATA_QUALITY": "Нужны данные",
    "REVIEW": "Обратить внимание",
    "CONSIDER_INCREASE": "Рассмотреть увеличение",
    "CONSIDER_REDUCE": "Рассмотреть сокращение",
    "KEEP_CASH": "Сохранить кэш",
    "HOLD": "Держать",
}


def _d(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _pct(w: Decimal | float | None) -> str | None:
    if w is None:
        return None
    return f"{float(_d(w)) * 100:.1f}%"


def _action(
    *,
    action: str,
    priority: str,
    title: str,
    rationale: str,
    reason_codes: list[str],
    facts: list[str],
    symbol: str | None = None,
    current_weight: float | None = None,
    target_weight: float | None = None,
    lots_delta: int | None = None,
    units_delta: float | None = None,
    estimated_notional: float | None = None,
    href: str | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    aid = f"{action}:{symbol or 'portfolio'}:{reason_codes[0] if reason_codes else 'x'}"
    return {
        "id": aid,
        "priority": priority,
        "action": action,
        "symbol": symbol,
        "title": title,
        "rationale": rationale,
        "reason_codes": reason_codes,
        "facts": facts[:5],
        "current_weight": current_weight,
        "target_weight": target_weight,
        "lots_delta": lots_delta,
        "units_delta": units_delta,
        "estimated_notional": estimated_notional,
        "href": href,
        "limitations": limitations or [],
    }


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One semantic action per symbol (or portfolio-level key); higher rank wins."""
    best: dict[str, dict[str, Any]] = {}
    for row in actions:
        key = (row.get("symbol") or "__portfolio__").upper()
        rank = _ACTION_RANK.get(str(row.get("action")), 0)
        prev = best.get(key)
        if prev is None or rank > _ACTION_RANK.get(str(prev.get("action")), 0):
            best[key] = row
        elif rank == _ACTION_RANK.get(str(prev.get("action")), 0):
            # Same class: keep higher priority label (HIGH > MEDIUM > LOW).
            order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
            if order.get(str(row.get("priority")), 0) > order.get(str(prev.get("priority")), 0):
                best[key] = row
    # Stable order: HIGH first, then MEDIUM, then LOW; preserve insertion among equals.
    pri_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    out = list(best.values())
    out.sort(key=lambda a: (pri_order.get(str(a.get("priority")), 9), -_ACTION_RANK.get(str(a.get("action")), 0)))
    return out[:MAX_ACTIONS]


def _bind_action_hrefs(actions: list[dict[str, Any]], portfolio_id: int) -> list[dict[str, Any]]:
    """Rewrite portfolio-scoped href placeholders to the selected portfolio id."""
    out: list[dict[str, Any]] = []
    for row in actions:
        href = row.get("href")
        if isinstance(href, str) and "{pid}" in href:
            row = {**row, "href": href.replace("{pid}", str(portfolio_id))}
        elif isinstance(href, str) and href.startswith("/portfolio/mine"):
            row = {
                **row,
                "href": href.replace("/portfolio/mine", f"/portfolio/{portfolio_id}", 1),
            }
        out.append(row)
    return out


def _risk_actions(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for finding in analysis.get("risk_findings") or []:
        code = str(finding.get("code") or "RISK")
        severity = str(finding.get("severity") or "WARN").upper()
        if severity not in {"WARN", "ERROR", "HIGH", "CRITICAL"} and code not in {
            "ISSUER_CONCENTRATION",
            "UNSUPPORTED_VALUATION",
            "MISSING_INSTRUMENT",
        }:
            continue
        symbol = finding.get("symbol") or finding.get("issuer")
        msg = str(finding.get("message") or code)
        priority = (
            "HIGH"
            if code in {"ISSUER_CONCENTRATION", "UNSUPPORTED_VALUATION", "MISSING_INSTRUMENT"}
            else "MEDIUM"
        )
        facts = [msg]
        if finding.get("weight") is not None:
            facts.append(f"Вес ≈ {_pct(_d(finding['weight']))}")
        out.append(
            _action(
                action="REVIEW",
                priority=priority,
                symbol=str(symbol).upper() if symbol else None,
                title=f"{_ACTION_TITLE_RU['REVIEW']}"
                + (f" · {str(symbol).upper()}" if symbol else ""),
                rationale=msg,
                reason_codes=[code],
                facts=facts,
                href="/portfolio/{pid}?tab=decision",
                current_weight=float(finding["weight"]) if finding.get("weight") is not None else None,
            )
        )
    return out


def _bond_review_actions(snap: PersonalPortfolioSnapshot) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pos in snap.positions:
        if (pos.asset_class or "").lower() != "bond":
            continue
        if pos.cost_basis_usable and pos.unrealized_pnl is not None:
            continue
        out.append(
            _action(
                action="REVIEW",
                priority="MEDIUM",
                symbol=pos.symbol,
                title=f"{_ACTION_TITLE_RU['REVIEW']} · {pos.symbol or 'облигация'}",
                rationale=(
                    "Облигация оценена по dirty price, но себестоимость/результат "
                    "пока недоступны — dedicated bond accounting ещё не готов."
                ),
                reason_codes=["BOND_COST_BASIS_UNAVAILABLE"],
                facts=[
                    f"Рыночная стоимость: {pos.market_value} ₽" if pos.market_value is not None else "Цена недоступна",
                    "P&L по облигации не рассчитывается",
                ],
                href="/portfolio/{pid}?tab=holdings",
                limitations=["BOND_TRADE_ACCOUNTING_NOT_READY"],
            )
        )
    return out


def _compare_rebalance_actions(
    *,
    analysis: dict[str, Any],
    compare: dict[str, Any] | None,
    rebalance: dict[str, Any] | None,
    allow_precise: bool,
) -> list[dict[str, Any]]:
    if not allow_precise:
        return []
    out: list[dict[str, Any]] = []
    bond_syms = {
        str(r.get("symbol") or "").upper()
        for r in (analysis.get("positions") or [])
        if (r.get("asset_class") or "").lower() == "bond"
    }

    # Prefer compare semantics (safe REVIEW for NOT_IN_CANDIDATE).
    for row in (compare or {}).get("comparisons") or []:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        status = str(row.get("status") or "")
        suggested = str(row.get("suggested_action") or "").upper()
        mw = row.get("manual_weight")
        cw = row.get("candidate_weight")
        if status == "NOT_IN_CANDIDATE":
            out.append(
                _action(
                    action="REVIEW",
                    priority="MEDIUM",
                    symbol=symbol,
                    title=f"{_ACTION_TITLE_RU['REVIEW']} · {symbol}",
                    rationale=(
                        f"{symbol} есть в вашем портфеле, но отсутствует у текущего кандидата Kraken. "
                        "Это не означает автоматическую продажу."
                    ),
                    reason_codes=["NOT_IN_CANDIDATE"],
                    facts=[
                        f"Ваш вес: {_pct(_d(mw))}" if mw is not None else "Вес неизвестен",
                        "В кандидате: нет",
                    ],
                    current_weight=float(mw) if mw is not None else None,
                    target_weight=None,
                    href="/portfolio/{pid}?tab=compare",
                )
            )
            continue
        if suggested in {"KEEP", "NO_VIEW", ""}:
            continue
        if symbol in bond_syms:
            out.append(
                _action(
                    action="REVIEW",
                    priority="MEDIUM",
                    symbol=symbol,
                    title=f"{_ACTION_TITLE_RU['REVIEW']} · {symbol}",
                    rationale="По облигации точное изменение состава пока advisory/review — учёт сделок не готов.",
                    reason_codes=["BOND_REBALANCE_REVIEW"],
                    facts=[
                        f"Сейчас {_pct(_d(mw))}" if mw is not None else "Вес неизвестен",
                        f"Кандидат {_pct(_d(cw))}" if cw is not None else "Цель неизвестна",
                    ],
                    current_weight=float(mw) if mw is not None else None,
                    target_weight=float(cw) if cw is not None else None,
                    href="/portfolio/{pid}?tab=compare",
                    limitations=["BOND_TRADE_ACCOUNTING_NOT_READY"],
                )
            )
            continue
        if suggested in {"REDUCE", "EXIT"} or (
            mw is not None and cw is not None and _d(mw) - _d(cw) >= WEIGHT_EPS
        ):
            out.append(
                _action(
                    action="CONSIDER_REDUCE",
                    priority="MEDIUM",
                    symbol=symbol,
                    title=f"{_ACTION_TITLE_RU['CONSIDER_REDUCE']} · {symbol}",
                    rationale=(
                        f"Вес {symbol} в вашем портфеле {_pct(_d(mw))}, "
                        f"у текущего кандидата {_pct(_d(cw))}."
                    ),
                    reason_codes=["CANDIDATE_WEIGHT_HIGH"],
                    facts=[
                        f"Сейчас {_pct(_d(mw))}",
                        f"Кандидат {_pct(_d(cw))}",
                    ],
                    current_weight=float(mw) if mw is not None else None,
                    target_weight=float(cw) if cw is not None else None,
                    href="/portfolio/{pid}?tab=rebalance",
                )
            )
        elif suggested in {"INCREASE", "BUY"} or (
            mw is not None and cw is not None and _d(cw) - _d(mw) >= WEIGHT_EPS
        ):
            out.append(
                _action(
                    action="CONSIDER_INCREASE",
                    priority="MEDIUM",
                    symbol=symbol,
                    title=f"{_ACTION_TITLE_RU['CONSIDER_INCREASE']} · {symbol}",
                    rationale=(
                        f"Вес {symbol} в вашем портфеле {_pct(_d(mw) if mw is not None else 0)}, "
                        f"у текущего кандидата {_pct(_d(cw))}."
                    ),
                    reason_codes=["CANDIDATE_WEIGHT_LOW"],
                    facts=[
                        f"Сейчас {_pct(_d(mw))}" if mw is not None else "Сейчас: нет позиции",
                        f"Кандидат {_pct(_d(cw))}",
                    ],
                    current_weight=float(mw) if mw is not None else None,
                    target_weight=float(cw) if cw is not None else None,
                    href="/portfolio/{pid}?tab=rebalance",
                )
            )

    # Enrich with rebalance lot hints when present (non-bond only).
    plan_by_sym = {
        str(r.get("ticker") or "").upper(): r for r in (rebalance or {}).get("plan_rows") or []
    }
    for row in out:
        sym = (row.get("symbol") or "").upper()
        plan = plan_by_sym.get(sym)
        if not plan or sym in bond_syms:
            continue
        if plan.get("lots_delta") is not None:
            row["lots_delta"] = int(plan["lots_delta"])
        if plan.get("units_delta") is not None:
            row["units_delta"] = float(plan["units_delta"])
        if plan.get("estimated_notional") is not None:
            row["estimated_notional"] = float(plan["estimated_notional"])
    return out


def _cash_action(
    *,
    snap: PersonalPortfolioSnapshot,
    research: dict[str, Any] | None,
    allow_precise: bool,
) -> dict[str, Any] | None:
    if not allow_precise or snap.known_nav_rub <= ZERO:
        return None
    cash_share = money(snap.cash_rub) / money(snap.known_nav_rub)
    decision = (research or {}).get("decision") or {}
    target_cash = decision.get("cash_weight")
    if target_cash is None:
        return None
    tc = _d(target_cash)
    if cash_share + WEIGHT_EPS < tc:
        return None  # underweight cash — covered by rebalance increases usually
    if cash_share >= tc:
        return _action(
            action="KEEP_CASH",
            priority="LOW",
            title=_ACTION_TITLE_RU["KEEP_CASH"],
            rationale=(
                f"В портфеле кэш ≈ {_pct(cash_share)}; research-контекст допускает "
                f"около {_pct(tc)} — сохранять кэш нормально."
            ),
            reason_codes=["STRATEGIC_CASH"],
            facts=[f"Кэш сейчас {_pct(cash_share)}", f"Контекст {_pct(tc)}"],
            href="/portfolio/{pid}?tab=decision",
        )
    return None


def _safe_call(label: str, fn: Any) -> tuple[Any | None, str | None]:
    try:
        return fn(), None
    except Exception as exc:  # noqa: BLE001 — graceful degradation for daily decision
        return None, f"{label}: {exc.__class__.__name__}"


def build_daily_personal_decision(
    session: Session,
    *,
    portfolio: ManualPortfolio | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Build advisory Daily Personal Decision for the real user book (read-only)."""
    from app.modules.investment.application.risk_opportunity_service import run_investment_decision
    from app.modules.portfolio.application.manual_portfolio_service import (
        advisory_rebalance,
        analyze_manual_portfolio,
        compare_to_candidate,
    )

    as_of = as_of or datetime.now(UTC).date()
    snap = load_personal_snapshot(session, portfolio)
    degradations: list[str] = []

    # --- Portfolio state gates ---
    if snap.journal_state == "EMPTY" and snap.cash_rub == ZERO and not snap.positions:
        setup = _action(
            action="SETUP",
            priority="HIGH",
            title=_ACTION_TITLE_RU["SETUP"],
            rationale="Добавьте текущий портфель, чтобы Kraken мог анализировать его.",
            reason_codes=["PORTFOLIO_EMPTY"],
            facts=["Портфель пуст", "Позиций нет"],
            href=f"/portfolio/{snap.portfolio.id}?tab=holdings",
        )
        return _pack(
            snap=snap,
            as_of=as_of,
            status="NEEDS_SETUP",
            headline="Сначала добавьте активы",
            summary="Пока нет денег и позиций — персональных действий нет.",
            actions=[setup],
            risks=[],
            analysis=None,
            compare=None,
            rebalance=None,
            research=None,
            degradations=degradations,
        )

    if snap.journal_state == "DRAFT":
        activate = _action(
            action="ACTIVATE_JOURNAL",
            priority="HIGH",
            title="Начать учёт",
            rationale=(
                "Состав портфеля готов к анализу. "
                "Начните учёт, чтобы вести историю операций. "
                "История операций ещё не начата."
            ),
            reason_codes=["PORTFOLIO_DRAFT"],
            facts=[
                f"Кэш: {snap.cash_rub} ₽",
                f"Позиций: {len(snap.positions)}",
            ],
            href=f"/portfolio/{snap.portfolio.id}?tab=holdings",
            limitations=["История операций ещё не начата."],
        )
        analysis, err = _safe_call("analysis", lambda: analyze_manual_portfolio(session, snap.portfolio))
        if err:
            degradations.append(err)
        return _pack(
            snap=snap,
            as_of=as_of,
            status="DRAFT_ANALYSIS",
            headline="Настройка портфеля",
            summary="История операций ещё не начата. Можно анализировать текущий состав.",
            actions=[activate],
            risks=[],
            analysis=analysis,
            compare=None,
            rebalance=None,
            research=None,
            degradations=degradations,
        )

    if snap.journal_state in ("DRAFT", "EMPTY", "LEGACY_PENDING"):
        activate = _action(
            action="ACTIVATE_JOURNAL",
            priority="HIGH",
            title=_ACTION_TITLE_RU["ACTIVATE_JOURNAL"],
            rationale=(
                "История операций ещё не начата. "
                "Зафиксируйте текущий состав как начальное состояние, чтобы вести учёт."
            ),
            reason_codes=["DRAFT_REQUIRES_ACTIVATION"],
            facts=[
                f"Кэш: {snap.cash_rub} ₽",
                f"Позиций: {len(snap.positions)}",
            ],
            href=f"/portfolio/{snap.portfolio.id}?tab=holdings",
        )
        return _pack(
            snap=snap,
            as_of=as_of,
            status="DRAFT_ANALYSIS",
            headline="Настройка портфеля",
            summary="История операций ещё не начата. Анализ состава доступен; журнал — после «Начать учёт».",
            actions=[activate],
            risks=[],
            analysis=None,
            compare=None,
            rebalance=None,
            research=None,
            degradations=degradations + ["DRAFT_NO_JOURNAL"],
        )

    book = snap.portfolio
    analysis, err = _safe_call(
        "analyze", lambda: analyze_manual_portfolio(session, portfolio=book)
    )
    if err:
        degradations.append(err)
    if analysis is None:
        return _pack(
            snap=snap,
            as_of=as_of,
            status="UNAVAILABLE",
            headline="Решение временно недоступно",
            summary="Не удалось собрать аналитику портфеля. Повторите позже.",
            actions=[
                _action(
                    action="DATA_QUALITY",
                    priority="HIGH",
                    title=_ACTION_TITLE_RU["DATA_QUALITY"],
                    rationale="Аналитика портфеля недоступна.",
                    reason_codes=["ANALYSIS_UNAVAILABLE"],
                    facts=degradations[:3] or ["Ошибка анализа"],
                    href="/portfolio/{pid}?tab=decision",
                )
            ],
            risks=[],
            analysis=None,
            compare=None,
            rebalance=None,
            research=None,
            degradations=degradations,
        )

    partial = bool(snap.valuation_partial or analysis.get("valuation_partial"))
    allow_precise = not partial and snap.valuation_complete

    compare = None
    rebalance = None
    if allow_precise:
        compare, cerr = _safe_call(
            "compare", lambda: compare_to_candidate(session, portfolio=book)
        )
        if cerr:
            degradations.append(cerr)
        rebalance, rerr = _safe_call(
            "rebalance", lambda: advisory_rebalance(session, portfolio=book)
        )
        if rerr:
            degradations.append(rerr)
    else:
        degradations.append("precise_rebalance_skipped_partial_valuation")

    research = None
    # Research context uses real Personal NAV only when complete; never invent 100000.
    if allow_precise and snap.known_nav_rub > ZERO:
        capital = money(snap.known_nav_rub)

        def _research() -> dict[str, Any]:
            return run_investment_decision(session, capital=capital)

        research, res_err = _safe_call("research", _research)
        if res_err:
            degradations.append(res_err)
    elif not allow_precise:
        degradations.append("research_skipped_partial_or_unknown_nav")

    actions: list[dict[str, Any]] = []
    if partial:
        missing = [
            p.symbol or str(p.instrument_id)
            for p in snap.positions
            if not p.price_available
        ]
        actions.append(
            _action(
                action="DATA_QUALITY",
                priority="HIGH",
                title=_ACTION_TITLE_RU["DATA_QUALITY"],
                rationale=(
                    "Нельзя надёжно рассчитать полный вес портфеля и инвестиционный результат: "
                    "часть позиций без цены. Неизвестная стоимость не считается нулём."
                ),
                reason_codes=["VALUATION_PARTIAL"],
                facts=[
                    f"Без цены: {', '.join(missing[:5])}" if missing else "Есть позиции без цены",
                    snap.valuation_label or "Частичная оценка",
                    "investment_pnl недоступен",
                ],
                href="/portfolio/{pid}?tab=decision",
                limitations=["NO_PRECISE_REBALANCE"],
            )
        )

    actions.extend(_risk_actions(analysis))
    actions.extend(_bond_review_actions(snap))
    actions.extend(
        _compare_rebalance_actions(
            analysis=analysis,
            compare=compare,
            rebalance=rebalance,
            allow_precise=allow_precise,
        )
    )
    cash_act = _cash_action(snap=snap, research=research, allow_precise=allow_precise)
    if cash_act is not None:
        actions.append(cash_act)

    actions = _dedupe_actions(actions)

    # Drop pure HOLD/KEEP_CASH if stronger actions exist.
    strong = [a for a in actions if a["action"] not in {"HOLD", "KEEP_CASH"}]
    if strong:
        actions = [a for a in actions if a["action"] not in {"HOLD"}][:MAX_ACTIONS]

    risks = [
        {
            "code": f.get("code"),
            "severity": f.get("severity"),
            "message": f.get("message"),
            "symbol": f.get("symbol") or f.get("issuer"),
        }
        for f in (analysis.get("risk_findings") or [])[:10]
    ]

    # NO_ACTION / ALIGNED_WITH_CANDIDATE only with successful compare evidence.
    compare_available = compare is not None and bool(compare.get("candidate_source"))
    soft_only = (not actions) or all(a["action"] in {"KEEP_CASH", "HOLD"} for a in actions)

    if partial:
        status = "PARTIAL"
        headline = "Сначала проверьте данные"
        summary = "Оценка портфеля частичная — точные действия по весам отложены."
    elif soft_only and not compare_available:
        status = "READY"
        headline = "Сравнение с кандидатом недоступно"
        summary = (
            "Портфель оценён, но сравнение с текущим кандидатом Kraken недоступно. "
            "Точное персональное действие не подтверждено."
        )
        actions = [
            _action(
                action="REVIEW",
                priority="MEDIUM",
                title=_ACTION_TITLE_RU["REVIEW"],
                rationale=summary,
                reason_codes=["CANDIDATE_CONTEXT_UNAVAILABLE"],
                facts=[
                    f"NAV ≈ {snap.known_nav_rub} ₽",
                    snap.valuation_label or "Оценка полная",
                    "Кандидат/compare: недоступен",
                ],
                href="/portfolio/{pid}?tab=decision",
                limitations=["NO_CANDIDATE_ALIGNMENT"],
            )
        ]
    elif soft_only and compare_available:
        status = "NO_ACTION"
        headline = "Срочных действий нет"
        summary = (
            "Портфель оценён полностью, серьёзных рисков не видно, "
            "состав близок к текущему кандидату Kraken."
        )
        actions = [
            _action(
                action="HOLD",
                priority="LOW",
                title="Срочных действий нет",
                rationale=summary,
                reason_codes=["ALIGNED_WITH_CANDIDATE"],
                facts=[
                    f"NAV ≈ {snap.known_nav_rub} ₽",
                    snap.valuation_label or "Оценка полная",
                    f"Кандидат: {compare.get('candidate_source')}",
                ],
                href="/portfolio/{pid}?tab=decision",
            )
        ]
    else:
        status = "READY"
        top = actions[0]
        headline = top["title"]
        summary = top["rationale"]

    return _pack(
        snap=snap,
        as_of=as_of,
        status=status,
        headline=headline,
        summary=summary,
        actions=actions,
        risks=risks,
        analysis=analysis,
        compare=compare,
        rebalance=rebalance,
        research=research,
        degradations=degradations,
    )


def _pack(
    *,
    snap: PersonalPortfolioSnapshot,
    as_of: date,
    status: str,
    headline: str,
    summary: str,
    actions: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    analysis: dict[str, Any] | None,
    compare: dict[str, Any] | None,
    rebalance: dict[str, Any] | None,
    research: dict[str, Any] | None,
    degradations: list[str],
) -> dict[str, Any]:
    decision_block = (research or {}).get("decision") if research else None
    bound_actions = _bind_action_hrefs(actions, int(snap.portfolio.id))
    return {
        "as_of": as_of.isoformat(),
        "status": status,
        "headline": headline,
        "summary": summary,
        "portfolio": {
            "id": snap.portfolio.id,
            "portfolio_id": snap.portfolio.id,
            "name": snap.portfolio.name,
            "portfolio_name": snap.portfolio.name,
            "journal_state": snap.journal_state,
            "lifecycle_state": snap.journal_state,
            "cash_rub": str(snap.cash_rub),
            "securities_value_rub": str(snap.securities_value_rub),
            "nav_rub": str(snap.known_nav_rub),
            "contributed_rub": str(snap.contributed_rub),
            "withdrawn_rub": str(snap.withdrawn_rub),
            "investment_pnl_rub": (
                str(snap.investment_pnl_rub) if snap.investment_pnl_rub is not None else None
            ),
            "symbols": snap.symbols,
        },
        "actions": bound_actions,
        "risks": risks,
        "data_quality": {
            "valuation_complete": snap.valuation_complete,
            "valuation_partial": snap.valuation_partial,
            "valuation_as_of": snap.valuation_as_of,
            "valuation_from": snap.valuation_from,
            "valuation_to": snap.valuation_to,
            "valuation_label": snap.valuation_label,
            "missing_price_count": snap.missing_price_count,
            "coverage_pct": (analysis or {}).get("coverage_pct"),
            "quality": (analysis or {}).get("quality"),
            "degradations": degradations,
        },
        "context": {
            "candidate_source": (compare or {}).get("candidate_source"),
            "candidate_id": (compare or {}).get("candidate_id"),
            "rebalance_available": rebalance is not None,
            "research_decision_status": (decision_block or {}).get("status") if decision_block else None,
            "research_equity_weight": (decision_block or {}).get("equity_weight") if decision_block else None,
            "research_cash_weight": (decision_block or {}).get("cash_weight") if decision_block else None,
            "research_used_personal_nav": bool(
                research is not None and snap.valuation_complete and snap.known_nav_rub > ZERO
            ),
            "what_can_change_decision": [
                "новая котировка / полнота оценки",
                "новый Portfolio Candidate",
                "изменение состава Personal Portfolio",
                "обновление Risk & Opportunity / research context",
            ],
        },
        "disclaimer": DISCLAIMER,
    }
