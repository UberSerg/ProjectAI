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

# CURRENT_ONLY share = CURRENT_ONLY / (DATED_WINDOW + CURRENT_ONLY + UNMAPPED + AMBIGUOUS).
# Missing any of the four counts → null (do not fabricate). Explicit 0 is kept.
ISSUER_BASIS_DENOMINATOR_KEYS: tuple[str, ...] = (
    "DATED_WINDOW",
    "CURRENT_ONLY",
    "UNMAPPED",
    "AMBIGUOUS",
)
CURRENT_ONLY_SHARE_DENOMINATOR = "DATED_WINDOW+CURRENT_ONLY+UNMAPPED+AMBIGUOUS"
_RANKER_FORBIDDEN_UI = frozenset({"rmse", "mae"})
_V4_COVERAGE_KEYS = (
    "fundamental_sample_coverage_pct",
    "event_sample_coverage_pct",
    "issuer_resolution_basis_counts",
    "bank_fi_unsupported_samples",
)


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


def _first_float(*values: Any) -> float | None:
    """Keep explicit 0.0; never coerce missing / NaN to 0."""
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, int):
            return float(value)
        if isinstance(value, float) and value == value and value not in (float("inf"), float("-inf")):
            return float(value)
    return None


def _status_token(value: Any) -> str:
    return str(value or "").strip().upper()


def _is_insufficient_status(value: Any) -> bool:
    return _status_token(value) == "INSUFFICIENT"


def current_only_share_from_counts(counts: Any) -> float | None:
    """Share of CURRENT_ONLY among DATED_WINDOW+CURRENT_ONLY+UNMAPPED+AMBIGUOUS."""
    if not isinstance(counts, dict):
        return None
    parts: list[int] = []
    for key in ISSUER_BASIS_DENOMINATOR_KEYS:
        if key not in counts:
            return None
        n = _first_int(counts.get(key))
        if n is None:
            return None
        parts.append(n)
    denom = sum(parts)
    if denom == 0:
        return None
    current_only = _first_int(counts.get("CURRENT_ONLY"))
    if current_only is None:
        return None
    return current_only / denom


def _looks_like_v4_coverage(payload: Any) -> bool:
    return isinstance(payload, dict) and any(key in payload for key in _V4_COVERAGE_KEYS)


def extract_v4_coverage_blocks(dataset: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Normalize path A (run.coverage_summary on proof) and path B (compare artifact).

    Path A: ``v4.coverage_summary['v4']`` + ``v4.coverage_summary['return_truth']``.
    Path B: ``dataset_compare['v4']['v4']`` + ``dataset_compare['v4']['return_truth']``.
    Also accept coverage_summary (or v4 side) that already *is* the v4 key block.
    """
    v4_side = dataset.get("v4") if isinstance(dataset.get("v4"), dict) else {}
    coverage_summary = None
    if isinstance(v4_side.get("coverage_summary"), dict):
        coverage_summary = v4_side["coverage_summary"]
    elif isinstance(dataset.get("coverage_summary"), dict):
        coverage_summary = dataset["coverage_summary"]

    v4_cov: dict[str, Any] | None = None
    return_truth: dict[str, Any] | None = None
    if isinstance(coverage_summary, dict):
        inner = coverage_summary.get("v4")
        if isinstance(inner, dict):
            v4_cov = inner
        elif _looks_like_v4_coverage(coverage_summary):
            v4_cov = coverage_summary
        if isinstance(coverage_summary.get("return_truth"), dict):
            return_truth = coverage_summary["return_truth"]

    nested = v4_side.get("v4") if isinstance(v4_side.get("v4"), dict) else None
    if v4_cov is None and nested is not None:
        if _looks_like_v4_coverage(nested):
            v4_cov = nested
        elif isinstance(nested.get("v4"), dict):
            v4_cov = nested["v4"]
            if return_truth is None and isinstance(nested.get("return_truth"), dict):
                return_truth = nested["return_truth"]

    if v4_cov is None and _looks_like_v4_coverage(v4_side):
        v4_cov = v4_side

    if return_truth is None and isinstance(v4_side.get("return_truth"), dict):
        return_truth = v4_side["return_truth"]

    return (v4_cov or {}, return_truth)


def map_v4_coverage_ui(dataset: dict[str, Any]) -> dict[str, Any]:
    v4_cov, return_truth = extract_v4_coverage_blocks(dataset)
    counts = (
        v4_cov.get("issuer_resolution_basis_counts")
        if isinstance(v4_cov.get("issuer_resolution_basis_counts"), dict)
        else None
    )
    fund_pct = _first_float(v4_cov.get("fundamental_sample_coverage_pct"))
    event_pct = _first_float(v4_cov.get("event_sample_coverage_pct"))
    bank_fi = _first_int(v4_cov.get("bank_fi_unsupported_samples"))
    share = current_only_share_from_counts(counts)
    total_return_status = "incomplete"
    if isinstance(return_truth, dict):
        enrichment = return_truth.get("total_return_enrichment_status")
        if return_truth.get("total_return") is True and str(enrichment or "").upper() == "READY":
            total_return_status = "complete"
        elif enrichment:
            total_return_status = "incomplete"
    v4_coverage = {
        "fundamental_sample_coverage_pct": fund_pct,
        "event_sample_coverage_pct": event_pct,
        "issuer_resolution_basis_counts": counts,
        "bank_fi_unsupported_samples": bank_fi,
        "current_only_share": share,
        "current_only_share_denominator": CURRENT_ONLY_SHARE_DENOMINATOR,
    }
    return {
        "v4_coverage": v4_coverage,
        "return_truth": return_truth,
        "fund_coverage": fund_pct,
        "event_coverage": event_pct,
        "current_only_share": share,
        "bank_fi_unsupported": bank_fi,
        "total_return_status": total_return_status,
    }


def _signal(part: dict[str, Any], *, family: str) -> dict[str, Any]:
    if _pending(part):
        return {"family": family, "available": False, "notes": "CHRONOLOGICAL OOS RESEARCH ещё не посчитан."}
    if _is_insufficient_status(part.get("status")):
        return {
            "family": family,
            "available": False,
            "rank_ic": None,
            "spread": None,
            "n": None,
            "fold_year": [],
            "consistent": None,
            "notes": part.get("reason") or part.get("note") or "INSUFFICIENT: выборки недостаточно для OOS-метрик.",
        }
    metrics = part.get("metrics") if isinstance(part.get("metrics"), dict) else None
    folds = part.get("folds") if isinstance(part.get("folds"), list) else []
    fold_year = []
    for fold in folds:
        m = fold.get("metrics") if isinstance(fold, dict) else None
        insufficient_fold = isinstance(fold, dict) and _is_insufficient_status(fold.get("status"))
        fold_year.append(
            {
                "fold": str(fold.get("fold_id")) if isinstance(fold, dict) else None,
                "year": None,
                "rank_ic": None if insufficient_fold else _ic(m if isinstance(m, dict) else None),
                "spread": None if insufficient_fold else _spread(m if isinstance(m, dict) else None),
                "n": None if insufficient_fold else _n(m if isinstance(m, dict) else None),
            }
        )
    ics = [row["rank_ic"] for row in fold_year if isinstance(row.get("rank_ic"), int | float)]
    consistent = None
    if len(ics) >= 2:
        consistent = (max(ics) - min(ics)) < 0.5
    return {
        "family": family,
        "available": True,
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


def _strip_ranker_error_metrics(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    for key in list(out):
        if str(key).lower() in _RANKER_FORBIDDEN_UI:
            out.pop(key, None)
    nested = out.get("metrics")
    if isinstance(nested, dict):
        cleaned = dict(nested)
        for key in list(cleaned):
            if str(key).lower() in _RANKER_FORBIDDEN_UI:
                cleaned.pop(key, None)
        out["metrics"] = cleaned
    return out


def _map_pdm_ui(pdm: dict[str, Any]) -> dict[str, Any]:
    horizons_raw = pdm.get("horizons") if isinstance(pdm.get("horizons"), list) else []
    horizons: list[dict[str, Any]] = []
    for row in horizons_raw:
        if not isinstance(row, dict):
            continue
        price = row.get("price_return") if isinstance(row.get("price_return"), dict) else {}
        align = row.get("direction_alignment") if isinstance(row.get("direction_alignment"), dict) else {}
        matured = _first_int(row.get("matured_count")) or 0
        status = price.get("status") or (
            "INSUFFICIENT_SAMPLE" if 0 < matured < 5 else ("OBSERVED" if matured >= 5 else "EMPTY")
        )
        horizons.append(
            {
                "horizon_sessions": row.get("horizon_sessions"),
                "matured_count": matured,
                "pending_count": _first_int(row.get("pending_count")) or 0,
                "unavailable_count": _first_int(row.get("unavailable_count")) or 0,
                "status": status,
                "price_return": price,
                "direction_alignment": align,
            }
        )
    links = (
        pdm.get("confirmed_operation_links")
        if isinstance(pdm.get("confirmed_operation_links"), dict)
        else {}
    )
    return {
        "captures_total": _first_int(pdm.get("captures_total")) or 0,
        "return_type": pdm.get("return_type") or "PRICE_RETURN",
        "horizons": horizons,
        "confirmed_operation_links": {
            "count": _first_int(links.get("count")) or 0,
            "role": links.get("role") or "METADATA_ONLY",
            "causality_claim": False,
            "linked_trade_means_recommendation_caused_trade": False,
            "note": links.get("note")
            or "Подтверждённая связь с PersonalOperation — только метаданные, не причинность.",
        },
    }


def _map_forward_ui(fwd: dict[str, Any]) -> dict[str, Any]:
    freshness = fwd.get("freshness") if isinstance(fwd.get("freshness"), dict) else {}
    ranking = _strip_ranker_error_metrics(fwd.get("ranking_score"))
    expected = fwd.get("expected_return") if isinstance(fwd.get("expected_return"), dict) else None
    latest_batch = fwd.get("latest_batch") if isinstance(fwd.get("latest_batch"), dict) else {}
    latest_eval = (
        fwd.get("latest_evaluated_batch")
        if isinstance(fwd.get("latest_evaluated_batch"), dict)
        else {}
    )
    return {
        "latest_batch": latest_batch,
        "latest_evaluated_batch": latest_eval,
        "freshness": {
            "matured_count": _first_int(freshness.get("matured_count")) or 0,
            "pending_count": _first_int(freshness.get("pending_count")) or 0,
            "pending_remains_pending": freshness.get("pending_remains_pending", True),
            "fabricated_immature_outcomes": False,
        },
        "expected_return": expected,
        "ranking_score": ranking,
    }


def map_prospective_ui(prospective: dict[str, Any]) -> dict[str, Any]:
    """Map PDM horizons[] and Forward freshness.matured_count. Never treat captures as OBSERVED."""
    notes = (
        "Проспективные наблюдения отделены от исторического OOS. "
        "Захваты (captures) не являются matured-доказательством. "
        "Связь с PersonalOperation не доказывает причинность. "
        "Нет комбинированной «точности Kraken»."
    )
    if _pending(prospective) and not isinstance(prospective.get("personal_decision_memory"), dict):
        return {
            "status": "EMPTY",
            "empty": True,
            "notes": "Проспективные наблюдения не загружены.",
            "personal_decision_memory": None,
            "forward_predictions": None,
        }
    pdm_raw = (
        prospective.get("personal_decision_memory")
        if isinstance(prospective.get("personal_decision_memory"), dict)
        else {}
    )
    fwd_raw = (
        prospective.get("forward_predictions")
        if isinstance(prospective.get("forward_predictions"), dict)
        else {}
    )
    pdm = _map_pdm_ui(pdm_raw)
    fwd = _map_forward_ui(fwd_raw)
    captures = int(pdm.get("captures_total") or 0)
    matured_pdm = sum(int(row.get("matured_count") or 0) for row in pdm["horizons"])
    fwd_matured = int((fwd.get("freshness") or {}).get("matured_count") or 0)
    latest_id = (fwd.get("latest_batch") or {}).get("batch_id")
    empty = captures == 0 and matured_pdm == 0 and fwd_matured == 0 and latest_id is None
    return {
        "status": "EMPTY" if empty else "SEPARATE_PROSPECTIVE",
        "empty": empty,
        "notes": notes,
        "personal_decision_memory": pdm,
        "forward_predictions": fwd,
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
            "notes": "Проспективный блок отделён от исторического OOS.",
            "personal_decision_memory": None,
            "forward_predictions": None,
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
    coverage_ui = map_v4_coverage_ui(dataset)
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
            "fund_coverage": coverage_ui["fund_coverage"],
            "event_coverage": coverage_ui["event_coverage"],
            "current_only_share": coverage_ui["current_only_share"],
            "bank_fi_unsupported": coverage_ui["bank_fi_unsupported"],
            "v4_coverage": coverage_ui["v4_coverage"],
            "return_truth": coverage_ui["return_truth"],
            "total_return_status": coverage_ui["total_return_status"],
            "date_from": identity.get("date_from"),
            "date_to": identity.get("date_to"),
            "partial": dataset.get("status") == "PENDING",
            "notes": (
                "CURRENT_ONLY share = CURRENT_ONLY / "
                f"({CURRENT_ONLY_SHARE_DENOMINATOR.replace('+', ' + ')})."
            ),
        },
        "historical_models": {
            "regression": _signal(regression, family="regression"),
            "ranker": _signal(ranker, family="ranker"),
        },
        "ablation": {
            "rows": _ablation_rows(ablation, paired),
            "partial": _pending(ablation) or _is_insufficient_status(ablation.get("status")),
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
