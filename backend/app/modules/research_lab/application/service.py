"""Research Lab application service: options, launch, reuse, suite."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.prediction.candidate_config import CANDIDATE_V0_CONFIG
from app.modules.research_lab.catalog import (
    ALLOWED_RESEARCH_SEGMENT,
    CAPITAL_MAX,
    CAPITAL_MIN,
    COST_PRESETS_BPS,
    CUSTOM_COST_MAX_BPS,
    CUSTOM_COST_MIN_BPS,
    PROTECTED_SEGMENT,
    QUICK_SUITE_VARIANTS,
    cost_preset_dicts,
    default_capital,
    display_name_from_config,
    holdout_boundary,
    list_candidates,
    list_policies,
    list_risks,
    resolve_policy_risk_kwargs,
)
from app.modules.research_lab.errors import (
    CandidateMismatch,
    HoldoutLaunchForbidden,
    InvalidCapital,
    InvalidCost,
    InvalidSegment,
    MissingPredictions,
    PeriodOutsideDev,
    RunNotFound,
    UnknownCandidate,
)
from app.modules.simulator.application.predictions import (
    load_oos_predictions,
    prediction_date_bounds,
)
from app.modules.simulator.application.runner import build_spec, describe_ready, run_segment
from app.modules.simulator.config import SimulationSpecV0
from app.modules.simulator.infrastructure.models import SimulationRun, SimulationSpec
from app.modules.simulator.infrastructure.repository import (
    get_nav_series,
    get_run,
    list_runs,
    run_to_summary,
)

LAB_CONTEXT = "RESEARCH_LAB"
MIN_TRADING_DAYS_WARN = 60
SHORT_PERIOD_CALENDAR_DAYS = 180


def _resolve_candidate(candidate_id: str) -> dict[str, Any]:
    for opt in list_candidates():
        if opt.id == candidate_id or opt.candidate_name == candidate_id:
            if not opt.eligible:
                raise UnknownCandidate(f"Кандидат недоступен: {candidate_id}")
            return opt.to_dict()
    raise UnknownCandidate(f"Неизвестный Prediction Candidate: {candidate_id}")


def _dev_bounds() -> tuple[date, date]:
    try:
        bundle = load_oos_predictions(ALLOWED_RESEARCH_SEGMENT)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        raise MissingPredictions(
            "Нет OOS-прогнозов Development для лаборатории.",
            details={"error": str(exc)},
        ) from exc
    return prediction_date_bounds(bundle)


def research_options() -> dict[str, Any]:
    try:
        d0, d1 = _dev_bounds()
        ready = describe_ready()
    except MissingPredictions as exc:
        d0 = d1 = None
        ready = {"error": exc.message}

    return {
        "candidates": [c.to_dict() for c in list_candidates()],
        "prediction_segments": [
            {
                "id": ALLOWED_RESEARCH_SEGMENT,
                "human_label": (
                    "Development OOS — исторические прогнозы вне обучающей выборки"
                ),
                "launchable": True,
                "help_id": "development_oos",
                "date_from": d0.isoformat() if d0 else None,
                "date_to": d1.isoformat() if d1 else None,
            },
            {
                "id": PROTECTED_SEGMENT,
                "human_label": "FINAL HOLDOUT — только просмотр",
                "launchable": False,
                "help_id": "observed_holdout",
                "badge": "Уже наблюдавшийся holdout",
                "explanation": (
                    "Этот период уже использовался для оценки Candidate V0. "
                    "Он больше не является независимым тестом для выбора новой стратегии."
                ),
                "holdout_start": holdout_boundary(),
            },
        ],
        "policies": [p.to_dict() for p in list_policies()],
        "risk_policies": [r.to_dict() for r in list_risks()],
        "cost_presets": cost_preset_dicts(),
        "cost_custom": {
            "allowed": True,
            "min_bps": CUSTOM_COST_MIN_BPS,
            "max_bps": CUSTOM_COST_MAX_BPS,
            "human_label": "Пользовательский исследовательский сценарий",
            "help_id": "simulation_cost",
            "friction_model": (
                "Пресеты Лаборатории задают commission_bps выбранным значением "
                "и slippage_bps=0. В симуляторе commission берётся от abs(notional); "
                "slippage при ненулевом значении сдвигает цену next-open fill."
            ),
        },
        "defaults": {
            "candidate_id": list_candidates()[0].id,
            "segment": ALLOWED_RESEARCH_SEGMENT,
            "policy_id": list_policies()[0].id,
            "risk_id": list_risks()[0].id,
            "commission_bps": 10.0,
            "initial_capital": default_capital(),
            "date_from": d0.isoformat() if d0 else None,
            "date_to": d1.isoformat() if d1 else None,
        },
        "capital_bounds": {"min": CAPITAL_MIN, "max": CAPITAL_MAX},
        "execution_assumptions": {
            "execution": "Next Open",
            "fractional_shares": True,
            "dividends": "excluded",
            "benchmark": "IMOEX price index",
            "no_leverage": True,
            "editable_in_lab": False,
        },
        "period_warnings": {
            "short_calendar_days": SHORT_PERIOD_CALENDAR_DAYS,
            "min_trading_days_soft": MIN_TRADING_DAYS_WARN,
        },
        "quick_suite": {
            "label": "Пакет сравнения",
            "variants": [
                {"policy_id": p, "risk_id": r} for p, r in QUICK_SUITE_VARIANTS
            ],
            "costs_bps": list(COST_PRESETS_BPS),
            "max_configs": len(QUICK_SUITE_VARIANTS) * len(COST_PRESETS_BPS),
        },
        "prediction_ready": ready,
        "holdout_start": holdout_boundary(),
    }


def _fallback_display_name(
    *,
    policy_name: str,
    risk_name: str,
    commission_bps: float,
    date_from: str | None,
    date_to: str | None,
    segment: str,
) -> str:
    base = display_name_from_config(
        policy_id=policy_name or "?",
        risk_id=risk_name or "?",
        commission_bps=commission_bps,
        date_from=date_from,
        date_to=date_to,
    )
    if segment == PROTECTED_SEGMENT:
        return f"{base} · HOLDOUT"
    return base


def enrich_run_summary(session: Session, run: SimulationRun) -> dict[str, Any]:
    summary = run_to_summary(session, run)
    spec_row = session.get(SimulationSpec, run.simulation_spec_id)
    full_payload = dict(spec_row.payload or {}) if spec_row else {}
    risk_name = full_payload.get("risk_name")
    policy_name = full_payload.get("policy_name") or (summary.get("spec") or {}).get(
        "policy_name"
    )
    prov = dict(run.provenance or {})
    lab = prov.get("research_lab") or {}
    name = lab.get("display_name") or _fallback_display_name(
        policy_name=str(policy_name or ""),
        risk_name=str(risk_name or ""),
        commission_bps=float(full_payload.get("commission_bps") or 0.0),
        date_from=summary.get("date_from"),
        date_to=summary.get("date_to"),
        segment=run.segment,
    )
    summary["research"] = {
        "display_name": name,
        "note": lab.get("note"),
        "created_from": lab.get("created_from") or (
            LAB_CONTEXT if lab else "SIMULATOR"
        ),
        "requested_date_from": lab.get("requested_date_from"),
        "requested_date_to": lab.get("requested_date_to"),
        "observed_holdout": run.segment == PROTECTED_SEGMENT,
        "launchable_again": run.segment == ALLOWED_RESEARCH_SEGMENT,
        "context": "historical_research",
        "cost_family_fingerprint": lab.get("cost_family_fingerprint"),
    }
    if summary.get("spec") is not None:
        summary["spec"]["risk_name"] = risk_name
        summary["spec"]["policy_name"] = policy_name
    return summary


def list_research_runs(
    session: Session,
    *,
    limit: int = 100,
    policy_id: str | None = None,
    risk_id: str | None = None,
    status: str | None = None,
    segment: str | None = None,
    commission_bps: float | None = None,
    sort: str = "newest",
) -> list[dict[str, Any]]:
    rows = list_runs(session, limit=max(limit, 200))
    items = [enrich_run_summary(session, r) for r in rows]

    def _match(item: dict[str, Any]) -> bool:
        spec = item.get("spec") or {}
        if policy_id and spec.get("policy_name") != policy_id:
            return False
        if risk_id and spec.get("risk_name") != risk_id:
            return False
        if status and item.get("status") != status:
            return False
        if segment and item.get("segment") != segment:
            return False
        if commission_bps is not None:
            if abs(float(spec.get("commission_bps") or 0.0) - float(commission_bps)) > 1e-9:
                return False
        return True

    filtered = [i for i in items if _match(i)]

    def _metric(item: dict[str, Any], key: str) -> float:
        m = item.get("metrics") or {}
        val = m.get(key)
        return float(val) if val is not None else float("-inf")

    if sort == "return":
        filtered.sort(key=lambda i: _metric(i, "total_price_return"), reverse=True)
    elif sort == "max_drawdown":
        filtered.sort(key=lambda i: _metric(i, "max_drawdown"), reverse=True)
    elif sort == "turnover":
        filtered.sort(key=lambda i: _metric(i, "turnover_ratio"), reverse=True)
    elif sort == "sharpe":
        filtered.sort(key=lambda i: _metric(i, "sharpe_rf0"), reverse=True)
    else:
        filtered.sort(key=lambda i: int(i.get("id") or 0), reverse=True)

    return filtered[:limit]


def _parse_date(value: Any, *, default: date) -> date:
    if value is None or value == "":
        return default
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _validate_launch_request(body: dict[str, Any]) -> dict[str, Any]:
    segment = body.get("segment") or ALLOWED_RESEARCH_SEGMENT
    if segment == PROTECTED_SEGMENT:
        raise HoldoutLaunchForbidden(
            "FINAL HOLDOUT нельзя использовать для запуска новых Research Lab экспериментов. "
            "Период уже наблюдался и не является независимым тестом.",
            details={"segment": segment, "holdout_start": holdout_boundary()},
        )
    if segment != ALLOWED_RESEARCH_SEGMENT:
        raise InvalidSegment(f"Сегмент недоступен для лаборатории: {segment}")

    candidate = _resolve_candidate(str(body.get("candidate_id") or list_candidates()[0].id))
    if (
        candidate["candidate_name"] != CANDIDATE_V0_CONFIG.candidate_name
        or candidate["candidate_version"] != CANDIDATE_V0_CONFIG.candidate_version
    ):
        raise UnknownCandidate("Кандидат не зарегистрирован для Research Lab")

    policy_id = str(body.get("policy_id") or "")
    risk_id = str(body.get("risk_id") or "")
    policy_kwargs = resolve_policy_risk_kwargs(policy_id, risk_id)

    try:
        commission_bps = float(body.get("commission_bps", 10.0))
    except (TypeError, ValueError) as exc:
        raise InvalidCost("Некорректное значение издержек") from exc
    if commission_bps < CUSTOM_COST_MIN_BPS or commission_bps > CUSTOM_COST_MAX_BPS:
        raise InvalidCost(
            f"Издержки должны быть в диапазоне {CUSTOM_COST_MIN_BPS}–{CUSTOM_COST_MAX_BPS} bps",
            details={"commission_bps": commission_bps},
        )
    slippage_bps = float(body.get("slippage_bps") or 0.0)
    if slippage_bps < 0:
        raise InvalidCost("Slippage не может быть отрицательным")

    try:
        capital = float(body.get("initial_capital", default_capital()))
    except (TypeError, ValueError) as exc:
        raise InvalidCapital("Некорректный стартовый капитал") from exc
    if capital <= 0 or capital < CAPITAL_MIN or capital > CAPITAL_MAX:
        raise InvalidCapital(
            f"Стартовый капитал должен быть в диапазоне {CAPITAL_MIN:.0f}–{CAPITAL_MAX:.0f}",
            details={"initial_capital": capital},
        )

    d0, d1 = _dev_bounds()
    date_from = _parse_date(body.get("date_from"), default=d0)
    date_to = _parse_date(body.get("date_to"), default=d1)
    if date_from > date_to:
        raise PeriodOutsideDev("Дата начала позже даты окончания")
    if date_from < d0 or date_to > d1:
        raise PeriodOutsideDev(
            "Период должен лежать внутри доступного Development OOS покрытия",
            details={
                "requested_from": date_from.isoformat(),
                "requested_to": date_to.isoformat(),
                "allowed_from": d0.isoformat(),
                "allowed_to": d1.isoformat(),
            },
        )

    name = (body.get("name") or body.get("display_name") or "").strip() or None
    note = (body.get("note") or "").strip() or None
    if note and len(note) > 2000:
        note = note[:2000]
    force_rerun = bool(body.get("force_rerun") or False)

    cost_label = None
    if abs(slippage_bps) < 1e-12 and any(
        abs(commission_bps - p) < 1e-9 for p in COST_PRESETS_BPS
    ):
        cost_label = f"COST_SENSITIVITY_{int(commission_bps)}bps"

    display = name or display_name_from_config(
        policy_id=policy_id,
        risk_id=risk_id,
        commission_bps=commission_bps,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
    )

    warnings: list[str] = []
    if (date_to - date_from).days < SHORT_PERIOD_CALENDAR_DAYS:
        warnings.append("Короткий период может давать нестабильные выводы.")

    return {
        "candidate": candidate,
        "segment": ALLOWED_RESEARCH_SEGMENT,
        "policy_id": policy_id,
        "risk_id": risk_id,
        "policy_kwargs": {
            **policy_kwargs,
            "initial_capital": capital,
        },
        "commission_bps": commission_bps,
        "slippage_bps": slippage_bps,
        "cost_label": cost_label,
        "initial_capital": capital,
        "date_from": date_from,
        "date_to": date_to,
        "display_name": display,
        "note": note,
        "force_rerun": force_rerun,
        "warnings": warnings,
    }


def fingerprint_excluding_cost(spec: SimulationSpecV0) -> str:
    payload = {
        k: v
        for k, v in spec.to_dict().items()
        if k not in ("commission_bps", "slippage_bps", "cost_sensitivity_label")
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def preview_config_hash(validated: dict[str, Any]) -> tuple[SimulationSpecV0, str, str]:
    bundle = load_oos_predictions(ALLOWED_RESEARCH_SEGMENT)  # type: ignore[arg-type]
    if not bundle.candidate_config_hash:
        raise MissingPredictions("В артефакте прогнозов нет candidate_config_hash")
    cand = validated["candidate"]
    if (
        cand["candidate_name"] != CANDIDATE_V0_CONFIG.candidate_name
        or cand["candidate_version"] != CANDIDATE_V0_CONFIG.candidate_version
    ):
        raise CandidateMismatch("Кандидат не совпадает с артефактом прогнозов")

    spec = build_spec(
        ALLOWED_RESEARCH_SEGMENT,  # type: ignore[arg-type]
        commission_bps=validated["commission_bps"],
        slippage_bps=validated["slippage_bps"],
        cost_sensitivity_label=validated["cost_label"],
        prediction_hash=bundle.prediction_hash,
        candidate_config_hash=bundle.candidate_config_hash,
        dataset_values_hash=bundle.dataset_values_hash,
        **validated["policy_kwargs"],
    )
    return spec, spec.config_hash(), fingerprint_excluding_cost(spec)


def _find_reusable_run(
    session: Session,
    *,
    config_hash: str,
    date_from: date,
    date_to: date,
    initial_capital: float,
) -> SimulationRun | None:
    spec = session.scalar(
        select(SimulationSpec).where(SimulationSpec.config_hash == config_hash)
    )
    if spec is None:
        return None
    payload = dict(spec.payload or {})
    if abs(float(payload.get("initial_capital") or 0.0) - initial_capital) > 1e-6:
        return None
    rows = list(
        session.scalars(
            select(SimulationRun)
            .where(
                SimulationRun.simulation_spec_id == spec.id,
                SimulationRun.status == "SUCCESS",
            )
            .order_by(SimulationRun.id.asc())
        )
    )
    for run in rows:
        prov = dict(run.provenance or {})
        lab = prov.get("research_lab") or {}
        req_from = lab.get("requested_date_from")
        req_to = lab.get("requested_date_to")
        if req_from == date_from.isoformat() and req_to == date_to.isoformat():
            return run
        if run.date_from and run.date_to:
            if abs((run.date_from - date_from).days) <= 5 and abs(
                (run.date_to - date_to).days
            ) <= 14:
                return run
    return None


def launch_research_run(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    """Create or reuse a DEV Research Lab simulation. Never touches Shadow/Forward."""
    validated = _validate_launch_request(body)
    spec, config_hash, cost_family = preview_config_hash(validated)

    if not validated["force_rerun"]:
        existing = _find_reusable_run(
            session,
            config_hash=config_hash,
            date_from=validated["date_from"],
            date_to=validated["date_to"],
            initial_capital=validated["initial_capital"],
        )
        if existing is not None:
            return {
                "outcome": "REUSE_EXISTING",
                "status": "REUSED",
                "message": "Такой эксперимент уже существует.",
                "run": enrich_run_summary(session, existing),
                "config_hash": config_hash,
                "cost_family_fingerprint": cost_family,
                "warnings": validated["warnings"],
                "simulation_executed": False,
            }

    result, run_id = run_segment(
        session,
        ALLOWED_RESEARCH_SEGMENT,  # type: ignore[arg-type]
        date_from=validated["date_from"],
        date_to=validated["date_to"],
        commission_bps=validated["commission_bps"],
        slippage_bps=validated["slippage_bps"],
        cost_sensitivity_label=validated["cost_label"],
        persist=True,
        **validated["policy_kwargs"],
    )
    run = get_run(session, run_id) if run_id else None
    if run is None:
        raise MissingPredictions("Симуляция не сохранила run")

    prov = dict(run.provenance or {})
    prov["research_lab"] = {
        "created_from": LAB_CONTEXT,
        "display_name": validated["display_name"],
        "note": validated["note"],
        "requested_date_from": validated["date_from"].isoformat(),
        "requested_date_to": validated["date_to"].isoformat(),
        "cost_family_fingerprint": cost_family,
        "candidate_id": validated["candidate"]["id"],
        "policy_id": validated["policy_id"],
        "risk_id": validated["risk_id"],
    }
    run.provenance = prov
    session.flush()

    return {
        "outcome": "CREATED",
        "status": "SUCCESS",
        "message": "Эксперимент выполнен.",
        "run": enrich_run_summary(session, run),
        "config_hash": result.config_hash,
        "cost_family_fingerprint": cost_family,
        "warnings": validated["warnings"],
        "simulation_executed": True,
        "metrics": result.metrics,
    }


def plan_quick_suite(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    d0, d1 = _dev_bounds()
    date_from = _parse_date(body.get("date_from"), default=d0)
    date_to = _parse_date(body.get("date_to"), default=d1)
    capital = float(body.get("initial_capital", default_capital()))
    candidate_id = str(body.get("candidate_id") or list_candidates()[0].id)

    planned: list[dict[str, Any]] = []
    for policy_id, risk_id in QUICK_SUITE_VARIANTS:
        for bps in COST_PRESETS_BPS:
            req = {
                "candidate_id": candidate_id,
                "segment": ALLOWED_RESEARCH_SEGMENT,
                "policy_id": policy_id,
                "risk_id": risk_id,
                "commission_bps": bps,
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "initial_capital": capital,
            }
            validated = _validate_launch_request(req)
            _spec, config_hash, _ = preview_config_hash(validated)
            existing = _find_reusable_run(
                session,
                config_hash=config_hash,
                date_from=date_from,
                date_to=date_to,
                initial_capital=capital,
            )
            planned.append(
                {
                    "policy_id": policy_id,
                    "risk_id": risk_id,
                    "commission_bps": bps,
                    "config_hash": config_hash,
                    "exists": existing is not None,
                    "existing_run_id": existing.id if existing else None,
                    "request": req,
                }
            )

    missing = [p for p in planned if not p["exists"]]
    return {
        "label": "Пакет сравнения",
        "total": len(planned),
        "already_exist": len(planned) - len(missing),
        "will_run": len(missing),
        "items": planned,
        "not_optimization": True,
    }


def run_quick_suite(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    plan = plan_quick_suite(session, body)
    created: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    for item in plan["items"]:
        if item["exists"]:
            run = get_run(session, item["existing_run_id"])
            if run:
                reused.append(enrich_run_summary(session, run))
            continue
        out = launch_research_run(session, item["request"])
        if out["outcome"] == "REUSE_EXISTING":
            reused.append(out["run"])
        else:
            created.append(out["run"])
            session.commit()
    return {
        "label": "Пакет сравнения",
        "total": plan["total"],
        "already_exist": plan["already_exist"],
        "created": len(created),
        "reused": len(reused),
        "runs": reused + created,
        "not_optimization": True,
        "message": (
            f"{plan['total']} конфигураций: {plan['already_exist']} уже есть, "
            f"{len(created)} запущено."
        ),
    }


def get_research_run(session: Session, run_id: int) -> dict[str, Any]:
    run = get_run(session, run_id)
    if run is None:
        raise RunNotFound(f"Эксперимент {run_id} не найден")
    summary = enrich_run_summary(session, run)
    nav = get_nav_series(session, run_id)
    summary["nav_preview"] = {
        "points": len(nav),
        "from": nav[0].as_of_date.isoformat() if nav else None,
        "to": nav[-1].as_of_date.isoformat() if nav else None,
    }
    return summary


def config_hash_ignores_note(session: Session, body: dict[str, Any]) -> dict[str, Any]:
    """Test helper: same math hash with/without note."""
    a = _validate_launch_request({**body, "note": None})
    b = _validate_launch_request({**body, "note": "Проверяю влияние комиссий."})
    ha = preview_config_hash(a)[1]
    hb = preview_config_hash(b)[1]
    return {"hash_without_note": ha, "hash_with_note": hb, "equal": ha == hb}
