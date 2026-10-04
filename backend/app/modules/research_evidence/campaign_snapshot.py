"""ResearchDataSnapshotV1 — honest local data coverage for Canonical Evidence Campaign V1.

Availability statuses are READY / PARTIAL / NOT_READY only. They are not alpha judgments.
Missing observations stay missing (None). Empty dividend rows are missing coverage, not
a zero-dividend universe.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Date, cast, distinct, func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, CorporateAction, Instrument, SeriesValue
from app.modules.prediction.infrastructure.artifacts import write_json
from app.modules.research_evidence.bundle import RUNTIME_TIMESTAMP_KEYS, payload_file_hash
from app.modules.research_evidence.campaign_window import resolve_primary_campaign_window
from app.modules.research_evidence.paths import research_evidence_root

SNAPSHOT_VERSION = "research_data_snapshot_v1"
AVAILABILITY_READY = "READY"
AVAILABILITY_PARTIAL = "PARTIAL"
AVAILABILITY_NOT_READY = "NOT_READY"
ALLOWED_AVAILABILITY = frozenset({AVAILABILITY_READY, AVAILABILITY_PARTIAL, AVAILABILITY_NOT_READY})
MISSING_COVERAGE = "MISSING_COVERAGE"
NOT_ZERO_OBSERVATION = "NOT_ZERO_OBSERVATION"
SNAPSHOT_RUNTIME_KEYS = RUNTIME_TIMESTAMP_KEYS | frozenset(
    {
        "data_snapshot_hash",
        "duration_ms",
        "elapsed_ms",
        "query_timing_ms",
        "timings",
    }
)


def _iso_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.isoformat()


def _safe_int(session: Session, stmt: Any) -> int | None:
    """Return a count, or None when the store cannot answer (never coerce missing → 0)."""
    try:
        value = session.scalar(stmt)
    except Exception:  # noqa: BLE001
        return None
    if value is None:
        return 0
    return int(value)


def _safe_rows(session: Session, stmt: Any) -> list[Any]:
    try:
        return list(session.execute(stmt).all())
    except Exception:  # noqa: BLE001
        return []


def _clamp_status(status: str) -> str:
    if status in ALLOWED_AVAILABILITY:
        return status
    return AVAILABILITY_NOT_READY


def _domain(*, code: str, status: str, evidence: dict[str, Any], note: str) -> dict[str, Any]:
    return {
        "code": code,
        "status": _clamp_status(status),
        "availability_only": True,
        "alpha_judgment": False,
        "note": note,
        "evidence": evidence,
    }


def snapshot_semantic_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: snapshot_semantic_payload(value)
            for key, value in payload.items()
            if key not in SNAPSHOT_RUNTIME_KEYS
        }
    if isinstance(payload, list):
        return [snapshot_semantic_payload(item) for item in payload]
    return payload


def data_snapshot_hash(payload: Any) -> str:
    """SHA-256 of canonical semantic JSON excluding created_at / timings.

    Prefer hashing an on-disk payload (write_json may coerce NaN/Inf to null).
    """
    return payload_file_hash(snapshot_semantic_payload(payload))


def research_data_snapshot_path(*, root: Path | None = None) -> Path:
    return research_evidence_root(root) / "campaign" / "research_data_snapshot_v1.json"


def write_research_data_snapshot(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist JSON then hash the on-disk file (NaN/Inf disk-true, same as evidence bundles)."""
    write_json(path, payload)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    digest = data_snapshot_hash(on_disk)
    if on_disk.get("data_snapshot_hash") != digest:
        on_disk["data_snapshot_hash"] = digest
        write_json(path, on_disk)
    return {
        "path": str(path),
        "data_snapshot_hash": digest,
        "schema_version": SNAPSHOT_VERSION,
    }


def _instrument_counts(session: Session) -> dict[str, Any]:
    total = _safe_int(session, select(func.count()).select_from(Instrument))
    equity = _safe_int(
        session, select(func.count()).select_from(Instrument).where(Instrument.asset_class == "equity")
    )
    active_equity = _safe_int(
        session,
        select(func.count())
        .select_from(Instrument)
        .where(Instrument.asset_class == "equity", Instrument.is_active.is_(True)),
    )
    inactive_equity: int | None
    if equity is None or active_equity is None:
        inactive_equity = None
    else:
        inactive_equity = equity - active_equity
    if total is None:
        status = AVAILABILITY_NOT_READY
    elif (equity or 0) > 0:
        status = AVAILABILITY_READY
    else:
        status = AVAILABILITY_NOT_READY
    return _domain(
        code="instruments",
        status=status,
        note="Instrument master counts; inactive ≠ deleted history.",
        evidence={
            "total_instrument_master_count": total,
            "equity_count": equity,
            "active_equity_count": active_equity,
            "inactive_equity_count": inactive_equity,
        },
    )


def _price_coverage(session: Session) -> dict[str, Any]:
    candle_n = _safe_int(
        session,
        select(func.count()).select_from(Candle).where(Candle.timeframe == "1d"),
    )
    equity_candles = _safe_int(
        session,
        select(func.count())
        .select_from(Candle)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Candle.timeframe == "1d", Instrument.asset_class == "equity"),
    )
    with_history = _safe_int(
        session,
        select(func.count(distinct(Candle.instrument_id)))
        .select_from(Candle)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Candle.timeframe == "1d", Instrument.asset_class == "equity"),
    )
    bounds_rows = _safe_rows(
        session,
        select(func.min(cast(Candle.timestamp, Date)), func.max(cast(Candle.timestamp, Date)))
        .select_from(Candle)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Candle.timeframe == "1d", Instrument.asset_class == "equity"),
    )
    earliest = latest = None
    if bounds_rows:
        earliest, latest = bounds_rows[0]
        earliest = earliest.isoformat() if isinstance(earliest, date) else None
        latest = latest.isoformat() if isinstance(latest, date) else None
    year_rows = _safe_rows(
        session,
        select(func.extract("year", Candle.timestamp), func.count())
        .select_from(Candle)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Candle.timeframe == "1d", Instrument.asset_class == "equity")
        .group_by(func.extract("year", Candle.timestamp))
        .order_by(func.extract("year", Candle.timestamp)),
    )
    per_year = []
    for year, n in year_rows:
        if year is None:
            continue
        per_year.append({"year": int(year), "daily_equity_candles": int(n)})
    missing_open = _safe_int(
        session,
        select(func.count()).select_from(Candle).where(Candle.timeframe == "1d", Candle.open.is_(None)),
    )
    missing_close = _safe_int(
        session,
        select(func.count()).select_from(Candle).where(Candle.timeframe == "1d", Candle.close.is_(None)),
    )
    if candle_n is None:
        status = AVAILABILITY_NOT_READY
    elif (equity_candles or 0) > 0:
        status = AVAILABILITY_READY
    else:
        status = AVAILABILITY_NOT_READY
    return _domain(
        code="prices",
        status=status,
        note=(
            "RAW market.candles OHLCV. Column NOT NULL means stored missing OPEN/CLOSE is 0 rows, "
            "not that ingest never coerced a missing open to close."
        ),
        evidence={
            "daily_candles": candle_n,
            "daily_equity_candles": equity_candles,
            "instruments_with_daily_history": with_history,
            "earliest_daily_equity_candle": earliest,
            "latest_daily_equity_candle": latest,
            "per_year_sample_coverage": per_year,
            "missing_open_counts": missing_open,
            "missing_close_counts": missing_close,
        },
    )


def _corporate_actions(session: Session) -> dict[str, Any]:
    from app.modules.market.application.split_events import (
        EVENT_TYPE_REVERSE_SPLIT,
        EVENT_TYPE_SPLIT,
        SPLIT_FEED_EVENT_TYPES,
    )

    splits = _safe_int(
        session,
        select(func.count())
        .select_from(CorporateAction)
        .where(CorporateAction.event_type == EVENT_TYPE_SPLIT),
    )
    reverse_splits = _safe_int(
        session,
        select(func.count())
        .select_from(CorporateAction)
        .where(CorporateAction.event_type == EVENT_TYPE_REVERSE_SPLIT),
    )
    affected = _safe_int(
        session,
        select(func.count(distinct(CorporateAction.instrument_id))).where(
            CorporateAction.event_type.in_(SPLIT_FEED_EVENT_TYPES)
        ),
    )
    bounds = _safe_rows(
        session,
        select(func.min(CorporateAction.event_date), func.max(CorporateAction.event_date)).where(
            CorporateAction.event_type.in_(SPLIT_FEED_EVENT_TYPES)
        ),
    )
    known_at_n = _safe_int(
        session,
        select(func.count())
        .select_from(CorporateAction)
        .where(
            CorporateAction.event_type.in_(SPLIT_FEED_EVENT_TYPES),
            CorporateAction.known_at.is_not(None),
        ),
    )
    known_at_missing = _safe_int(
        session,
        select(func.count())
        .select_from(CorporateAction)
        .where(
            CorporateAction.event_type.in_(SPLIT_FEED_EVENT_TYPES),
            CorporateAction.known_at.is_(None),
        ),
    )
    earliest = latest = None
    if bounds:
        earliest, latest = bounds[0]
        earliest = earliest.isoformat() if isinstance(earliest, date) else None
        latest = latest.isoformat() if isinstance(latest, date) else None
    n = (splits or 0) + (reverse_splits or 0) if splits is not None and reverse_splits is not None else None
    if splits is None:
        status = AVAILABILITY_NOT_READY
    elif (n or 0) > 0:
        status = AVAILABILITY_PARTIAL
    else:
        status = AVAILABILITY_NOT_READY
    return _domain(
        code="corporate_actions",
        status=status,
        note="Mechanical SPLIT/REVERSE_SPLIT events only. known_at may be NULL; do not fabricate.",
        evidence={
            "split_count": splits,
            "reverse_split_count": reverse_splits,
            "instruments_affected": affected,
            "event_date_from": earliest,
            "event_date_to": latest,
            "known_at_present": known_at_n,
            "known_at_missing": known_at_missing,
            "known_at_quality": "NULL_ALLOWED_NOT_FABRICATED",
        },
    )


def _fundamentals(session: Session) -> tuple[dict[str, Any], dict[str, Any]]:
    from app.modules.fundamentals.application.coverage_service import FundamentalCoverageService
    from app.modules.fundamentals.application.pit import BASIS_CURRENT_ONLY, BASIS_DATED_WINDOW
    from app.modules.fundamentals.domain.types import MappingStatus
    from app.modules.fundamentals.infrastructure.models import (
        FinancialReport,
        SecurityIssuerMapping,
        fundamentals_schema_ready,
    )

    schema_ok = False
    try:
        schema_ok = bool(fundamentals_schema_ready(session))
    except Exception:  # noqa: BLE001
        schema_ok = False

    mapping_counts = {
        BASIS_DATED_WINDOW: None,
        BASIS_CURRENT_ONLY: None,
        MappingStatus.UNMAPPED.value: None,
        MappingStatus.AMBIGUOUS.value: None,
    }
    reports_by_year: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    known_at_present = known_at_missing = None
    known_at_min = known_at_max = None
    store: dict[str, Any] = {}
    cohort: dict[str, Any] = {}

    if schema_ok:
        mapping_counts[MappingStatus.UNMAPPED.value] = _safe_int(
            session,
            select(func.count())
            .select_from(SecurityIssuerMapping)
            .where(SecurityIssuerMapping.mapping_status == MappingStatus.UNMAPPED.value),
        )
        mapping_counts[MappingStatus.AMBIGUOUS.value] = _safe_int(
            session,
            select(func.count())
            .select_from(SecurityIssuerMapping)
            .where(SecurityIssuerMapping.mapping_status == MappingStatus.AMBIGUOUS.value),
        )
        mapping_counts[BASIS_DATED_WINDOW] = _safe_int(
            session,
            select(func.count())
            .select_from(SecurityIssuerMapping)
            .where(
                SecurityIssuerMapping.mapping_status == MappingStatus.MAPPED.value,
                SecurityIssuerMapping.valid_from.is_not(None),
            ),
        )
        mapping_counts[BASIS_CURRENT_ONLY] = _safe_int(
            session,
            select(func.count())
            .select_from(SecurityIssuerMapping)
            .where(
                SecurityIssuerMapping.mapping_status == MappingStatus.MAPPED.value,
                SecurityIssuerMapping.valid_from.is_(None),
            ),
        )
        year_rows = _safe_rows(
            session,
            select(func.extract("year", FinancialReport.period_end), func.count())
            .select_from(FinancialReport)
            .group_by(func.extract("year", FinancialReport.period_end))
            .order_by(func.extract("year", FinancialReport.period_end)),
        )
        for year, n in year_rows:
            if year is None:
                continue
            reports_by_year.append({"year": int(year), "reports": int(n)})
        source_rows = _safe_rows(
            session,
            select(FinancialReport.source, func.count())
            .select_from(FinancialReport)
            .group_by(FinancialReport.source)
            .order_by(FinancialReport.source),
        )
        sources = [{"source": str(src), "reports": int(n)} for src, n in source_rows]
        known_at_present = _safe_int(
            session,
            select(func.count()).select_from(FinancialReport).where(FinancialReport.known_at.is_not(None)),
        )
        known_at_missing = _safe_int(
            session,
            select(func.count()).select_from(FinancialReport).where(FinancialReport.known_at.is_(None)),
        )
        ka_bounds = _safe_rows(
            session,
            select(func.min(FinancialReport.known_at), func.max(FinancialReport.known_at)),
        )
        if ka_bounds:
            known_at_min, known_at_max = ka_bounds[0]
            known_at_min = known_at_min.isoformat() if isinstance(known_at_min, date) else None
            known_at_max = known_at_max.isoformat() if isinstance(known_at_max, date) else None
        try:
            cov = FundamentalCoverageService(session)
            store = cov.store_summary()
            cohort = cov.cohort_table()
            cohort = {k: v for k, v in cohort.items() if k != "rows"}
        except Exception as exc:  # noqa: BLE001
            store = {"error": str(exc)[:200]}
            cohort = {"error": str(exc)[:200]}

    industrial_reports = store.get("fns_gir_bo_reports") if isinstance(store, dict) else None
    if industrial_reports is None:
        fund_status = AVAILABILITY_NOT_READY
    elif int(industrial_reports or 0) > 0:
        fund_status = AVAILABILITY_PARTIAL
    else:
        fund_status = AVAILABILITY_NOT_READY

    fundamentals = _domain(
        code="fundamentals",
        status=fund_status,
        note=(
            "No FNS report does not mean zero company fundamentals. "
            "Banks/FI stay NOT_SUPPORTED — do not fill industrial zeros."
        ),
        evidence={
            "schema_ready": schema_ok,
            "issuer_mappings": mapping_counts,
            "industrial_report_coverage": cohort,
            "store": store,
            "reports_by_year": reports_by_year,
            "report_sources": sources,
            "known_at_present": known_at_present,
            "known_at_missing": known_at_missing,
            "known_at_min": known_at_min,
            "known_at_max": known_at_max,
            "known_at_quality": "STORED_AVAILABILITY_DATE_NOT_FABRICATED",
            "empty_report_store_means": MISSING_COVERAGE,
        },
    )
    banks = _domain(
        code="fundamentals_banks",
        status=AVAILABILITY_NOT_READY,
        note="FNS industrial RAS does not support banks/FI. Do not invent industrial-style zeros.",
        evidence={
            "fns_support": "NOT_SUPPORTED_BY_FNS_RAS_V1",
            "bank_unsupported": cohort.get("bank_unsupported") if isinstance(cohort, dict) else None,
        },
    )
    return fundamentals, banks


def _events_and_total_return(session: Session) -> tuple[dict[str, Any], dict[str, Any]]:
    from app.modules.fundamentals.application.dividend_provider import get_dividend_provider
    from app.modules.fundamentals.infrastructure.models import DividendEvent, fundamentals_schema_ready

    schema_ok = False
    try:
        schema_ok = bool(fundamentals_schema_ready(session))
    except Exception:  # noqa: BLE001
        schema_ok = False

    events: int | None
    if schema_ok:
        events = _safe_int(session, select(func.count()).select_from(DividendEvent))
        known_at_n = _safe_int(
            session,
            select(func.count()).select_from(DividendEvent).where(DividendEvent.known_at.is_not(None)),
        )
    else:
        events = None
        known_at_n = None

    try:
        provider = get_dividend_provider().readiness()
    except Exception as exc:  # noqa: BLE001
        provider = {"status": AVAILABILITY_NOT_READY, "accepted": False, "error": str(exc)[:200]}

    accepted = bool(provider.get("accepted")) if isinstance(provider, dict) else False
    if events is None:
        div_status = AVAILABILITY_NOT_READY
        interpretation = MISSING_COVERAGE
    elif events == 0:
        div_status = AVAILABILITY_NOT_READY
        interpretation = MISSING_COVERAGE
    else:
        div_status = AVAILABILITY_PARTIAL
        interpretation = "STORED_DISCLOSURES_PARTIAL_UNIVERSE"

    events_domain = _domain(
        code="events",
        status=div_status,
        note="Empty dividend_events is missing coverage, not a zero-dividend market.",
        evidence={
            "stored_dividend_disclosures": events,
            "empty_store_means": interpretation,
            "not_implied": NOT_ZERO_OBSERVATION,
            "split_events_see": "corporate_actions",
            "known_at_present": known_at_n,
            "known_at_quality": "STORED_OR_MISSING_NOT_FABRICATED",
            "provider": provider,
        },
    )
    if events is None or events == 0 or not accepted:
        tr_status = AVAILABILITY_NOT_READY
        accepted_tr = False
        universe_wide = False
        verdict = AVAILABILITY_NOT_READY
    else:
        tr_status = AVAILABILITY_PARTIAL
        accepted_tr = False
        universe_wide = False
        verdict = AVAILABILITY_PARTIAL
    total_return = _domain(
        code="total_return",
        status=tr_status,
        note="Gross total return is not the campaign primary label (mechanical price return).",
        evidence={
            "provider_readiness": provider,
            "accepted": accepted_tr,
            "universe_wide": universe_wide,
            "verdict": verdict,
            "depends_on_stored_dividend_disclosures": events,
        },
    )
    return events_domain, total_return


def _macro(session: Session) -> dict[str, Any]:
    n = _safe_int(session, select(func.count()).select_from(SeriesValue))
    if n is None:
        status = AVAILABILITY_NOT_READY
    elif n > 0:
        status = AVAILABILITY_PARTIAL
    else:
        status = AVAILABILITY_NOT_READY
    return _domain(
        code="macro",
        status=status,
        note="Existing CBR/series store only; no new macro pack in this snapshot.",
        evidence={"series_values": n, "relevant_to_dataset_or_economics": True},
    )


def _universe(session: Session) -> dict[str, Any]:
    from app.modules.market.application.historical_universe import (
        HISTORICAL_EQUITY_UNIVERSE_V2,
        summarize_historical_universe,
    )

    try:
        summary = summarize_historical_universe(session, version=HISTORICAL_EQUITY_UNIVERSE_V2)
    except Exception as exc:  # noqa: BLE001
        summary = {"version": HISTORICAL_EQUITY_UNIVERSE_V2, "members": None, "error": str(exc)[:200]}
    members = summary.get("members")
    if members is None:
        status = AVAILABILITY_NOT_READY
    elif int(members) > 0:
        status = AVAILABILITY_PARTIAL
    else:
        status = AVAILABILITY_NOT_READY
    return _domain(
        code="historical_universe",
        status=status,
        note="historical_equity_universe_v2 eligibility boundaries; candle proxy remains explicit.",
        evidence=summary if isinstance(summary, dict) else {"raw": str(summary)},
    )


def _observation_boundary(window: dict[str, Any], prices: dict[str, Any]) -> dict[str, Any]:
    evidence = prices.get("evidence") if isinstance(prices, dict) else {}
    return {
        "store": "postgres_core",
        "raw_prices": "market.candles",
        "earliest_daily_equity_candle": (evidence or {}).get("earliest_daily_equity_candle"),
        "latest_daily_equity_candle": (evidence or {}).get("latest_daily_equity_candle"),
        "latest_mature_20d_as_of": window.get("latest_mature_20d_as_of") if isinstance(window, dict) else None,
        "note": "Decision-time knowledge is known_at / as_of, not a future database row.",
    }


def _overall_availability(domains: list[dict[str, Any]], window: dict[str, Any]) -> str:
    if window.get("status") == "CAMPAIGN_DATA_INSUFFICIENT":
        return AVAILABILITY_NOT_READY
    by_code = {d["code"]: d["status"] for d in domains}
    if by_code.get("prices") == AVAILABILITY_READY and by_code.get("historical_universe") != AVAILABILITY_NOT_READY:
        if any(d["status"] != AVAILABILITY_READY for d in domains):
            return AVAILABILITY_PARTIAL
        return AVAILABILITY_READY
    if by_code.get("prices") == AVAILABILITY_READY:
        return AVAILABILITY_PARTIAL
    return AVAILABILITY_NOT_READY


def build_research_data_snapshot(
    session: Session,
    *,
    created_at: datetime | None = None,
    window: dict[str, Any] | None = None,
    query_timing_ms: float | None = None,
) -> dict[str, Any]:
    """Assemble ResearchDataSnapshotV1. Does not train models or judge alpha."""
    stamped = created_at or datetime.now(UTC)
    window_payload = window if window is not None else resolve_primary_campaign_window(session)
    instruments = _instrument_counts(session)
    prices = _price_coverage(session)
    universe = _universe(session)
    corporate = _corporate_actions(session)
    fundamentals, banks = _fundamentals(session)
    events, total_return = _events_and_total_return(session)
    macro = _macro(session)
    domains = [instruments, prices, universe, corporate, fundamentals, banks, events, total_return, macro]
    payload = {
        "schema": SNAPSHOT_VERSION,
        "schema_version": SNAPSHOT_VERSION,
        "created_at": _iso_dt(stamped),
        "query_timing_ms": query_timing_ms,
        "research_only": True,
        "alpha_judgment": False,
        "missing_policy": "missing_is_not_zero",
        "empty_dividend_rows_mean": MISSING_COVERAGE,
        "observation_boundary": _observation_boundary(window_payload, prices),
        "campaign_window": window_payload,
        "instruments": instruments["evidence"],
        "historical_universe": universe["evidence"],
        "prices": prices["evidence"],
        "corporate_actions": corporate["evidence"],
        "fundamentals": fundamentals["evidence"],
        "events": events["evidence"],
        "total_return": total_return["evidence"],
        "macro": macro["evidence"],
        "domains": domains,
        "overall_availability": _overall_availability(domains, window_payload),
        "campaign_window_status": window_payload.get("status"),
    }
    payload["data_snapshot_hash"] = data_snapshot_hash(payload)
    return payload
