"""Pure industrial fundamental profile builder. Missing stays UNKNOWN — never 0."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.modules.fundamentals.domain.types import (
    FactRef,
    NormalizationStatus,
    PeriodType,
    ReportRef,
)
from app.modules.intelligence.fundamentals.constants import (
    ACCRUAL_PROXY_SEMANTICS,
    DEBT_SEMANTICS,
    DERIVED_CODES,
    FACT_CODES,
    LIABILITIES_PROXY_SEMANTICS,
    LIMITATION_CURRENT_LINES,
    LIMITATION_DEBT_PROXY,
    LIMITATION_LIABILITIES_PROXY,
    READY_REQUIRED_FACTS,
    RECENT_REPORT_MAX_AGE_DAYS,
    STATUS_PARTIAL,
    STATUS_READY,
)


@dataclass(frozen=True, slots=True)
class PriorPeriodFacts:
    """Comparable prior-period facts for YoY / trend (same period_type when possible)."""

    report: ReportRef
    facts: Mapping[str, float]


def normalized_fact_map(
    facts: Sequence[FactRef],
) -> tuple[dict[str, FactRef], list[str]]:
    """Deduplicate NORMALIZED facts; conflicting codes are omitted (not averaged)."""
    buckets: dict[str, list[FactRef]] = {}
    for fact in facts:
        if fact.normalization_status is not NormalizationStatus.NORMALIZED:
            continue
        if fact.value is None:
            continue
        buckets.setdefault(fact.metric_code, []).append(fact)

    out: dict[str, FactRef] = {}
    conflicts: list[str] = []
    for code, items in sorted(buckets.items()):
        signatures = {
            (float(item.value), item.currency or "", item.unit_scale or "") for item in items
        }
        if len(signatures) != 1:
            conflicts.append(code)
            continue
        out[code] = sorted(
            items, key=lambda f: (f.source_metric_name or "", f.report_id or 0)
        )[0]
    return out, conflicts


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None:
        return None
    if den == 0.0:
        return None
    return float(num) / float(den)


def _yoy(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None:
        return None
    if prior == 0.0:
        return None
    return (float(current) - float(prior)) / abs(float(prior))


def select_comparable_prior(
    reports: Sequence[ReportRef],
    latest: ReportRef,
) -> ReportRef | None:
    """Prefer same period_type with earlier period_end; else nearest earlier period_end."""
    earlier = [r for r in reports if r.period_end < latest.period_end]
    if not earlier:
        return None
    same_type = [r for r in earlier if r.period_type == latest.period_type]
    pool = same_type or earlier
    # Prefer FY when latest is FY
    if latest.period_type is PeriodType.FY:
        fy = [r for r in pool if r.period_type is PeriodType.FY]
        if fy:
            pool = fy
    return max(pool, key=lambda r: (r.period_end, r.known_at, r.report_version))


def build_industrial_profile(
    *,
    as_of: date,
    latest: ReportRef,
    facts: Sequence[FactRef],
    visible_reports: Sequence[ReportRef],
    prior: PriorPeriodFacts | None = None,
) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...], str]:
    """Return (metrics, missing_metrics, limitations, status)."""
    by_code, conflicts = normalized_fact_map(facts)
    values = {code: float(fact.value) for code, fact in by_code.items() if fact.value is not None}

    facts_payload: dict[str, Any] = {}
    for code in FACT_CODES:
        fact = by_code.get(code)
        if fact is None:
            continue
        facts_payload[code] = {
            "value": float(fact.value) if fact.value is not None else None,
            "currency": fact.currency,
            "unit_scale": fact.unit_scale,
            "source_metric_name": fact.source_metric_name,
            "report_id": fact.report_id,
        }

    revenue = values.get("REVENUE")
    operating = values.get("OPERATING_INCOME")
    net_income = values.get("NET_INCOME")
    assets = values.get("TOTAL_ASSETS")
    equity = values.get("TOTAL_EQUITY")
    debt = values.get("TOTAL_DEBT")
    cash = values.get("CASH_AND_EQUIVALENTS")
    ocf = values.get("OPERATING_CASH_FLOW")
    current_assets = values.get("CURRENT_ASSETS")
    current_liab = values.get("CURRENT_LIABILITIES")

    derived: dict[str, float] = {}
    missing: list[str] = []

    for code in FACT_CODES:
        if code not in values:
            missing.append(code)

    def put(name: str, value: float | None) -> None:
        if value is None:
            missing.append(name)
        else:
            derived[name] = float(value)

    put("net_margin", _ratio(net_income, revenue))
    put("operating_margin", _ratio(operating, revenue))
    put("roa", _ratio(net_income, assets))
    put("roe", _ratio(net_income, equity))
    put("leverage_assets_to_equity", _ratio(assets, equity))
    put("equity_to_assets", _ratio(equity, assets))
    put("cash_to_assets", _ratio(cash, assets))
    put("debt_to_equity", _ratio(debt, equity))
    put("debt_to_assets", _ratio(debt, assets))

    liabilities_proxy: float | None = None
    if assets is not None and equity is not None:
        liabilities_proxy = float(assets) - float(equity)
        derived["total_liabilities_proxy"] = liabilities_proxy
    else:
        missing.append("total_liabilities_proxy")

    put("current_ratio", _ratio(current_assets, current_liab))
    put("asset_turnover", _ratio(revenue, assets))

    accrual: float | None = None
    if net_income is not None and ocf is not None and assets not in (None, 0.0):
        accrual = (float(net_income) - float(ocf)) / float(assets)
        derived["accrual_proxy"] = accrual
    else:
        missing.append("accrual_proxy")

    prior_values = dict(prior.facts) if prior is not None else {}
    put("revenue_yoy", _yoy(revenue, prior_values.get("REVENUE")))
    put("net_income_yoy", _yoy(net_income, prior_values.get("NET_INCOME")))

    prior_net_margin = _ratio(prior_values.get("NET_INCOME"), prior_values.get("REVENUE"))
    cur_net_margin = derived.get("net_margin")
    if cur_net_margin is not None and prior_net_margin is not None:
        derived["net_margin_delta"] = cur_net_margin - prior_net_margin
    else:
        missing.append("net_margin_delta")

    prior_roe = _ratio(prior_values.get("NET_INCOME"), prior_values.get("TOTAL_EQUITY"))
    cur_roe = derived.get("roe")
    if cur_roe is not None and prior_roe is not None:
        derived["roe_delta"] = cur_roe - prior_roe
    else:
        missing.append("roe_delta")

    # Deduplicate missing while preserving order
    seen: set[str] = set()
    missing_ordered: list[str] = []
    for item in missing:
        if item in seen:
            continue
        seen.add(item)
        missing_ordered.append(item)

    report_age_days = (as_of - latest.period_end).days
    days_since_known = (as_of - latest.known_at).days
    freshness = {
        "days_since_known_at": float(days_since_known),
        "report_age_days": float(report_age_days),
        "has_recent_report": report_age_days <= RECENT_REPORT_MAX_AGE_DAYS,
        "period_type": str(latest.period_type),
        "reporting_standard": str(latest.reporting_standard),
    }

    fy_years = sorted(
        {
            r.period_end.year
            for r in visible_reports
            if r.period_type is PeriodType.FY
        }
    )
    history = {
        "visible_reports": len(visible_reports),
        "comparable_fy_years": len(fy_years),
        "fy_years": fy_years,
        "prior_period_end": prior.report.period_end.isoformat() if prior else None,
        "prior_period_type": str(prior.report.period_type) if prior else None,
    }

    flags = _deterioration_flags(
        derived=derived,
        values=values,
        liabilities_proxy=liabilities_proxy,
    )

    limitations: list[str] = [
        LIMITATION_DEBT_PROXY,
        LIMITATION_LIABILITIES_PROXY,
    ]
    if "CURRENT_ASSETS" in missing_ordered or "CURRENT_LIABILITIES" in missing_ordered:
        limitations.append(LIMITATION_CURRENT_LINES)
    if conflicts:
        limitations.append(f"CONFLICTING_NORMALIZED_FACTS:{','.join(conflicts)}")
    if prior is None:
        limitations.append("NO_COMPARABLE_PRIOR_PERIOD_FOR_YOY")

    present_required = READY_REQUIRED_FACTS.issubset(values.keys())
    status = STATUS_READY if present_required and not conflicts else STATUS_PARTIAL

    metrics: dict[str, Any] = {
        "facts": facts_payload,
        "derived": derived,
        "freshness": freshness,
        "history": history,
        "flags": {"deterioration": flags},
        "semantics": {
            "debt": DEBT_SEMANTICS,
            "total_liabilities_proxy": LIABILITIES_PROXY_SEMANTICS,
            "accrual_proxy": ACCRUAL_PROXY_SEMANTICS,
        },
        "conflicting_normalized_metrics": conflicts,
    }
    # Ensure every DERIVED_CODES entry is either in derived or missing
    for code in DERIVED_CODES:
        if code not in derived and code not in missing_ordered:
            missing_ordered.append(code)

    return metrics, tuple(missing_ordered), tuple(limitations), status


def _deterioration_flags(
    *,
    derived: Mapping[str, float],
    values: Mapping[str, float],
    liabilities_proxy: float | None,
) -> list[str]:
    flags: list[str] = []
    revenue_yoy = derived.get("revenue_yoy")
    if revenue_yoy is not None and revenue_yoy < 0:
        flags.append("REVENUE_YOY_NEGATIVE")
    ni_yoy = derived.get("net_income_yoy")
    if ni_yoy is not None and ni_yoy < 0:
        flags.append("NET_INCOME_YOY_NEGATIVE")
    margin_delta = derived.get("net_margin_delta")
    if margin_delta is not None and margin_delta < 0:
        flags.append("NET_MARGIN_DETERIORATING")
    roe_delta = derived.get("roe_delta")
    if roe_delta is not None and roe_delta < 0:
        flags.append("ROE_DETERIORATING")
    equity = values.get("TOTAL_EQUITY")
    if equity is not None and equity < 0:
        flags.append("NEGATIVE_EQUITY")
    ni = values.get("NET_INCOME")
    ocf = values.get("OPERATING_CASH_FLOW")
    if ni is not None and ocf is not None and ni > 0 and ocf < 0:
        flags.append("POSITIVE_NI_NEGATIVE_OCF")
    leverage = derived.get("leverage_assets_to_equity")
    if leverage is not None and leverage > 5.0:
        flags.append("HIGH_LEVERAGE_ASSETS_TO_EQUITY")
    if liabilities_proxy is not None and liabilities_proxy < 0:
        flags.append("NEGATIVE_LIABILITIES_PROXY")
    return flags


def facts_used_payload(
    by_code: Mapping[str, FactRef],
    *,
    known_at: date,
    period_end: date,
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for code in sorted(by_code):
        fact = by_code[code]
        rows.append(
            {
                "metric_code": code,
                "value": float(fact.value) if fact.value is not None else None,
                "currency": fact.currency,
                "unit_scale": fact.unit_scale,
                "source_metric_name": fact.source_metric_name,
                "report_id": fact.report_id,
                "known_at": known_at.isoformat(),
                "period_end": period_end.isoformat(),
                "normalization_status": str(fact.normalization_status),
            }
        )
    return tuple(rows)
