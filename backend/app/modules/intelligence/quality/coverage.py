"""Intelligence coverage summary across daily / intraday / fundamentals / events / macro / knowledge.

Statuses are READY | PARTIAL | NOT_READY | UNKNOWN — missing ≠ zero.
Does not mutate production Candidate / Shadow / Daily Decision pins.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.intelligence.isolation import production_isolation_report

COVERAGE_DOMAINS: tuple[str, ...] = (
    "daily",
    "intraday",
    "fundamentals",
    "events",
    "macro",
    "knowledge",
)

_STATUS_RANK = {
    "READY": 3,
    "PARTIAL": 2,
    "NOT_READY": 1,
    "UNKNOWN": 0,
}


@dataclass(frozen=True, slots=True)
class DomainCoverage:
    domain: str
    status: str
    row_count: int = 0
    detail: str | None = None
    last_known_at: date | datetime | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.domain not in COVERAGE_DOMAINS:
            raise ValueError(f"unsupported domain: {self.domain}")
        if self.status not in _STATUS_RANK:
            raise ValueError(f"unsupported status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        value = payload.get("last_known_at")
        if isinstance(value, date | datetime):
            payload["last_known_at"] = value.isoformat()
        payload["limitations"] = list(self.limitations)
        return payload


def overall_status(domains: list[DomainCoverage] | tuple[DomainCoverage, ...]) -> str:
    """Conservative aggregate: worst concrete readiness wins; all-UNKNOWN stays UNKNOWN."""
    if not domains:
        return "UNKNOWN"
    concrete = [d.status for d in domains if d.status != "UNKNOWN"]
    if not concrete:
        return "UNKNOWN"
    return min(concrete, key=lambda s: _STATUS_RANK[s])


def build_intelligence_coverage_summary(
    session: Session,
    *,
    instrument_id: int | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Measure store coverage for Intelligence Stack V1 domains.

    Safe when ``intelligence`` schema is absent (domains → NOT_READY / UNKNOWN).
    Ordinary automated tests should pass a stub session or skip live DB.
    """
    domains = [
        _daily_coverage(session, instrument_id=instrument_id, as_of=as_of),
        _intraday_coverage(session, instrument_id=instrument_id, as_of=as_of),
        _fundamentals_coverage(session, instrument_id=instrument_id, as_of=as_of),
        _events_coverage(session, instrument_id=instrument_id, as_of=as_of),
        _macro_coverage(session, as_of=as_of),
        _knowledge_coverage(session, instrument_id=instrument_id, as_of=as_of),
    ]
    return {
        "schema": "IntelligenceCoverageSummaryV1",
        "instrument_id": instrument_id,
        "as_of": as_of.isoformat() if as_of else None,
        "domains": [d.to_dict() for d in domains],
        "overall_status": overall_status(domains),
        "production_isolation": production_isolation_report(),
        "notes": (
            "Advisory measurement only; does not gate Candidate promotion.",
            "Intraday bars live in market.candles (timeframe 60m), not a new DB.",
            "Missing domain rows ⇒ NOT_READY, never fabricated READY.",
        ),
    }


def _status_from_counts(*, ready_floor: int, partial_floor: int, count: int) -> str:
    if count >= ready_floor:
        return "READY"
    if count >= partial_floor:
        return "PARTIAL"
    if count <= 0:
        return "NOT_READY"
    return "PARTIAL"


def _safe_scalar(session: Session, sql: str, params: dict[str, Any] | None = None) -> int:
    try:
        return int(session.execute(text(sql), params or {}).scalar_one() or 0)
    except Exception:  # noqa: BLE001 — coverage must not crash callers
        return -1


def _safe_ts(session: Session, sql: str, params: dict[str, Any] | None = None) -> datetime | None:
    try:
        value = session.execute(text(sql), params or {}).scalar_one_or_none()
        if isinstance(value, datetime | date):
            return value  # type: ignore[return-value]
        return None
    except Exception:  # noqa: BLE001
        return None


def _instrument_clause(column: str, instrument_id: int | None) -> tuple[str, dict[str, Any]]:
    if instrument_id is None:
        return "", {}
    return f" AND {column} = :instrument_id", {"instrument_id": int(instrument_id)}


def _as_of_date_clause(column: str, as_of: date | None) -> tuple[str, dict[str, Any]]:
    if as_of is None:
        return "", {}
    return f" AND {column} <= :as_of", {"as_of": as_of}


def _as_of_ts_clause(column: str, as_of: date | None) -> tuple[str, dict[str, Any]]:
    """PIT: known_at / timestamp must be <= end of as_of calendar day (date compare)."""
    if as_of is None:
        return "", {}
    return f" AND ({column})::date <= :as_of", {"as_of": as_of}


def _daily_coverage(
    session: Session,
    *,
    instrument_id: int | None,
    as_of: date | None,
) -> DomainCoverage:
    extra, params = _instrument_clause("instrument_id", instrument_id)
    asof_sql, asof_params = _as_of_ts_clause("timestamp", as_of)
    params = {**params, **asof_params}
    count = _safe_scalar(
        session,
        f"SELECT COUNT(*) FROM market.candles WHERE timeframe = '1d'{extra}{asof_sql}",
        params,
    )
    if count < 0:
        return DomainCoverage(
            domain="daily",
            status="UNKNOWN",
            detail="market.candles query failed",
            limitations=("store_unreachable_or_missing",),
        )
    distinct = _safe_scalar(
        session,
        f"SELECT COUNT(DISTINCT instrument_id) FROM market.candles "
        f"WHERE timeframe = '1d'{extra}{asof_sql}",
        params,
    )
    last = _safe_ts(
        session,
        f"SELECT MAX(timestamp) FROM market.candles WHERE timeframe = '1d'{extra}{asof_sql}",
        params,
    )
    # System-wide: READY when multiple instruments have daily history.
    ready_floor = 1 if instrument_id is not None else 500
    partial_floor = 1
    status = _status_from_counts(
        ready_floor=ready_floor, partial_floor=partial_floor, count=count
    )
    if instrument_id is None and distinct > 0 and distinct < 10 and status == "READY":
        status = "PARTIAL"
    return DomainCoverage(
        domain="daily",
        status=status,
        row_count=count,
        detail=f"1d candles={count}; distinct_instruments={max(distinct, 0)}",
        last_known_at=last,
        evidence={"timeframe": "1d", "distinct_instruments": max(distinct, 0)},
        limitations=("survivorship_free_universe_not_claimed",),
    )


def _intraday_coverage(
    session: Session,
    *,
    instrument_id: int | None,
    as_of: date | None,
) -> DomainCoverage:
    extra, params = _instrument_clause("instrument_id", instrument_id)
    asof_sql, asof_params = _as_of_ts_clause("timestamp", as_of)
    params = {**params, **asof_params}
    bars = _safe_scalar(
        session,
        f"SELECT COUNT(*) FROM market.candles WHERE timeframe = '60m'{extra}{asof_sql}",
        params,
    )
    feat_extra, feat_params = _instrument_clause("instrument_id", instrument_id)
    feat_asof, feat_asof_params = _as_of_date_clause("as_of", as_of)
    feat_params = {**feat_params, **feat_asof_params}
    features = _safe_scalar(
        session,
        "SELECT COUNT(*) FROM intelligence.intraday_feature_snapshots "
        f"WHERE TRUE{feat_extra}{feat_asof}",
        feat_params,
    )
    if bars < 0 and features < 0:
        return DomainCoverage(
            domain="intraday",
            status="UNKNOWN",
            detail="intraday store query failed",
            limitations=("store_unreachable_or_missing",),
        )
    bars_n = max(bars, 0)
    feat_n = max(features, 0)
    if bars_n == 0 and feat_n == 0:
        status = "NOT_READY"
    elif bars_n > 0 and feat_n > 0:
        status = "READY" if (instrument_id is not None or bars_n >= 100) else "PARTIAL"
    else:
        status = "PARTIAL"
    last = _safe_ts(
        session,
        f"SELECT MAX(timestamp) FROM market.candles WHERE timeframe = '60m'{extra}{asof_sql}",
        params,
    )
    return DomainCoverage(
        domain="intraday",
        status=status,
        row_count=bars_n,
        detail=f"60m_bars={bars_n}; feature_snapshots={feat_n}",
        last_known_at=last,
        evidence={
            "timeframe": "60m",
            "bars": bars_n,
            "feature_snapshots": feat_n,
            "storage": "market.candles",
        },
        limitations=(
            "no_ticks_or_order_book",
            "60m_only_in_v1_scope",
        ),
    )


def _fundamentals_coverage(
    session: Session,
    *,
    instrument_id: int | None,
    as_of: date | None,
) -> DomainCoverage:
    extra, params = _instrument_clause("instrument_id", instrument_id)
    asof_sql, asof_params = _as_of_date_clause("as_of", as_of)
    params = {**params, **asof_params}
    snaps = _safe_scalar(
        session,
        "SELECT COUNT(*) FROM intelligence.fundamental_snapshots "
        f"WHERE TRUE{extra}{asof_sql}",
        params,
    )
    ready_snaps = _safe_scalar(
        session,
        "SELECT COUNT(*) FROM intelligence.fundamental_snapshots "
        f"WHERE status = 'READY'{extra}{asof_sql}",
        params,
    )
    if snaps < 0:
        return DomainCoverage(
            domain="fundamentals",
            status="UNKNOWN",
            detail="intelligence.fundamental_snapshots unavailable",
            limitations=("apply_intelligence_migration",),
        )
    status = _status_from_counts(
        ready_floor=1 if instrument_id is not None else 20,
        partial_floor=1,
        count=max(ready_snaps, 0) if ready_snaps >= 0 else snaps,
    )
    if snaps > 0 and ready_snaps == 0:
        status = "PARTIAL"
    last = _safe_ts(
        session,
        "SELECT MAX(known_at) FROM intelligence.fundamental_snapshots "
        f"WHERE TRUE{extra}{asof_sql}",
        params,
    )
    return DomainCoverage(
        domain="fundamentals",
        status=status,
        row_count=max(snaps, 0),
        detail=f"fundamental_snapshots={snaps}; ready={max(ready_snaps, 0)}",
        last_known_at=last,
        evidence={"snapshots": max(snaps, 0), "ready": max(ready_snaps, 0)},
        limitations=(
            "bank_fi_issuer_kind_must_not_use_industrial_ratios",
            "period_end_is_not_known_at",
        ),
    )


def _events_coverage(
    session: Session,
    *,
    instrument_id: int | None,
    as_of: date | None,
) -> DomainCoverage:
    extra, params = _instrument_clause("instrument_id", instrument_id)
    asof_sql, asof_params = _as_of_ts_clause("known_at", as_of)
    params = {**params, **asof_params}
    events = _safe_scalar(
        session,
        "SELECT COUNT(*) FROM intelligence.intelligence_events "
        f"WHERE TRUE{extra}{asof_sql}",
        params,
    )
    doc_extra, doc_params = _instrument_clause("instrument_id", instrument_id)
    doc_asof, doc_asof_params = _as_of_ts_clause("known_at", as_of)
    doc_params = {**doc_params, **doc_asof_params}
    docs = _safe_scalar(
        session,
        "SELECT COUNT(*) FROM intelligence.source_documents "
        f"WHERE TRUE{doc_extra}{doc_asof}",
        doc_params,
    )
    if events < 0 and docs < 0:
        return DomainCoverage(
            domain="events",
            status="UNKNOWN",
            detail="events/documents store unavailable",
            limitations=("apply_intelligence_migration",),
        )
    events_n = max(events, 0)
    docs_n = max(docs, 0)
    if events_n == 0 and docs_n == 0:
        status = "NOT_READY"
    elif events_n > 0:
        status = "PARTIAL" if instrument_id is None and events_n < 50 else "READY"
        if instrument_id is not None:
            status = "READY"
    else:
        status = "PARTIAL"
    last = _safe_ts(
        session,
        "SELECT MAX(known_at) FROM intelligence.intelligence_events "
        f"WHERE TRUE{extra}{asof_sql}",
        params,
    )
    return DomainCoverage(
        domain="events",
        status=status,
        row_count=events_n,
        detail=f"events={events_n}; source_documents={docs_n}",
        last_known_at=last,
        evidence={"events": events_n, "source_documents": docs_n},
        limitations=(
            "no_fabricated_historical_timestamps",
            "known_at_gate_required_at_decision_time",
        ),
    )


def _macro_coverage(session: Session, *, as_of: date | None) -> DomainCoverage:
    asof_sql, params = _as_of_date_clause("as_of", as_of)
    snaps = _safe_scalar(
        session,
        f"SELECT COUNT(*) FROM intelligence.macro_snapshots WHERE TRUE{asof_sql}",
        params,
    )
    if snaps < 0:
        return DomainCoverage(
            domain="macro",
            status="UNKNOWN",
            detail="intelligence.macro_snapshots unavailable",
            limitations=("apply_intelligence_migration",),
        )
    status = _status_from_counts(ready_floor=5, partial_floor=1, count=snaps)
    last = _safe_ts(
        session,
        f"SELECT MAX(known_at) FROM intelligence.macro_snapshots WHERE TRUE{asof_sql}",
        params,
    )
    return DomainCoverage(
        domain="macro",
        status=status,
        row_count=snaps,
        detail=f"macro_snapshots={snaps}",
        last_known_at=last,
        evidence={"snapshots": snaps},
        limitations=("macro_is_cross_instrument",),
    )


def _knowledge_coverage(
    session: Session,
    *,
    instrument_id: int | None,
    as_of: date | None,
) -> DomainCoverage:
    rules = _safe_scalar(
        session,
        "SELECT COUNT(*) FROM intelligence.knowledge_rules WHERE status = 'ACTIVE'",
    )
    eval_extra, eval_params = _instrument_clause("instrument_id", instrument_id)
    eval_asof, eval_asof_params = _as_of_date_clause("as_of", as_of)
    eval_params = {**eval_params, **eval_asof_params}
    evals = _safe_scalar(
        session,
        "SELECT COUNT(*) FROM intelligence.knowledge_rule_evaluations "
        f"WHERE TRUE{eval_extra}{eval_asof}",
        eval_params,
    )
    if rules < 0 and evals < 0:
        return DomainCoverage(
            domain="knowledge",
            status="UNKNOWN",
            detail="knowledge tables unavailable",
            limitations=("apply_intelligence_migration",),
        )
    rules_n = max(rules, 0)
    evals_n = max(evals, 0)
    if rules_n == 0:
        status = "NOT_READY"
    elif evals_n == 0:
        status = "PARTIAL"
    else:
        status = "READY" if rules_n >= 3 else "PARTIAL"
    return DomainCoverage(
        domain="knowledge",
        status=status,
        row_count=rules_n,
        detail=f"active_rules={rules_n}; evaluations={evals_n}",
        evidence={"active_rules": rules_n, "evaluations": evals_n},
        limitations=("rules_are_advisory_not_orders",),
    )
