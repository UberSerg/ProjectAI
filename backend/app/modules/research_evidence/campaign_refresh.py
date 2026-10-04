"""Audit-only wrappers around existing campaign data refresh workflows.

Does not invent scrapers, paid vendors, or fabricated known_at. Tests inject fake
sessions/hooks; runtime may call existing MOEX/FNS/CBR providers when dry_run=False.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Candle, CorporateAction, Instrument, SeriesValue

RefreshHook = Callable[[Session], dict[str, Any]]

ALLOWED_SOURCES = (
    "MOEX_ISS_CANDLES",
    "MOEX_ISS_INSTRUMENT_MASTER",
    "MOEX_ISS_SPLITS",
    "FNS_GIR_BO",
    "CBR_SERIES",
)

WORKFLOW_SPECS: tuple[dict[str, str], ...] = (
    {
        "source": "MOEX_ISS_CANDLES",
        "workflow": "MarketIngestionService.run_update",
        "accepted_data": "instrument_identity_and_daily_candles",
    },
    {
        "source": "CBR_SERIES",
        "workflow": "MarketIngestionService.run_update",
        "accepted_data": "existing_cbr_macro_series_only",
    },
    {
        "source": "MOEX_ISS_INSTRUMENT_MASTER",
        "workflow": "MoexInstrumentMasterSync.run",
        "accepted_data": "instrument_identity",
    },
    {
        "source": "MOEX_ISS_SPLITS",
        "workflow": "SplitIngestionService.run",
        "accepted_data": "splits_where_accepted_implementation_exists",
    },
    {
        "source": "FNS_GIR_BO",
        "workflow": "sync_fundamentals_fns",
        "accepted_data": "industrial_ras_existing_pit_known_at",
    },
)


def _safe_int(session: Session, stmt: Any) -> int | None:
    try:
        value = session.scalar(stmt)
    except Exception:  # noqa: BLE001
        return None
    if value is None:
        return 0
    return int(value)


def inspect_campaign_coverage(session: Session) -> dict[str, Any]:
    """Local coverage counts used as before/after audit. No network."""
    from app.modules.fundamentals.infrastructure.models import (
        DividendEvent,
        FinancialReport,
        fundamentals_schema_ready,
    )

    schema_ok = False
    try:
        schema_ok = bool(fundamentals_schema_ready(session))
    except Exception:  # noqa: BLE001
        schema_ok = False

    fns_reports: int | None
    dividend_events: int | None
    if schema_ok:
        fns_reports = _safe_int(
            session,
            select(func.count()).select_from(FinancialReport).where(FinancialReport.source == "FNS_GIR_BO"),
        )
        dividend_events = _safe_int(session, select(func.count()).select_from(DividendEvent))
    else:
        fns_reports = None
        dividend_events = None

    return {
        "equity_instruments": _safe_int(
            session, select(func.count()).select_from(Instrument).where(Instrument.asset_class == "equity")
        ),
        "daily_equity_candles": _safe_int(
            session,
            select(func.count())
            .select_from(Candle)
            .join(Instrument, Instrument.id == Candle.instrument_id)
            .where(Candle.timeframe == "1d", Instrument.asset_class == "equity"),
        ),
        "instruments_with_daily_history": _safe_int(
            session,
            select(func.count(distinct(Candle.instrument_id)))
            .select_from(Candle)
            .join(Instrument, Instrument.id == Candle.instrument_id)
            .where(Candle.timeframe == "1d", Instrument.asset_class == "equity"),
        ),
        "corporate_actions": _safe_int(session, select(func.count()).select_from(CorporateAction)),
        "fns_gir_bo_reports": fns_reports,
        "dividend_events": dividend_events,
        "empty_dividend_events_mean": "MISSING_COVERAGE",
        "series_values": _safe_int(session, select(func.count()).select_from(SeriesValue)),
        "fundamentals_schema_ready": schema_ok,
    }


def _coverage_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    keys = set(before) | set(after)
    for key in sorted(keys):
        left, right = before.get(key), after.get(key)
        if isinstance(left, int) and isinstance(right, int):
            delta[key] = {"before": left, "after": right, "delta": right - left}
        elif left != right:
            delta[key] = {"before": left, "after": right}
    return delta


def _default_market_update(session: Session) -> dict[str, Any]:
    from app.modules.market.application.ingest import MarketIngestionService

    return MarketIngestionService(session).run_update()


def _default_instrument_master(session: Session) -> dict[str, Any]:
    from app.modules.market.application.instrument_master_sync import run_instrument_master_sync

    return run_instrument_master_sync(session)


def _default_splits(session: Session) -> dict[str, Any]:
    from app.modules.market.application.corporate_actions import SplitIngestionService

    return SplitIngestionService(session).run()


def _default_fns(session: Session) -> dict[str, Any]:
    from app.modules.fundamentals.application.sync_fundamentals_fns import sync_fundamentals_fns

    result = sync_fundamentals_fns(session)
    return result.to_dict() if hasattr(result, "to_dict") else dict(result)


def refresh_campaign_data(
    session: Session,
    *,
    dry_run: bool = True,
    sources: list[str] | None = None,
    market_update: RefreshHook | None = None,
    instrument_master: RefreshHook | None = None,
    splits: RefreshHook | None = None,
    fns_sync: RefreshHook | None = None,
) -> dict[str, Any]:
    """Inspect coverage, optionally wrap existing ingest/FNS/split workflows, audit after.

    Default ``dry_run=True`` never calls providers. Runtime must pass dry_run=False.
    """
    wanted = tuple(sources) if sources is not None else ALLOWED_SOURCES
    unknown = [name for name in wanted if name not in ALLOWED_SOURCES]
    before = inspect_campaign_coverage(session)
    steps: list[dict[str, Any]] = []
    errors: list[str] = []

    runners: dict[str, RefreshHook | None] = {
        "MOEX_ISS_CANDLES": market_update,
        "CBR_SERIES": None,
        "MOEX_ISS_INSTRUMENT_MASTER": instrument_master,
        "MOEX_ISS_SPLITS": splits,
        "FNS_GIR_BO": fns_sync,
    }
    defaults: dict[str, RefreshHook] = {
        "MOEX_ISS_CANDLES": _default_market_update,
        "MOEX_ISS_INSTRUMENT_MASTER": _default_instrument_master,
        "MOEX_ISS_SPLITS": _default_splits,
        "FNS_GIR_BO": _default_fns,
    }

    for spec in WORKFLOW_SPECS:
        source = spec["source"]
        if source not in wanted:
            continue
        step: dict[str, Any] = {
            "source": source,
            "workflow": spec["workflow"],
            "accepted_data": spec["accepted_data"],
            "dry_run": dry_run,
            "secrets_recorded": False,
        }
        if source == "CBR_SERIES":
            step["status"] = "COVERED_BY_MARKET_UPDATE"
            step["note"] = "CBR series ride existing MarketIngestionService; no separate scraper."
            steps.append(step)
            continue
        if dry_run:
            step["status"] = "DRY_RUN"
            step["rows_inserted"] = 0
            step["rows_updated"] = 0
            steps.append(step)
            continue
        runner = runners.get(source) or defaults.get(source)
        if runner is None:
            step["status"] = "SKIPPED"
            steps.append(step)
            continue
        try:
            result = runner(session)
            step["status"] = "RAN"
            step["result"] = _public_result(result)
            step["rows_inserted"] = _result_count(result, "inserted")
            step["rows_updated"] = _result_count(result, "updated")
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            errors.append(f"{source}: {message}")
            step["status"] = "ERROR"
            step["error"] = message
        steps.append(step)

    after = inspect_campaign_coverage(session) if not dry_run else dict(before)
    return {
        "dry_run": dry_run,
        "unknown_sources": unknown,
        "before": before,
        "after": after,
        "coverage_delta": _coverage_delta(before, after),
        "steps": steps,
        "errors": errors,
        "invented_scrapers": False,
        "fabricated_known_at": False,
        "paid_vendors": False,
    }


def _result_count(result: Any, key: str) -> int | None:
    if not isinstance(result, dict):
        return None
    if key in result and isinstance(result[key], int):
        return int(result[key])
    nested = result.get("stats") if isinstance(result.get("stats"), dict) else {}
    if key in nested and isinstance(nested[key], int):
        return int(nested[key])
    alt = {
        "inserted": ("records_inserted", "reports_inserted"),
        "updated": ("records_updated", "reports_skipped"),
    }
    for candidate in alt.get(key, ()):
        if isinstance(result.get(candidate), int):
            return int(result[candidate])
    return None


def _public_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"type": type(result).__name__}
    blocked = ("api_key", "token", "password", "secret", "authorization", "cookie")
    return {k: v for k, v in result.items() if str(k).lower() not in blocked and "secret" not in str(k).lower()}
