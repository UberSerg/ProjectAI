"""Fixed Income Enrichment V2 — queue, batch runner, single-instrument enrich.

Reuses MoexBondClient + ingest_bonds helpers. Never wipes good BondTerm on
source failure. Does NOT auto-grow research_fi_v1.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import redis
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.infrastructure.market.models import Instrument, InstrumentEnrichmentJob, InstrumentSource
from app.modules.investment.application.ingest_bonds import (
    _bond_type,
    _date,
    _decimal,
    _persist_schedule_cashflows,
)
from app.modules.investment.domain.cashflows import (
    MOEX_BONDIZATION_KNOWN_AT_QUALITY,
    classify_bond_support_v1,
    coupon_structure_fixed,
    future_offers,
    has_complex_amortization,
    parse_bondization_schedule,
    remaining_coupons,
)
from app.modules.investment.domain.currency import resolve_nominal_currency
from app.modules.investment.domain.enrichment import (
    FI_KINDS,
    LOCK_KEY,
    LOCK_TTL_SECONDS,
    EnrichmentKind,
    EnrichmentPriority,
    EnrichmentStatus,
)
from app.modules.investment.domain.fixed_income import CreditQualityStatus
from app.modules.investment.infrastructure.models import BondCashflow, BondMarketSnapshot, BondTerm
from app.modules.investment.infrastructure.moex_bonds import (
    SOURCE_BOARD,
    SOURCE_BONDIZATION,
    MoexBondClient,
)
from app.modules.market.application.instrument_classification import OFZ_GOV

logger = get_logger(__name__, component="fi_enrichment")


def enqueue_enrichment(
    session: Session,
    instrument_id: int,
    kind: EnrichmentKind | str,
    priority: int | EnrichmentPriority = EnrichmentPriority.P3_OTHER_BOND,
) -> InstrumentEnrichmentJob:
    """Upsert queue row for (instrument_id, kind). Improves priority if already queued."""
    kind_s = kind.value if isinstance(kind, EnrichmentKind) else str(kind)
    pri = int(priority)
    now = datetime.now(UTC)
    existing = session.scalar(
        select(InstrumentEnrichmentJob).where(
            InstrumentEnrichmentJob.instrument_id == instrument_id,
            InstrumentEnrichmentJob.kind == kind_s,
        )
    )
    if existing is None:
        job = InstrumentEnrichmentJob(
            instrument_id=instrument_id,
            kind=kind_s,
            priority=pri,
            status=EnrichmentStatus.PENDING.value,
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        session.flush()
        return job

    # Re-queue failed / stale; never demote priority; bump to PENDING if done.
    if pri < int(existing.priority):
        existing.priority = pri
    if existing.status in {
        EnrichmentStatus.SUCCESS.value,
        EnrichmentStatus.PARTIAL.value,
        EnrichmentStatus.FAILED.value,
        EnrichmentStatus.NO_DATA.value,
    }:
        existing.status = EnrichmentStatus.PENDING.value
        existing.next_retry_at = None
        existing.last_error = None
    existing.updated_at = now
    session.flush()
    return existing


def enqueue_fi_kinds(
    session: Session,
    instrument_id: int,
    priority: int | EnrichmentPriority,
) -> list[InstrumentEnrichmentJob]:
    return [enqueue_enrichment(session, instrument_id, kind, priority) for kind in FI_KINDS]


def priority_for_instrument(session: Session, instrument: Instrument) -> EnrichmentPriority:
    if not instrument.is_active or (instrument.support_level or "").upper() == "INACTIVE":
        return EnrichmentPriority.P4_INACTIVE
    subtype = (instrument.instrument_subtype or "").lower()
    if subtype == OFZ_GOV or str(instrument.symbol or "").upper().startswith("SU"):
        return EnrichmentPriority.P2_OFZ
    return EnrichmentPriority.P3_OTHER_BOND


def enqueue_new_bond_from_master(session: Session, instrument: Instrument) -> list[InstrumentEnrichmentJob]:
    """Hook after Instrument Master discovers/updates a bond — P1 for new, else subtype priority."""
    if (instrument.asset_class or "").lower() != "bond":
        return []
    pri = EnrichmentPriority.P1_NEW_BOND
    # Downgrade to subtype priority if terms already exist (refresh, not discovery).
    has_term = session.scalar(select(BondTerm.id).where(BondTerm.instrument_id == instrument.id))
    if has_term is not None:
        pri = priority_for_instrument(session, instrument)
    return enqueue_fi_kinds(session, int(instrument.id), pri)


def enqueue_p0_portfolio_positions(session: Session) -> dict[str, int]:
    """Enqueue P0 for Manual Portfolio + Shadow bond positions (startup / catch-up)."""
    from app.modules.portfolio.application.manual_portfolio_service import get_or_create_primary

    count = 0
    portfolio = get_or_create_primary(session)
    for pos in portfolio.positions or []:
        instrument = session.get(Instrument, pos.instrument_id)
        if instrument is None or (instrument.asset_class or "").lower() != "bond":
            continue
        enqueue_fi_kinds(session, int(instrument.id), EnrichmentPriority.P0_PORTFOLIO)
        count += 1

    # Shadow positions if table exists.
    try:
        rows = session.execute(
            text(
                """
                SELECT DISTINCT sp.instrument_id
                FROM shadow.positions sp
                JOIN market.instruments i ON i.id = sp.instrument_id
                WHERE lower(i.asset_class) = 'bond'
                """
            )
        ).all()
        for (iid,) in rows:
            enqueue_fi_kinds(session, int(iid), EnrichmentPriority.P0_PORTFOLIO)
            count += 1
    except Exception:  # noqa: BLE001
        pass

    return {"enqueued_positions": count}


def try_acquire_enrichment_lock(token: str, *, ttl: int = LOCK_TTL_SECONDS) -> bool:
    try:
        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=False)
        return bool(client.set(LOCK_KEY, token.encode(), nx=True, ex=ttl))
    except Exception as exc:  # noqa: BLE001
        logger.warning("fi_enrichment_lock_unavailable", extra={"error": str(exc)})
        return True  # fail-open for single-worker local; batch still bounded


def release_enrichment_lock(token: str) -> None:
    try:
        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=False)
        current = client.get(LOCK_KEY)
        if current == token.encode():
            client.delete(LOCK_KEY)
    except Exception:  # noqa: BLE001
        pass


def claim_enrichment_batch(session: Session, *, batch_size: int) -> list[InstrumentEnrichmentJob]:
    now = datetime.now(UTC)
    rows = list(
        session.scalars(
            select(InstrumentEnrichmentJob)
            .where(
                InstrumentEnrichmentJob.kind.in_([k.value for k in FI_KINDS]),
                InstrumentEnrichmentJob.status.in_(
                    [
                        EnrichmentStatus.PENDING.value,
                        EnrichmentStatus.FAILED.value,
                    ]
                ),
                or_(
                    InstrumentEnrichmentJob.next_retry_at.is_(None),
                    InstrumentEnrichmentJob.next_retry_at <= now,
                ),
            )
            .order_by(
                InstrumentEnrichmentJob.priority.asc(),
                InstrumentEnrichmentJob.next_retry_at.asc().nullsfirst(),
                InstrumentEnrichmentJob.id.asc(),
            )
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    for job in rows:
        job.status = EnrichmentStatus.RUNNING.value
        job.last_attempted_at = now
        job.attempts = int(job.attempts or 0) + 1
        job.updated_at = now
    session.flush()
    return rows


def enrich_single_bond(
    session: Session,
    instrument: Instrument,
    *,
    client: MoexBondClient,
    kinds: set[str] | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Fetch MOEX board + bondization and upsert terms/cashflows/market.

    On source failure: raise — caller marks FAILED and keeps existing good terms.
    Empty bondization with existing good terms → PARTIAL/NO_DATA without wipe.
    """
    as_of = as_of or date.today()
    kinds = kinds or {k.value for k in FI_KINDS}
    secid = instrument.symbol
    board = instrument.primary_board or _resolve_board(session, instrument)

    board_row = _fetch_board_row(client, secid, board)
    face = resolve_nominal_currency(
        face_unit=board_row.get("FACEUNIT") if board_row else None,
        currency_id=board_row.get("CURRENCYID") if board_row else None,
    )
    result: dict[str, Any] = {
        "instrument_id": instrument.id,
        "symbol": secid,
        "board": board,
        "kinds": sorted(kinds),
        "status": EnrichmentStatus.SUCCESS.value,
    }

    had_term = session.scalar(select(BondTerm).where(BondTerm.instrument_id == instrument.id))

    bondization = client.fetch_bondization(secid)
    schedule = parse_bondization_schedule(
        coupons=bondization.get("coupons") or [],
        amortizations=bondization.get("amortizations") or [],
        offers=bondization.get("offers") or [],
    )
    empty_schedule = not (schedule.coupons or schedule.amortizations or schedule.offers)

    if empty_schedule and had_term is not None and EnrichmentKind.FIXED_INCOME_TERMS.value in kinds:
        # Never wipe good terms with empty source response.
        result["status"] = EnrichmentStatus.PARTIAL.value
        result["preserved_terms"] = True
        result["note"] = "empty_bondization_preserved_existing_terms"
        if EnrichmentKind.FIXED_INCOME_MARKET.value in kinds and board_row:
            _upsert_market_snapshot(session, instrument, board_row, as_of=as_of)
            result["market"] = "updated"
        return result

    if empty_schedule and had_term is None:
        result["status"] = EnrichmentStatus.NO_DATA.value
        result["note"] = "empty_bondization_no_prior_terms"
        return result

    if not board_row and had_term is None:
        result["status"] = EnrichmentStatus.NO_DATA.value
        result["note"] = "no_board_row"
        return result

    row = board_row or {}
    nominal = _decimal(row.get("FACEVALUE")) or (had_term.nominal if had_term else None)
    maturity = _date(row.get("MATDATE")) or (had_term.maturity_date if had_term else None)
    lot_size = (
        int(row["LOTSIZE"])
        if row.get("LOTSIZE") not in (None, "")
        else (int(had_term.lot_size) if had_term and had_term.lot_size is not None else None)
    )
    clean = _decimal(row.get("PREVPRICE") or row.get("PRICE") or row.get("LCURRENTPRICE"))
    nkd = _decimal(row.get("ACCRUEDINT"))
    ytm = _decimal(row.get("YIELD"))
    duration = _decimal(row.get("DURATION"))
    support, reasons = classify_bond_support_v1(
        face_unit=row.get("FACEUNIT"),
        currency_id=row.get("CURRENCYID"),
        nominal=float(nominal) if nominal is not None else None,
        lot_size=lot_size,
        maturity_date=maturity,
        schedule=schedule,
        market_price_percent=float(clean) if clean is not None else None,
        as_of=as_of,
    )
    coupon_type = "FIXED" if coupon_structure_fixed(schedule, as_of=as_of) else None
    bond_type = _bond_type(board or "", secid)
    next_coupon = remaining_coupons(schedule, as_of)
    next_c = next_coupon[0] if next_coupon else None
    raw_fields = {
        "FACEUNIT": row.get("FACEUNIT"),
        "CURRENCYID": row.get("CURRENCYID"),
        "FACEVALUE": row.get("FACEVALUE"),
        "MATDATE": row.get("MATDATE"),
        "OFFERDATE": row.get("OFFERDATE"),
        "COUPONPERCENT": row.get("COUPONPERCENT"),
        "COUPONVALUE": row.get("COUPONVALUE"),
        "LOTSIZE": row.get("LOTSIZE"),
        "BOARDID": row.get("BOARDID") or board,
        "canonical_nominal_currency": face.canonical if face else (had_term.currency if had_term else None),
        "currency_raw_faceunit": face.raw_value if face else None,
        "support_reasons": reasons,
        "bondization_known_at_quality": MOEX_BONDIZATION_KNOWN_AT_QUALITY.value,
        "coupon_count": len(schedule.coupons),
        "amortization_count": len(schedule.amortizations),
        "offer_count": len(schedule.offers),
        "future_offer_count": len(future_offers(schedule, as_of)),
        "complex_amortization": has_complex_amortization(schedule),
        "next_coupon_date": next_c.coupon_date.isoformat() if next_c else None,
        "next_coupon_amount": float(next_c.amount) if next_c and next_c.amount is not None else None,
        "duration": float(duration) if duration is not None else None,
        "moex_yield": float(ytm) if ytm is not None else None,
        "accounting_support": support.value == "SUPPORTED",
    }

    if EnrichmentKind.FIXED_INCOME_TERMS.value in kinds:
        currency = face.canonical if face and face.canonical != "UNKNOWN" else (
            had_term.currency if had_term else "RUB"
        )
        if had_term is None:
            session.add(
                BondTerm(
                    instrument_id=instrument.id,
                    bond_type=bond_type.value,
                    nominal=nominal,
                    currency=currency,
                    coupon_type=coupon_type,
                    coupon_rate=_decimal(row.get("COUPONPERCENT"))
                    or (next_c.rate_percent if next_c else None),
                    maturity_date=maturity,
                    lot_size=lot_size,
                    support_status=support.value,
                    credit_quality_status=CreditQualityStatus.UNKNOWN.value,
                    known_at=as_of,
                    source=SOURCE_BONDIZATION,
                    raw_fields=raw_fields,
                )
            )
            result["terms"] = "inserted"
        else:
            had_term.bond_type = bond_type.value
            if nominal is not None:
                had_term.nominal = nominal
            if currency:
                had_term.currency = currency
            had_term.coupon_type = coupon_type
            rate = _decimal(row.get("COUPONPERCENT")) or (next_c.rate_percent if next_c else None)
            if rate is not None:
                had_term.coupon_rate = rate
            if maturity is not None:
                had_term.maturity_date = maturity
            if lot_size is not None:
                had_term.lot_size = lot_size
            had_term.support_status = support.value
            had_term.raw_fields = {**(had_term.raw_fields or {}), **raw_fields}
            had_term.known_at = as_of
            had_term.source = SOURCE_BONDIZATION
            result["terms"] = "updated"
        if face and face.canonical and face.canonical != "UNKNOWN":
            instrument.currency = face.canonical
        session.flush()

    if EnrichmentKind.FIXED_INCOME_CASHFLOWS.value in kinds:
        currency = face.canonical if face else (instrument.currency or "RUB")
        cf_added = _persist_schedule_cashflows(
            session,
            instrument_id=instrument.id,
            schedule=schedule,
            face_currency=currency,
            known_at=as_of,
            maturity=maturity,
            nominal=nominal,
        )
        result["cashflows"] = cf_added

    if EnrichmentKind.FIXED_INCOME_MARKET.value in kinds and board_row:
        _upsert_market_snapshot(session, instrument, board_row, as_of=as_of, clean=clean, nkd=nkd, ytm=ytm)
        result["market"] = "updated"

    # Refresh support_level / capabilities side-effects via bond term presence.
    _refresh_bond_support_level(session, instrument)
    session.flush()
    return result


def _refresh_bond_support_level(session: Session, instrument: Instrument) -> None:
    term = session.scalar(select(BondTerm).where(BondTerm.instrument_id == instrument.id))
    if term is None:
        return
    # Keep master classification; bump PARTIAL→FULL-ish only via support_status note in raw.
    if instrument.support_level in (None, "", "CATALOG_ONLY") and term.support_status == "SUPPORTED":
        instrument.support_level = "PARTIAL"
    instrument.updated_at = datetime.now(UTC)


def _resolve_board(session: Session, instrument: Instrument) -> str | None:
    src = session.scalar(
        select(InstrumentSource)
        .where(
            InstrumentSource.instrument_id == instrument.id,
            InstrumentSource.valid_to.is_(None),
        )
        .limit(1)
    )
    return src.board if src else instrument.primary_board


def _fetch_board_row(client: MoexBondClient, secid: str, board: str | None) -> dict[str, Any] | None:
    boards = [board] if board else ["TQOB", "TQCB"]
    for b in boards:
        if not b:
            continue
        rows = client.fetch_board_rows(b, limit=100)
        for row in rows:
            if str(row.get("SECID") or "").upper() == secid.upper():
                return {**row, "_board": b}
    # Fallback: scan both boards more deeply
    for b in ("TQOB", "TQCB"):
        rows = client.fetch_board_rows(b, limit=100)
        for row in rows:
            if str(row.get("SECID") or "").upper() == secid.upper():
                return {**row, "_board": b}
    return None


def _upsert_market_snapshot(
    session: Session,
    instrument: Instrument,
    row: dict[str, Any],
    *,
    as_of: date,
    clean: Decimal | None = None,
    nkd: Decimal | None = None,
    ytm: Decimal | None = None,
) -> None:
    clean = clean if clean is not None else _decimal(
        row.get("PREVPRICE") or row.get("PRICE") or row.get("LCURRENTPRICE")
    )
    nkd = nkd if nkd is not None else _decimal(row.get("ACCRUEDINT"))
    ytm = ytm if ytm is not None else _decimal(row.get("YIELD"))
    existing = session.scalar(
        select(BondMarketSnapshot).where(
            BondMarketSnapshot.instrument_id == instrument.id,
            BondMarketSnapshot.as_of == as_of,
            BondMarketSnapshot.source == SOURCE_BOARD,
        )
    )
    observed = {
        k: row.get(k)
        for k in (
            "PREVPRICE",
            "ACCRUEDINT",
            "YIELD",
            "DURATION",
            "LOTSIZE",
            "FACEUNIT",
            "CURRENCYID",
            "VALTODAY",
            "NUMTRADES",
        )
        if k in row
    }
    if existing is None:
        session.add(
            BondMarketSnapshot(
                instrument_id=instrument.id,
                as_of=as_of,
                clean_price_percent=clean,
                accrued_interest=nkd,
                yield_value=ytm,
                source=SOURCE_BOARD,
                observed_fields=observed,
            )
        )
    else:
        if clean is not None:
            existing.clean_price_percent = clean
        if nkd is not None:
            existing.accrued_interest = nkd
        if ytm is not None:
            existing.yield_value = ytm
        existing.observed_fields = {**(existing.observed_fields or {}), **observed}


def run_fi_enrichment_batch(session: Session, *, acquire_lock: bool = True) -> dict[str, Any]:
    settings = get_settings()
    if not settings.fi_enrichment_enabled:
        return {"status": "DISABLED", "reason": "FI_ENRICHMENT_ENABLED=false"}

    token = uuid.uuid4().hex
    if acquire_lock and not try_acquire_enrichment_lock(token):
        return {"status": "SKIPPED_LOCK", "errors": ["lock_held"]}

    batch_size = max(1, min(int(settings.fi_enrichment_batch_size), 100))
    pacing_ms = max(0, int(settings.fi_enrichment_pacing_ms))
    started = datetime.now(UTC)
    processed = 0
    success = 0
    failed = 0
    partial = 0
    no_data = 0
    details: list[dict[str, Any]] = []

    try:
        jobs = claim_enrichment_batch(session, batch_size=batch_size)
        if not jobs:
            return {
                "status": "EMPTY",
                "processed": 0,
                "started_at": started.isoformat(),
            }

        # Group by instrument so one MOEX round-trip covers all kinds.
        by_iid: dict[int, list[InstrumentEnrichmentJob]] = {}
        for job in jobs:
            by_iid.setdefault(int(job.instrument_id), []).append(job)

        client = MoexBondClient(auto_close=False)
        try:
            for iid, job_list in by_iid.items():
                instrument = session.get(Instrument, iid)
                now = datetime.now(UTC)
                if instrument is None:
                    for job in job_list:
                        job.status = EnrichmentStatus.FAILED.value
                        job.last_error = "instrument_missing"
                        job.updated_at = now
                        failed += 1
                        processed += 1
                    continue
                kinds = {j.kind for j in job_list}
                try:
                    result = enrich_single_bond(
                        session, instrument, client=client, kinds=kinds
                    )
                    status = result.get("status") or EnrichmentStatus.SUCCESS.value
                    for job in job_list:
                        job.status = status
                        job.last_error = result.get("note") if status != EnrichmentStatus.SUCCESS.value else None
                        if status == EnrichmentStatus.SUCCESS.value:
                            job.last_success_at = now
                        elif status == EnrichmentStatus.PARTIAL.value:
                            job.last_success_at = now
                        job.updated_at = now
                        processed += 1
                        if status == EnrichmentStatus.SUCCESS.value:
                            success += 1
                        elif status == EnrichmentStatus.PARTIAL.value:
                            partial += 1
                        elif status == EnrichmentStatus.NO_DATA.value:
                            no_data += 1
                        else:
                            failed += 1
                    details.append(result)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "fi_enrichment_instrument_failed",
                        extra={"instrument_id": iid, "error": str(exc)},
                    )
                    for job in job_list:
                        job.status = EnrichmentStatus.FAILED.value
                        job.last_error = str(exc)[:500]
                        job.next_retry_at = now + timedelta(minutes=min(60, 5 * int(job.attempts or 1)))
                        job.updated_at = now
                        failed += 1
                        processed += 1
                if pacing_ms:
                    time.sleep(pacing_ms / 1000.0)
                session.flush()
        finally:
            client.close()

        session.flush()
        return {
            "status": "SUCCESS",
            "processed": processed,
            "success": success,
            "partial": partial,
            "failed": failed,
            "no_data": no_data,
            "batch_size": batch_size,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "details": details[:20],
        }
    finally:
        if acquire_lock:
            release_enrichment_lock(token)


def fi_coverage_report(session: Session) -> dict[str, Any]:
    from app.modules.market.application.research_universe import (
        RESEARCH_FI_V1,
        research_fi_member_ids,
        seed_research_fi_membership,
    )

    seed_research_fi_membership(session, only_if_empty=True)
    pinned = research_fi_member_ids(session)

    bonds_total = int(
        session.scalar(
            select(func.count()).select_from(Instrument).where(Instrument.asset_class == "bond")
        )
        or 0
    )
    terms_total = int(session.scalar(select(func.count()).select_from(BondTerm)) or 0)
    cf_instruments = int(
        session.scalar(select(func.count(func.distinct(BondCashflow.instrument_id)))) or 0
    )
    market_instruments = int(
        session.scalar(select(func.count(func.distinct(BondMarketSnapshot.instrument_id)))) or 0
    )

    job_counts: dict[str, int] = {}
    try:
        rows = session.execute(
            select(InstrumentEnrichmentJob.status, func.count())
            .where(InstrumentEnrichmentJob.kind.in_([k.value for k in FI_KINDS]))
            .group_by(InstrumentEnrichmentJob.status)
        ).all()
        job_counts = {str(s): int(c) for s, c in rows}
    except Exception:  # noqa: BLE001
        job_counts = {}

    pending = int(job_counts.get(EnrichmentStatus.PENDING.value, 0))
    return {
        "as_of": date.today().isoformat(),
        "generated_at": datetime.now(UTC).isoformat(),
        "bonds_in_master": bonds_total,
        "bond_terms": terms_total,
        "instruments_with_cashflows": cf_instruments,
        "instruments_with_market_snapshots": market_instruments,
        "research_fi_v1": {
            "universe_code": RESEARCH_FI_V1,
            "pinned_count": len(pinned),
            "note": (
                "Candidate / Opportunity FI pool is pinned. "
                "Enrichment expands catalog valuation without growing this set."
            ),
        },
        "enrichment_jobs": job_counts,
        "pending_jobs": pending,
        "fi_enrichment_enabled": bool(get_settings().fi_enrichment_enabled),
        "known_at_quality": MOEX_BONDIZATION_KNOWN_AT_QUALITY.value,
    }


def write_fi_coverage_artifact(session: Session, path: Path | None = None) -> Path:
    import json

    report = fi_coverage_report(session)
    root = Path(__file__).resolve().parents[5]
    target = path or (root / ".tmp" / "fixed-income-dividend-enrichment-v2" / "fi-coverage.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def maybe_startup_fi_enrichment_p0(session: Session) -> dict[str, Any]:
    settings = get_settings()
    if not settings.fi_enrichment_enabled or not settings.fi_enrichment_startup_p0:
        return {"status": "DISABLED"}
    enq = enqueue_p0_portfolio_positions(session)
    try:
        from app.worker import tasks as worker_tasks

        async_result = worker_tasks.enrich_fixed_income_instruments.delay()
        return {
            "status": "SCHEDULED",
            "task_id": getattr(async_result, "id", None),
            **enq,
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "ENQUEUED_ONLY", "error": str(exc), **enq}
