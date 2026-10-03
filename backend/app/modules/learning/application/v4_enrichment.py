"""Bounded PIT fundamental/event enrichment for Dataset V4 (in-memory timelines).

Preloads mappings, reports, facts and events in a handful of SQL queries, then
resolves each sample from sorted timelines. Never N+1 per sample.

Missing stays missing. Raw monetary size is not placed in X: same-report ratios
only, when currency/unit_scale match and the denominator is a genuine non-zero.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.modules.fundamentals.application.dividend_provider import (
    dividend_coverage_v2,
    get_dividend_provider,
)
from app.modules.fundamentals.application.features_event import build_event_features
from app.modules.fundamentals.application.features_fundamental import (
    LookaheadError,
    build_fundamental_features,
)
from app.modules.fundamentals.application.pit import (
    BASIS_AMBIGUOUS,
    BASIS_CURRENT_ONLY,
    BASIS_DATED_WINDOW,
    BASIS_UNMAPPED,
    corporate_event_ref,
    dividend_ref,
    fact_ref,
    report_ref,
)
from app.modules.fundamentals.domain import pit_rules
from app.modules.fundamentals.domain.types import (
    CorporateEventRef,
    DividendEventRef,
    FactRef,
    FundamentalsState,
    MappingStatus,
    NormalizationStatus,
    ReportRef,
    ReportStatus,
)
from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import SUPPORT_BANK
from app.modules.fundamentals.infrastructure.models import (
    CorporateEvent,
    DividendEvent,
    FinancialFact,
    FinancialReport,
    Issuer,
    SecurityIssuerMapping,
    fundamentals_schema_ready,
)
from app.modules.learning.dataset_config import (
    V4_EVENT_FEATURE_NAMES,
    V4_FUNDAMENTAL_FEATURE_NAMES,
)

FNS_BANK_FI_UNSUPPORTED = SUPPORT_BANK
STATUS_UNSUPPORTED_BANK_FI = "UNSUPPORTED_BANK_FI"
REASON_BANK_FI_UNSUPPORTED = "BANK_FI_SEMANTICS_UNSUPPORTED"
REASON_CONFLICTING_FACTS = "CONFLICTING_NORMALIZED_FACTS"
REASON_AMBIGUOUS_ISSUER = "AMBIGUOUS_ISSUER_MAPPING"

_EVENT_KEY_MAP = {
    "days_since_last_split": "event_days_since_last_split",
    "split_events_365d": "event_split_events_365d",
    "days_since_last_dividend_disclosure": "event_days_since_last_dividend_disclosure",
    "last_disclosed_dividend_per_share": "event_last_disclosed_dividend_per_share",
    "has_known_upcoming_dividend": "event_has_known_upcoming_dividend",
    "days_to_next_dividend_record_date": "event_days_to_next_dividend_record_date",
}

_RATIO_SPECS: tuple[tuple[str, str, str], ...] = (
    ("fund_net_margin", "NET_INCOME", "REVENUE"),
    ("fund_operating_margin", "OPERATING_INCOME", "REVENUE"),
    ("fund_debt_to_equity", "TOTAL_DEBT", "TOTAL_EQUITY"),
    ("fund_cash_to_assets", "CASH_AND_EQUIVALENTS", "TOTAL_ASSETS"),
    ("fund_equity_to_assets", "TOTAL_EQUITY", "TOTAL_ASSETS"),
    ("fund_operating_cash_flow_to_revenue", "OPERATING_CASH_FLOW", "REVENUE"),
)


@dataclass(slots=True)
class V4SampleEnrichment:
    features: dict[str, float | None]
    lineage: dict[str, Any]
    pit_violations: list[str] = field(default_factory=list)

    @property
    def has_fundamental_feature(self) -> bool:
        return any(self.features.get(name) is not None for name in V4_FUNDAMENTAL_FEATURE_NAMES)

    @property
    def has_event_feature(self) -> bool:
        return any(self.features.get(name) is not None for name in V4_EVENT_FEATURE_NAMES)


@dataclass
class V4EnrichmentIndex:
    """In-memory PIT timelines. ``query_count`` is the preload SQL bound, not per sample."""

    query_count: int = 0
    schema_ready: bool = False
    mappings_by_instrument: dict[int, list[SecurityIssuerMapping]] = field(default_factory=dict)
    reports_by_issuer: dict[int, list[ReportRef]] = field(default_factory=dict)
    facts_by_report: dict[int, tuple[FactRef, ...]] = field(default_factory=dict)
    corp_by_instrument: dict[int, list[CorporateEventRef]] = field(default_factory=dict)
    div_by_instrument: dict[int, list[DividendEventRef]] = field(default_factory=dict)
    issuer_fns_support: dict[int, str | None] = field(default_factory=dict)
    preload_reason: str | None = None

    def empty_features(self) -> dict[str, float | None]:
        return {name: None for name in (*V4_FUNDAMENTAL_FEATURE_NAMES, *V4_EVENT_FEATURE_NAMES)}


class _QueryCounter:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, *_args: Any, **_kwargs: Any) -> None:
        self.count += 1


def load_v4_enrichment_index(
    session: Session,
    *,
    instrument_ids: list[int],
) -> V4EnrichmentIndex:
    """Batch-load V4 evidence. Query count is O(1) vs instruments/samples."""
    index = V4EnrichmentIndex()
    if not instrument_ids:
        index.preload_reason = "empty_instrument_set"
        return index
    if not fundamentals_schema_ready(session):
        index.preload_reason = "fundamentals_schema_missing"
        return index
    index.schema_ready = True

    bind = session.get_bind()
    engine = bind.engine if hasattr(bind, "engine") else bind
    counter = _QueryCounter()
    if isinstance(engine, Engine):
        event.listen(engine, "before_cursor_execute", counter)
    try:
        inst_ids = list(dict.fromkeys(int(i) for i in instrument_ids))
        mappings = list(
            session.scalars(
                select(SecurityIssuerMapping).where(
                    SecurityIssuerMapping.instrument_id.in_(inst_ids),
                )
            ).all()
        )
        by_inst: dict[int, list[SecurityIssuerMapping]] = defaultdict(list)
        issuer_ids: set[int] = set()
        for row in mappings:
            by_inst[int(row.instrument_id)].append(row)
            if row.issuer_id is not None and row.mapping_status == MappingStatus.MAPPED.value:
                issuer_ids.add(int(row.issuer_id))
        index.mappings_by_instrument = dict(by_inst)

        reports: list[FinancialReport] = []
        if issuer_ids:
            reports = list(
                session.scalars(
                    select(FinancialReport).where(
                        FinancialReport.issuer_id.in_(sorted(issuer_ids)),
                        FinancialReport.status != ReportStatus.REJECTED.value,
                    )
                ).all()
            )
        report_ids = [int(r.id) for r in reports]
        facts: list[FinancialFact] = []
        if report_ids:
            facts = list(
                session.scalars(select(FinancialFact).where(FinancialFact.report_id.in_(report_ids))).all()
            )
        by_issuer_reports: dict[int, list[ReportRef]] = defaultdict(list)
        for row in reports:
            by_issuer_reports[int(row.issuer_id)].append(report_ref(row))
        index.reports_by_issuer = dict(by_issuer_reports)
        by_report_facts: dict[int, list[FactRef]] = defaultdict(list)
        for row in facts:
            by_report_facts[int(row.report_id)].append(fact_ref(row))
        index.facts_by_report = {rid: tuple(vals) for rid, vals in by_report_facts.items()}

        corp_rows = list(
            session.scalars(
                select(CorporateEvent).where(CorporateEvent.instrument_id.in_(inst_ids))
            ).all()
        )
        div_rows = list(
            session.scalars(
                select(DividendEvent).where(DividendEvent.instrument_id.in_(inst_ids))
            ).all()
        )
        corp_map: dict[int, list[CorporateEventRef]] = defaultdict(list)
        for row in corp_rows:
            ref = corporate_event_ref(row)
            if ref is not None and row.instrument_id is not None:
                corp_map[int(row.instrument_id)].append(ref)
        div_map: dict[int, list[DividendEventRef]] = defaultdict(list)
        for row in div_rows:
            if row.instrument_id is not None:
                div_map[int(row.instrument_id)].append(dividend_ref(row))
        index.corp_by_instrument = dict(corp_map)
        index.div_by_instrument = dict(div_map)
        if issuer_ids:
            issuer_rows = list(
                session.scalars(select(Issuer).where(Issuer.id.in_(sorted(issuer_ids)))).all()
            )
            index.issuer_fns_support = {
                int(row.id): _fns_support_status(row.metadata_) for row in issuer_rows
            }
    finally:
        if isinstance(engine, Engine):
            event.remove(engine, "before_cursor_execute", counter)
    index.query_count = counter.count
    return index


def _fns_support_status(metadata: Any) -> str | None:
    if not isinstance(metadata, dict):
        return None
    fns = metadata.get("fns")
    if not isinstance(fns, dict):
        return None
    status = fns.get("support_status")
    if status is None or status == "":
        return None
    return str(status)


def _is_bank_fi_unsupported(support_status: str | None) -> bool:
    return support_status == FNS_BANK_FI_UNSUPPORTED


def _mapping_sort_key(row: Any) -> tuple[int, str, int]:
    issuer = int(row.issuer_id) if getattr(row, "issuer_id", None) is not None else 0
    valid_from = getattr(row, "valid_from", None)
    vf = valid_from.isoformat() if valid_from is not None else ""
    row_id = int(getattr(row, "id", 0) or 0)
    return (issuer, vf, row_id)


def _resolve_issuer(
    mappings: list[SecurityIssuerMapping], as_of: date
) -> tuple[int | None, str]:
    dated = [
        row
        for row in mappings
        if row.mapping_status == MappingStatus.MAPPED.value
        and row.issuer_id is not None
        and row.valid_from is not None
        and row.valid_from <= as_of
        and (row.valid_to is None or as_of < row.valid_to)
    ]
    if dated:
        issuers = {int(row.issuer_id) for row in dated}
        if len(issuers) > 1:
            return None, BASIS_AMBIGUOUS
        return int(sorted(dated, key=_mapping_sort_key)[0].issuer_id), BASIS_DATED_WINDOW
    current = [
        row
        for row in mappings
        if row.mapping_status == MappingStatus.MAPPED.value
        and row.issuer_id is not None
        and row.valid_from is None
        and row.valid_to is None
    ]
    if current:
        issuers = {int(row.issuer_id) for row in current}
        if len(issuers) > 1:
            return None, BASIS_AMBIGUOUS
        return int(sorted(current, key=_mapping_sort_key)[0].issuer_id), BASIS_CURRENT_ONLY
    return None, BASIS_UNMAPPED


def _compatible(a: FactRef, b: FactRef) -> bool:
    return (a.currency or "") == (b.currency or "") and (a.unit_scale or "") == (b.unit_scale or "")


def _fact_signature(fact: FactRef) -> tuple[float, str, str]:
    return (float(fact.value), fact.currency or "", fact.unit_scale or "")


def _normalized_facts(facts: tuple[FactRef, ...]) -> tuple[dict[str, FactRef], list[str]]:
    by_code: dict[str, list[FactRef]] = defaultdict(list)
    for fact in facts:
        if fact.normalization_status is not NormalizationStatus.NORMALIZED:
            continue
        if fact.value is None:
            continue
        by_code[fact.metric_code].append(fact)
    out: dict[str, FactRef] = {}
    conflicts: list[str] = []
    for code in sorted(by_code):
        candidates = by_code[code]
        signatures = {_fact_signature(item) for item in candidates}
        if len(signatures) == 1:
            out[code] = sorted(
                candidates,
                key=lambda f: (f.source_metric_name or "", f.report_id or 0),
            )[0]
        else:
            conflicts.append(code)
    return out, conflicts


def _ratio(num: FactRef | None, den: FactRef | None) -> float | None:
    if num is None or den is None:
        return None
    if not _compatible(num, den):
        return None
    if den.value is None or float(den.value) == 0.0:
        return None
    if num.value is None:
        return None
    return float(num.value) / float(den.value)


def resolve_v4_sample(
    index: V4EnrichmentIndex,
    *,
    instrument_id: int,
    as_of: date,
) -> V4SampleEnrichment:
    features = index.empty_features()
    violations: list[str] = []
    fund_lineage: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "issuer_id": None,
        "issuer_resolution_basis": BASIS_UNMAPPED,
        "missing_reason": None,
    }
    event_lineage: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "visible_event_count": 0,
        "visible_dividend_count": 0,
        "missing_reason": None,
    }

    if not index.schema_ready:
        fund_lineage["missing_reason"] = index.preload_reason or "schema_not_ready"
        event_lineage["missing_reason"] = index.preload_reason or "schema_not_ready"
        return V4SampleEnrichment(
            features=features,
            lineage={"fundamentals": fund_lineage, "events": event_lineage},
            pit_violations=violations,
        )

    issuer_id, basis = _resolve_issuer(index.mappings_by_instrument.get(instrument_id, []), as_of)
    fund_lineage["issuer_resolution_basis"] = basis
    fund_lineage["issuer_id"] = issuer_id
    if basis == BASIS_AMBIGUOUS:
        fund_lineage["status"] = BASIS_AMBIGUOUS
        fund_lineage["missing_reason"] = REASON_AMBIGUOUS_ISSUER
    elif issuer_id is None:
        fund_lineage["status"] = "UNMAPPED"
        fund_lineage["missing_reason"] = "UNMAPPED"
    elif _is_bank_fi_unsupported(index.issuer_fns_support.get(issuer_id)):
        fund_lineage["status"] = STATUS_UNSUPPORTED_BANK_FI
        fund_lineage["missing_reason"] = REASON_BANK_FI_UNSUPPORTED
        fund_lineage["fns_support_status"] = index.issuer_fns_support.get(issuer_id)
    else:
        visible_reports = pit_rules.visible_reports(
            index.reports_by_issuer.get(issuer_id, ()), as_of
        )
        latest = pit_rules.latest_report(visible_reports, as_of)
        facts = index.facts_by_report.get(int(latest.report_id), ()) if latest and latest.report_id else ()
        state = FundamentalsState(
            as_of=as_of,
            issuer_id=issuer_id,
            latest_report=latest,
            facts=facts,
            visible_reports=len(visible_reports),
        )
        try:
            row = build_fundamental_features(state, instrument_id=instrument_id)
        except LookaheadError as exc:
            violations.append(str(exc))
            row = None
        if row is None:
            fund_lineage["status"] = "NO_VISIBLE_REPORT"
            fund_lineage["missing_reason"] = "NO_VISIBLE_REPORT"
        else:
            if row.feature_known_at > as_of:
                violations.append(
                    f"fundamental feature_known_at {row.feature_known_at} > {as_of}"
                )
            features["fund_days_since_latest_report"] = row.features.get("days_since_latest_report")
            features["fund_report_age_days"] = row.features.get("report_age_days")
            features["fund_has_recent_report"] = row.features.get("has_recent_report")
            by_code, conflicts = _normalized_facts(facts)
            for name, num_code, den_code in _RATIO_SPECS:
                if num_code in conflicts or den_code in conflicts:
                    features[name] = None
                    continue
                features[name] = _ratio(by_code.get(num_code), by_code.get(den_code))
            fund_lineage.update(
                {
                    "status": "AVAILABLE",
                    "feature_known_at": row.feature_known_at.isoformat(),
                    "report_id": latest.report_id if latest else None,
                    "report_period_end": latest.period_end.isoformat() if latest else None,
                    "report_known_at": latest.known_at.isoformat() if latest else None,
                    "report_source": latest.source if latest else None,
                    "reporting_standard": (
                        latest.reporting_standard.value if latest else None
                    ),
                    "missing_reason": REASON_CONFLICTING_FACTS if conflicts else None,
                    "conflicting_normalized_metrics": conflicts or None,
                }
            )

    corp = index.corp_by_instrument.get(instrument_id, ())
    divs = index.div_by_instrument.get(instrument_id, ())
    visible_corp = pit_rules.visible_corporate_events(corp, as_of)
    visible_div = pit_rules.visible_dividend_events(divs, as_of)
    event_lineage["visible_event_count"] = len(visible_corp)
    event_lineage["visible_dividend_count"] = len(visible_div)
    try:
        event_row = build_event_features(
            as_of,
            instrument_id=instrument_id,
            corporate_events=corp,
            dividend_events=divs,
        )
    except LookaheadError as exc:
        violations.append(str(exc))
        event_row = None
    if event_row is None:
        event_lineage["status"] = "NO_VISIBLE_EVENTS"
        event_lineage["missing_reason"] = (
            "NO_DIVIDEND_COVERAGE" if not divs and not corp else "NOT_YET_VISIBLE"
        )
    else:
        if event_row.feature_known_at > as_of:
            violations.append(f"event feature_known_at {event_row.feature_known_at} > {as_of}")
        for src, dest in _EVENT_KEY_MAP.items():
            if src in event_row.features:
                features[dest] = event_row.features[src]
        event_lineage.update(
            {
                "status": "AVAILABLE",
                "feature_known_at": event_row.feature_known_at.isoformat(),
                "missing_reason": None,
            }
        )
        if not visible_div:
            # Honest unknown: do not emit upcoming-dividend=0 from an empty store.
            features["event_has_known_upcoming_dividend"] = None
            features["event_days_to_next_dividend_record_date"] = None
            features["event_days_since_last_dividend_disclosure"] = None
            features["event_last_disclosed_dividend_per_share"] = None
            event_lineage["dividend_missing_reason"] = "NO_DIVIDEND_COVERAGE"

    return V4SampleEnrichment(
        features=features,
        lineage={"fundamentals": fund_lineage, "events": event_lineage},
        pit_violations=violations,
    )


def v4_return_truth(session: Session) -> dict[str, Any]:
    """Provider-aware TR diagnostic. Primary labels stay mechanical price-return."""
    coverage = dividend_coverage_v2(session)
    provider = get_dividend_provider().readiness()
    events_stored = int(coverage.get("dividend_events_stored") or 0)
    accepted = bool(provider.get("accepted"))
    universe_wide = bool(provider.get("universe_wide"))
    store_quality = str(coverage.get("quality") or "NOT_READY")
    reasons = list(coverage.get("reasons") or [])
    reasons.extend(str(item) for item in (provider.get("reasons") or []) if item not in reasons)

    if events_stored <= 0:
        enrichment = "NOT_READY"
        reasons.append("empty_dividend_store_is_not_zero_cashflow")
    elif not accepted:
        enrichment = "NOT_READY"
        reasons.append("dividend_provider_not_accepted")
    elif not universe_wide:
        enrichment = "PARTIAL"
        reasons.append("dividend_provider_not_universe_wide")
    elif str(provider.get("status") or "").upper() == "READY" and store_quality == "READY":
        enrichment = "READY"
        reasons.append("provider_universe_wide_and_store_ready")
    else:
        enrichment = "PARTIAL"
        reasons.append("accepted_universe_wide_provider_not_fully_ready")

    notes = [
        "Empty dividend_events is NOT_READY, not zero cashflow.",
        "V4 primary labels remain mechanical price-return (same as V3).",
        "Bounded accepted IR coverage cannot become universe-wide Total Return READY.",
        *(coverage.get("notes") or []),
        *(provider.get("notes") or []),
    ]
    return {
        "primary_label_family": "MECHANICAL_PRICE_RETURN",
        "dividend_adjusted": False,
        "total_return": False,
        "total_return_enrichment_status": enrichment,
        "dividend_coverage_quality": store_quality,
        "verdict": enrichment,
        "coverage_quality": store_quality,
        "provider": provider.get("provider") or provider.get("status"),
        "provider_accepted": accepted,
        "provider_universe_wide": universe_wide,
        "provider_status": provider.get("status"),
        "dividend_events_stored": events_stored,
        "instruments_with_dividend_events": coverage.get("instruments_with_dividend_events", 0),
        "reasons": reasons,
        "notes": notes,
    }


def empty_v4_enrichment(*, reason: str) -> V4SampleEnrichment:
    features = {name: None for name in (*V4_FUNDAMENTAL_FEATURE_NAMES, *V4_EVENT_FEATURE_NAMES)}
    return V4SampleEnrichment(
        features=features,
        lineage={
            "fundamentals": {
                "status": "UNAVAILABLE",
                "issuer_resolution_basis": BASIS_UNMAPPED,
                "missing_reason": reason,
            },
            "events": {"status": "UNAVAILABLE", "missing_reason": reason},
        },
    )
