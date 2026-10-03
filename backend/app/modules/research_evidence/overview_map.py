"""Map frozen evidence artifacts to the OWNER UI aggregate contract.

Never emit overall_accuracy / master_score / kraken_score / production_readiness_score.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.modules.research_evidence.ablation import (
    VARIANT_BASE,
    VARIANT_BASE_EVENTS,
    VARIANT_BASE_FUNDAMENTALS,
    VARIANT_V4_FULL,
)
from app.modules.research_evidence.experiment import EVALUATION_WORDING, EXPERIMENT_VERSION

FORBIDDEN_OVERVIEW_KEYS = frozenset(
    {
        "overall_accuracy",
        "master_score",
        "kraken_score",
        "production_readiness_score",
    }
)

REQUIRED_LIMITATIONS: list[dict[str, str]] = [
    {
        "code": "total_return_incomplete",
        "title": "Total Return неполный",
        "detail": "Дивиденды и total-return метки не являются готовым universe-wide рядом.",
    },
    {
        "code": "dividends_excluded",
        "title": "Дивиденды исключены",
        "detail": "Исторический OOS и симулятор считают MECHANICAL_PRICE_RETURN, не Total Return.",
    },
    {
        "code": "bank_fi_partial",
        "title": "Банки / FI — частичный фундаментал",
        "detail": "Промышленные FNS-коэффициенты для банков и FI не подставляются наугад.",
    },
    {
        "code": "delisted_partial",
        "title": "Исторические делистинги покрыты частично",
        "detail": "Неполный exit по цене помечает экономику PARTIAL, выход не выдумывается.",
    },
    {
        "code": "current_only_weaker",
        "title": "CURRENT_ONLY слабее DATED_WINDOW",
        "detail": "Идентичность эмитента CURRENT_ONLY — более слабое PIT-основание.",
    },
    {
        "code": "fractional_sizing",
        "title": "Дробные research-веса",
        "detail": "position_sizing = FRACTIONAL_RESEARCH_WEIGHTS, не лотовая реалистичность брокера.",
    },
    {
        "code": "assumed_costs",
        "title": "Издержки — допущения",
        "detail": "0/10/30/50 bps all-in per side — research assumptions, не исторический тариф брокера.",
    },
    {
        "code": "no_auto_promotion",
        "title": "Нет авто-промоушена Candidate",
        "detail": "persist_registry=false. ACTIVE DatasetSpec и Candidate V0/V1 не меняются.",
    },
]

_ABLATION_UI = {
    VARIANT_BASE: "base",
    VARIANT_BASE_FUNDAMENTALS: "fund",
    VARIANT_BASE_EVENTS: "events",
    VARIANT_V4_FULL: "full_v4",
}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "PENDING"}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {"status": "PENDING", "value": raw}


def _pending(part: dict[str, Any] | None) -> bool:
    return not part or part.get("status") == "PENDING"


def _ic(metrics: dict[str, Any] | None) -> float | None:
    if not metrics:
        return None
    rank = metrics.get("rank_ic")
    if isinstance(rank, dict):
        val = rank.get("mean_ic")
        return float(val) if isinstance(val, int | float) else None
    if isinstance(rank, int | float):
        return float(rank)
    if isinstance(metrics.get("mean_ic"), int | float):
        return float(metrics["mean_ic"])
    return None


def _spread(metrics: dict[str, Any] | None) -> float | None:
    if not metrics:
        return None
    tb = metrics.get("top_bottom") or metrics.get("top_minus_bottom")
    if isinstance(tb, dict):
        val = tb.get("top_minus_bottom")
        return float(val) if isinstance(val, int | float) else None
    if isinstance(tb, int | float):
        return float(tb)
    return None


def _n(metrics: dict[str, Any] | None, fallback: dict[str, Any] | None = None) -> int | None:
    if metrics and isinstance(metrics.get("n"), int | float):
        return int(metrics["n"])
    if fallback and isinstance(fallback.get("n_rows"), int | float):
        return int(fallback["n_rows"])
    return None


def _first_int(*values: Any) -> int | None:
    """Keep explicit 0; never coerce missing / NaN to 0."""
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value == value and value not in (float("inf"), float("-inf")):
            return int(value)
    return None


def _signal(part: dict[str, Any], *, family: str) -> dict[str, Any]:
    if _pending(part):
        return {"family": family, "available": False, "notes": "CHRONOLOGICAL OOS RESEARCH ещё не посчитан."}
    metrics = part.get("metrics") if isinstance(part.get("metrics"), dict) else None
    folds = part.get("folds") if isinstance(part.get("folds"), list) else []
    fold_year = []
    for fold in folds:
        m = fold.get("metrics") if isinstance(fold, dict) else None
        fold_year.append(
            {
                "fold": str(fold.get("fold_id")) if isinstance(fold, dict) else None,
                "year": None,
                "rank_ic": _ic(m if isinstance(m, dict) else None),
                "spread": _spread(m if isinstance(m, dict) else None),
                "n": _n(m if isinstance(m, dict) else None),
            }
        )
    ics = [row["rank_ic"] for row in fold_year if isinstance(row.get("rank_ic"), int | float)]
    consistent = None
    if len(ics) >= 2:
        consistent = (max(ics) - min(ics)) < 0.5
    return {
        "family": family,
        "available": part.get("status") not in {None, "PENDING", "insufficient"},
        "rank_ic": _ic(metrics),
        "spread": _spread(metrics),
        "n": _n(metrics, part),
        "fold_year": fold_year,
        "consistent": consistent,
        "notes": part.get("note") or EVALUATION_WORDING,
    }


def _ablation_rows(ablation: dict[str, Any], paired: dict[str, Any] | None) -> list[dict[str, Any]]:
    variants = ablation.get("variants") if isinstance(ablation.get("variants"), dict) else {}
    ci = None
    if isinstance(paired, dict) and paired.get("status") != "INSUFFICIENT":
        ic_delta = paired.get("ic_delta") if isinstance(paired.get("ic_delta"), dict) else {}
        ci = (ic_delta.get("ci95_low"), ic_delta.get("ci95_high"))
    rows = []
    for name, ui in _ABLATION_UI.items():
        payload = variants.get(name) if isinstance(variants.get(name), dict) else {}
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else None
        row = {
            "variant": ui,
            "label": name,
            "mean_oos_ic": _ic(metrics),
            "spread": _spread(metrics),
            "n": _n(metrics, payload),
            "bootstrap_ci_low": None,
            "bootstrap_ci_high": None,
        }
        if ui == "full_v4" and ci is not None:
            row["bootstrap_ci_low"] = ci[0]
            row["bootstrap_ci_high"] = ci[1]
        rows.append(row)
    return rows


def _economics_ui(econ: dict[str, Any], experiment_id: str) -> dict[str, Any]:
    if _pending(econ):
        return {
            "experiment_id": experiment_id,
            "simulation_kind": "historical_oos_research",
            "return_kind": "PRICE_RETURN",
            "dividends": "excluded",
            "partial": True,
            "notes": "Историческая OOS симуляция ещё не посчитана.",
            "scenarios": [],
        }
    variants = econ.get("variants") if isinstance(econ.get("variants"), dict) else {}
    primary = variants.get("V4_FULL") or next(iter(variants.values()), {}) if variants else {}
    if not isinstance(primary, dict):
        primary = {}
    gross = primary.get("gross") if isinstance(primary.get("gross"), dict) else {}
    net = primary.get("net_by_cost_bps") if isinstance(primary.get("net_by_cost_bps"), dict) else {}
    bench = (
        (primary.get("primary_benchmark") or {}).get("net_by_cost_bps")
        if isinstance(primary.get("primary_benchmark"), dict)
        else {}
    )
    if not isinstance(bench, dict):
        bench = {}

    def _ret(metrics: Any) -> float | None:
        if not isinstance(metrics, dict):
            return None
        val = metrics.get("cumulative_price_return")
        return float(val) if isinstance(val, int | float) else None

    def _mdd(metrics: Any) -> float | None:
        if not isinstance(metrics, dict):
            return None
        val = metrics.get("max_drawdown")
        return float(val) if isinstance(val, int | float) else None

    def _to(metrics: Any) -> float | None:
        if not isinstance(metrics, dict):
            return None
        val = metrics.get("turnover")
        return float(val) if isinstance(val, int | float) else None

    scenarios = [
        {
            "id": "gross",
            "label": "gross (0 bps)",
            "commission_bps": 0,
            "total_return": _ret(gross),
            "max_drawdown": _mdd(gross),
            "turnover_ratio": _to(gross),
            "benchmark_return": _ret(bench.get(0) or bench.get("0")),
        }
    ]
    for bps, key in ((10, "net_10bps"), (30, "net_30bps"), (50, "net_50bps")):
        m = net.get(bps) or net.get(str(bps))
        b = bench.get(bps) or bench.get(str(bps))
        scenarios.append(
            {
                "id": key,
                "label": f"net {bps} bps (допущение)",
                "commission_bps": bps,
                "total_return": _ret(m),
                "max_drawdown": _mdd(m),
                "turnover_ratio": _to(m),
                "benchmark_return": _ret(b),
                "excess_vs_benchmark": (
                    None
                    if _ret(m) is None or _ret(b) is None
                    else float(_ret(m)) - float(_ret(b))
                ),
            }
        )
    return {
        "experiment_id": experiment_id,
        "simulation_kind": "historical_oos_research",
        "return_kind": "PRICE_RETURN",
        "dividends": "excluded",
        "benchmark": "eligible-universe equal-weight",
        "scenarios": scenarios,
        "max_drawdown": _mdd(gross),
        "turnover_ratio": _to(gross),
        "partial": primary.get("status") == "PARTIAL" or econ.get("status") == "PARTIAL",
        "notes": econ.get("wording")
        or "Историческая OOS симуляция, не фактический счёт. PRICE_RETURN, дивиденды исключены.",
    }


def map_prospective_ui(prospective: dict[str, Any]) -> dict[str, Any]:
    if _pending(prospective):
        return {
            "status": "EMPTY",
            "empty": True,
            "n_observations": 0,
            "notes": "Проспективные наблюдения не загружены.",
            "observations": [],
        }
    pdm = prospective.get("personal_decision_memory") if isinstance(
        prospective.get("personal_decision_memory"), dict
    ) else {}
    fwd = prospective.get("forward_predictions") if isinstance(
        prospective.get("forward_predictions"), dict
    ) else {}
    captures = int(pdm.get("captures_total") or 0)
    matured = 0
    by_h = pdm.get("by_horizon") if isinstance(pdm.get("by_horizon"), dict) else {}
    for blob in by_h.values():
        if isinstance(blob, dict):
            matured += int(blob.get("matured") or blob.get("n_ready") or 0)
    fwd_n = int(fwd.get("matured_observations") or fwd.get("evaluated_count") or 0)
    n = captures + fwd_n
    empty = n == 0 and matured == 0
    return {
        "status": "INSUFFICIENT_SAMPLE" if n and n < 5 else ("EMPTY" if empty else "OBSERVED"),
        "empty": empty,
        "n_observations": n,
        "notes": (
            "Проспективные наблюдения отделены от исторического OOS. "
            "Связь с PersonalOperation не доказывает причинность. "
            "Нет комбинированной «точности Kraken»."
        ),
        "observations": [],
    }


def empty_overview() -> dict[str, Any]:
    payload = {
        "experiment": {
            "id": None,
            "name": "Research Evidence Engine V1",
            "version": EXPERIMENT_VERSION,
            "purpose": EVALUATION_WORDING,
            "status": "EMPTY",
            "checking": [
                "Добавляет ли V4 предиктивную информацию сверх V3?",
                "Какие группы признаков V4 дают evidence?",
                "Устойчив ли эффект по времени / когортам?",
                "Выживает ли ranking в long-only симуляции?",
                "Насколько результат чувствителен к издержкам?",
                "Какие prospective наблюдения уже есть?",
            ],
            "notes": "RESEARCH ONLY. Не торговый контур и не production Candidate.",
        },
        "dataset": None,
        "historical_models": {
            "regression": {"family": "regression", "available": False},
            "ranker": {"family": "ranker", "available": False},
        },
        "ablation": {"rows": [], "partial": True, "notes": "Нет посчитанной абляции."},
        "stability": {"fold_year": [], "notes": EVALUATION_WORDING},
        "economics": {
            "return_kind": "PRICE_RETURN",
            "dividends": "excluded",
            "partial": True,
            "scenarios": [],
            "notes": "Историческая OOS симуляция, не фактический счёт.",
        },
        "prospective": {
            "status": "EMPTY",
            "empty": True,
            "n_observations": 0,
            "notes": "Проспективный блок отделён от исторического OOS.",
            "observations": [],
        },
        "limitations": list(REQUIRED_LIMITATIONS),
    }
    assert FORBIDDEN_OVERVIEW_KEYS.isdisjoint(payload.keys())
    return payload


def overview_from_dir(path: Path) -> dict[str, Any]:
    overview_file = _load_json(path / "evidence_overview.json")
    if overview_file.get("status") != "PENDING" and "experiment" in overview_file:
        for key in FORBIDDEN_OVERVIEW_KEYS:
            overview_file.pop(key, None)
        limitations = overview_file.get("limitations") or []
        if not limitations:
            overview_file["limitations"] = list(REQUIRED_LIMITATIONS)
        return overview_file

    manifest = _load_json(path / "manifest.json")
    dataset = _load_json(path / "dataset_compare.json")
    regression = _load_json(path / "model_regression.json")
    ranker = _load_json(path / "model_ranker.json")
    ablation = _load_json(path / "ablation.json")
    stability = _load_json(path / "stability.json")
    economics = _load_json(path / "economics.json")
    prospective = _load_json(path / "prospective.json")
    experiment_id = str(manifest.get("experiment_fingerprint") or path.name)
    identity = manifest.get("identity") if isinstance(manifest.get("identity"), dict) else {}
    pop = dataset.get("population") if isinstance(dataset.get("population"), dict) else {}
    v3 = dataset.get("v3") if isinstance(dataset.get("v3"), dict) else {}
    v4 = dataset.get("v4") if isinstance(dataset.get("v4"), dict) else {}
    cov = v4.get("coverage_summary") if isinstance(v4.get("coverage_summary"), dict) else {}
    paired = ablation.get("paired_delta") if isinstance(ablation.get("paired_delta"), dict) else None

    payload = {
        "experiment": {
            "id": experiment_id,
            "name": "Research Evidence Engine V1",
            "version": EXPERIMENT_VERSION,
            "purpose": EVALUATION_WORDING,
            "status": manifest.get("bundle_status") or "COMPLETE",
            "dataset_from": identity.get("date_from"),
            "dataset_to": identity.get("date_to"),
            "checking": empty_overview()["experiment"]["checking"],
            "notes": "RESEARCH ONLY. CHRONOLOGICAL OOS RESEARCH, не pristine final holdout.",
        },
        "dataset": {
            "universe_label": identity.get("historical_universe_version")
            or "historical_equity_universe_v2",
            "labels": ["forward_return_20d"],
            "feature_count_v3": (dataset.get("schema") or {}).get("v3_feature_count")
            if isinstance(dataset.get("schema"), dict)
            else None,
            "feature_count_v4": (dataset.get("schema") or {}).get("v4_feature_count")
            if isinstance(dataset.get("schema"), dict)
            else None,
            "sample_identity_match": bool(dataset.get("sample_identity_match") or pop.get("sample_identity_match")),
            "pit_violations": _first_int(
                dataset.get("pit_violations"),
                v4.get("pit_violations"),
                v3.get("pit_violations"),
            ),
            "fund_coverage": cov.get("fundamental_coverage_pct") or cov.get("fundamentals_coverage"),
            "event_coverage": cov.get("event_coverage_pct") or cov.get("events_coverage"),
            "current_only_share": cov.get("current_only_share") or cov.get("current_only_pct"),
            "bank_fi_unsupported": cov.get("bank_fi_unsupported_samples"),
            "total_return_status": "incomplete",
            "date_from": identity.get("date_from"),
            "date_to": identity.get("date_to"),
            "partial": dataset.get("status") == "PENDING",
        },
        "historical_models": {
            "regression": _signal(regression, family="regression"),
            "ranker": _signal(ranker, family="ranker"),
        },
        "ablation": {
            "rows": _ablation_rows(ablation, paired),
            "partial": _pending(ablation),
            "notes": "Одна и та же выборка и y; отличается только маска признаков (NATIVE_NAN).",
        },
        "stability": {
            "fold_year": _signal(ranker, family="ranker").get("fold_year"),
            "notes": (stability.get("note") if isinstance(stability, dict) else None) or EVALUATION_WORDING,
            "ranker": _signal(ranker, family="ranker"),
            "regression": _signal(regression, family="regression"),
        },
        "economics": _economics_ui(economics, experiment_id),
        "prospective": map_prospective_ui(prospective),
        "limitations": list(REQUIRED_LIMITATIONS),
    }
    assert FORBIDDEN_OVERVIEW_KEYS.isdisjoint(payload.keys())
    return payload
