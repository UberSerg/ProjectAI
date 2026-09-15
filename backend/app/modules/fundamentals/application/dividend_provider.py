"""Dividend provider port — readiness without inventing data.

MOEX ISS dividend endpoints remain REJECTED (description / candles, not dividend tables).
Bounded production-capable path: ``ISSUER_IR_XLS_V1`` for configured IR issuers
(MGNT + LKOH catalog). Other symbols stay empty / not ready.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.fundamentals.domain.total_return import (
    DividendCashPoint,
    compute_gross_total_return,
)
from app.modules.fundamentals.domain.types import SOURCE_ISSUER_IR_XLS_V1


@dataclass(frozen=True, slots=True)
class DividendProviderRecord:
    """Normalized dividend observation from an accepted provider (future)."""

    symbol: str
    ex_date: date
    amount_per_share: float | None
    currency: str | None = None
    known_at: date | None = None
    record_date: date | None = None
    source: str | None = None
    external_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class DividendProvider(Protocol):
    """Port for a lawful, audited dividend history source."""

    name: str

    def fetch_dividends(self, symbol: str) -> Sequence[DividendProviderRecord]:
        ...

    def readiness(self) -> dict[str, Any]:
        ...


class NotReadyDividendProvider:
    """Default provider — documents why ingest is blocked."""

    name = "NOT_READY"

    def __init__(self, *, reasons: Sequence[str] | None = None) -> None:
        self._reasons = list(
            reasons
            or (
                "moex_iss_securities_dividends_rejected",
                "moex_iss_history_dividends_rejected",
                "no_accepted_public_provider_in_env",
            )
        )

    def fetch_dividends(self, symbol: str) -> Sequence[DividendProviderRecord]:
        return ()

    def readiness(self) -> dict[str, Any]:
        return {
            "status": "NOT_READY",
            "provider": self.name,
            "accepted": False,
            "reasons": list(self._reasons),
            "notes": [
                "MOEX ISS /iss/securities/{SECID}/dividends.json returns security description, not dividends.",
                "MOEX ISS history/.../dividends returns candle history, not dividend records.",
                "Do not invent ex-dates or amounts. Dataset/features must not gain dividends.",
            ],
            "as_of": date.today().isoformat(),
        }


class CompositeDividendProvider:
    """Try issuer IR XLS for configured SECIDs; empty for everyone else."""

    name = "COMPOSITE_ISSUER_IR_V2"

    def __init__(
        self,
        *,
        ir_provider: Any,
        fallback: NotReadyDividendProvider | None = None,
    ) -> None:
        self._ir = ir_provider
        self._fallback = fallback or NotReadyDividendProvider(
            reasons=(
                "symbol_not_in_issuer_ir_xlsx_catalog",
                "moex_iss_dividends_rejected",
            )
        )

    def fetch_dividends(self, symbol: str) -> Sequence[DividendProviderRecord]:
        secid = (symbol or "").strip().upper()
        if not secid or secid not in self._ir.configured_secids():
            return ()
        refs = self._ir.fetch_by_secid(secid)
        out: list[DividendProviderRecord] = []
        for ref in refs:
            # Application record requires ex_date; IR V1 leaves ex_date null —
            # surface via record_date placeholder only when present; do not invent.
            if ref.ex_date is None and ref.record_date is None:
                continue
            out.append(
                DividendProviderRecord(
                    symbol=secid,
                    ex_date=ref.ex_date or ref.record_date,  # type: ignore[arg-type]
                    amount_per_share=ref.amount_per_share,
                    currency=ref.currency,
                    known_at=ref.known_at,
                    record_date=ref.record_date,
                    source=ref.source,
                    external_id=(ref.metadata or {}).get("period_key"),
                    raw={
                        "status": str(ref.status),
                        "board_recommendation_date": (
                            ref.board_recommendation_date.isoformat()
                            if ref.board_recommendation_date
                            else None
                        ),
                        "shareholder_approval_date": (
                            ref.shareholder_approval_date.isoformat()
                            if ref.shareholder_approval_date
                            else None
                        ),
                        "ex_date_present": ref.ex_date is not None,
                        "metadata": dict(ref.metadata or {}),
                    },
                )
            )
        return out

    def readiness(self) -> dict[str, Any]:
        ir_ready = self._ir.readiness()
        return {
            **ir_ready,
            "provider": self.name,
            "ir_provider": ir_ready.get("provider") or SOURCE_ISSUER_IR_XLS_V1,
            "fallback_provider": self._fallback.name,
            "universe_wide": False,
        }


def build_issuer_ir_dividend_provider(
    *,
    issuer_id_by_secid: dict[str, int] | None = None,
    instrument_id_by_secid: dict[str, int] | None = None,
    local_files: dict[str, tuple[Any, Any]] | None = None,
) -> Any:
    from app.modules.fundamentals.infrastructure.issuer_ir_xlsx_dividend_provider import (
        IssuerIrXlsxDividendProvider,
    )

    return IssuerIrXlsxDividendProvider(
        issuer_id_by_secid=issuer_id_by_secid or {},
        instrument_id_by_secid=instrument_id_by_secid or {},
        local_files=local_files or {},
    )


def get_dividend_provider() -> DividendProvider:
    """Resolve provider: Composite IR XLS (MGNT) when sync enabled.

    ``DIVIDEND_SYNC_ENABLED=false`` keeps a NOT_READY gate for automated sync
    workers; readiness notes that IR XLSX is available when sync is on.
    """
    from app.core.config import get_settings

    settings = get_settings()
    ir = build_issuer_ir_dividend_provider()
    if not settings.dividend_sync_enabled:
        return NotReadyDividendProvider(
            reasons=(
                "DIVIDEND_SYNC_ENABLED=false",
                "moex_iss_dividends_rejected",
                "issuer_ir_xlsx_v1_available_when_sync_enabled",
            )
        )
    return CompositeDividendProvider(ir_provider=ir)


def get_ports_dividend_provider(
    *,
    issuer_id_by_secid: dict[str, int] | None = None,
    instrument_id_by_secid: dict[str, int] | None = None,
    local_files: dict[str, tuple[Any, Any]] | None = None,
) -> Any:
    """Ports.DividendProvider for ingest (issuer-id keyed)."""
    return build_issuer_ir_dividend_provider(
        issuer_id_by_secid=issuer_id_by_secid,
        instrument_id_by_secid=instrument_id_by_secid,
        local_files=local_files,
    )


def dividend_coverage_v2(session: Session) -> dict[str, Any]:
    from app.infrastructure.market.models import Candle, Instrument
    from app.modules.fundamentals.application.total_return import build_dividend_coverage_report

    provider = get_dividend_provider()
    provider_ready = provider.readiness()
    base = build_dividend_coverage_report(session)
    payload = base.to_dict()
    payload["provider"] = provider_ready
    payload["verdict"] = "NOT_READY" if not provider_ready.get("accepted") else payload.get("quality")
    payload["ingest_enabled"] = bool(provider_ready.get("accepted"))
    payload["dataset_mutation"] = False
    eq_with_candles = int(
        session.scalar(
            select(func.count(func.distinct(Candle.instrument_id)))
            .select_from(Candle)
            .join(Instrument, Instrument.id == Candle.instrument_id)
            .where(Instrument.asset_class == "equity", Candle.timeframe == "1d")
        )
        or 0
    )
    payload["instruments_with_price_history"] = max(
        int(payload.get("instruments_with_price_history") or 0),
        eq_with_candles,
    )
    payload["generated_at"] = datetime.now(UTC).isoformat()
    return payload


def total_return_readiness_report(session: Session) -> dict[str, Any]:
    """Richer total-return readiness for artifact + API."""
    from app.modules.fundamentals.application.total_return import build_dividend_coverage_report
    from app.modules.fundamentals.infrastructure.models import DividendEvent

    cov = build_dividend_coverage_report(session)
    provider = get_dividend_provider().readiness()
    events = int(session.scalar(select(func.count()).select_from(DividendEvent)) or 0)

    sample_tr = None
    if events > 0:
        row = session.execute(
            select(DividendEvent).where(DividendEvent.amount_per_share.is_not(None)).limit(5)
        ).scalars().all()
        points = [
            DividendCashPoint(
                ex_date=r.ex_date,
                amount_per_share=float(r.amount_per_share) if r.amount_per_share is not None else None,
                currency=r.currency,
                known_at=r.known_at if isinstance(r.known_at, date) else None,
                status=r.status,
            )
            for r in row
            if getattr(r, "ex_date", None) is not None
        ]
        if points:
            sample_tr = compute_gross_total_return(
                start_date=date(2025, 1, 1),
                end_date=date(2026, 1, 1),
                start_price=100.0,
                end_price=100.0,
                dividends=points,
            ).to_dict()

    return {
        "quality": cov.quality.value,
        "verdict": "NOT_READY" if not provider.get("accepted") and events == 0 else cov.quality.value,
        "provider": provider,
        "dividend_coverage": cov.to_dict(),
        "dividend_events_stored": events,
        "sample_total_return_with_stored_events": sample_tr,
        "compute_gross_total_return_wired": True,
        "dataset_mutation": False,
        "training": False,
        "generated_at": datetime.now(UTC).isoformat(),
        "notes": [
            "compute_gross_total_return accepts real DividendEvent rows when present.",
            "Empty store → price-only / NOT_READY coverage; no fabricated dividends.",
            "ISSUER_IR_XLS_V1 is PARTIAL_RESEARCH_PRODUCTION_BOUNDED (MGNT).",
        ],
    }


def write_total_return_readiness_artifact(session: Session, path=None):
    import json
    from pathlib import Path

    report = total_return_readiness_report(session)
    root = Path(__file__).resolve().parents[5]
    target = path or (root / ".tmp" / "fixed-income-dividend-enrichment-v2" / "total-return-readiness.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def load_dividend_cash_points(
    session: Session,
    *,
    instrument_id: int,
    start_date: date,
    end_date: date,
    strict_known_at: bool = False,
) -> list[DividendCashPoint]:
    """Load real DividendEvent rows for total-return computation (empty OK).

    When ``strict_known_at`` is True, drop events whose metadata marks approximate /
    record-date / meeting-date proxies — Dataset V3 gate should prefer this mode.
    """
    from app.modules.fundamentals.infrastructure.models import DividendEvent

    rows = session.scalars(
        select(DividendEvent).where(
            DividendEvent.instrument_id == instrument_id,
            DividendEvent.ex_date > start_date,
            DividendEvent.ex_date <= end_date,
            DividendEvent.status == "APPROVED",
        )
    ).all()
    approx_markers = {
        "APPROXIMATE_PUBLICATION_PROXY",
        "MEETING_DATE_PROXY",
        "RECORD_DATE_PROXY",
        "UNKNOWN",
    }
    out: list[DividendCashPoint] = []
    for r in rows:
        if r.ex_date is None:
            continue
        meta = dict(getattr(r, "metadata_", None) or {})
        quality = str(meta.get("known_at_quality") or "")
        if strict_known_at and quality in approx_markers:
            continue
        out.append(
            DividendCashPoint(
                ex_date=r.ex_date,
                amount_per_share=float(r.amount_per_share) if r.amount_per_share is not None else None,
                currency=getattr(r, "currency", None),
                known_at=r.known_at if isinstance(getattr(r, "known_at", None), date) else None,
                status=getattr(r, "status", None),
            )
        )
    return out


def compute_instrument_gross_total_return(
    session: Session,
    *,
    instrument_id: int,
    start_date: date,
    end_date: date,
    start_price: float | None,
    end_price: float | None,
    strict_known_at: bool = False,
) -> dict[str, Any]:
    dividends = load_dividend_cash_points(
        session,
        instrument_id=instrument_id,
        start_date=start_date,
        end_date=end_date,
        strict_known_at=strict_known_at,
    )
    result = compute_gross_total_return(
        start_date=start_date,
        end_date=end_date,
        start_price=start_price,
        end_price=end_price,
        dividends=dividends,
    )
    payload = result.to_dict()
    payload["dividends_loaded_from_db"] = len(dividends)
    payload["strict_known_at"] = strict_known_at
    return payload


def resolve_ir_catalog_bindings(session: Session) -> dict[str, Any]:
    """Map catalog SECIDs → instrument_id + issuer_id via current MOEX sources + mappings."""
    from app.infrastructure.market.models import Instrument, InstrumentSource
    from app.modules.fundamentals.infrastructure.issuer_ir_xlsx_dividend_provider import (
        DEFAULT_ISSUER_IR_CATALOG,
    )
    from app.modules.fundamentals.infrastructure.models import SecurityIssuerMapping
    from app.modules.market.application.identity import SOURCE_MOEX

    catalog_secids = {s.secid.upper() for s in DEFAULT_ISSUER_IR_CATALOG}
    instrument_id_by_secid: dict[str, int] = {}
    issuer_id_by_secid: dict[str, int] = {}
    unresolved: list[str] = []

    sources = session.scalars(
        select(InstrumentSource).where(
            InstrumentSource.source.in_((SOURCE_MOEX, "MOEX_ISS", "MOEX")),
            InstrumentSource.valid_to.is_(None),
            InstrumentSource.external_id.in_(sorted(catalog_secids)),
        )
    )
    for src in sources:
        secid = str(src.external_id or "").upper()
        if secid not in catalog_secids:
            continue
        instrument_id_by_secid[secid] = int(src.instrument_id)

    for secid, iid in list(instrument_id_by_secid.items()):
        mapping = session.scalar(
            select(SecurityIssuerMapping).where(
                SecurityIssuerMapping.instrument_id == iid,
                SecurityIssuerMapping.mapping_status == "MAPPED",
                SecurityIssuerMapping.issuer_id.is_not(None),
            )
        )
        if mapping is not None and mapping.issuer_id is not None:
            issuer_id_by_secid[secid] = int(mapping.issuer_id)
        else:
            # Fallback: use instrument_id as synthetic issuer binding only if issuer missing —
            # DividendEvent.issuer_id is nullable, so leave unset.
            pass

    for secid in catalog_secids:
        if secid not in instrument_id_by_secid:
            # Symbol-level fallback for research cohort without source row.
            inst = session.scalar(
                select(Instrument).where(
                    Instrument.symbol == secid,
                    Instrument.asset_class == "equity",
                )
            )
            if inst is not None:
                instrument_id_by_secid[secid] = int(inst.id)
            else:
                unresolved.append(secid)

    return {
        "instrument_id_by_secid": instrument_id_by_secid,
        "issuer_id_by_secid": issuer_id_by_secid,
        "unresolved_secids": unresolved,
        "catalog_secids": sorted(catalog_secids),
    }


def sync_issuer_ir_dividends(session: Session) -> dict[str, Any]:
    """Resolve catalog bindings and ingest via ports provider (idempotent)."""
    from app.modules.fundamentals.application.ingest_dividends import (
        DividendIngestResult,
        _existing_version,
    )
    from app.modules.fundamentals.application.runs import finish_run, start_run
    from app.modules.fundamentals.config import PROVIDER_DIVIDENDS
    from app.modules.fundamentals.domain.types import DeferralReason, IngestionStatus
    from app.modules.fundamentals.infrastructure.issuer_ir_xlsx_dividend_provider import (
        DEFAULT_ISSUER_IR_CATALOG,
    )
    from app.modules.fundamentals.infrastructure.models import DividendEvent

    bindings = resolve_ir_catalog_bindings(session)
    instrument_map = bindings["instrument_id_by_secid"]
    issuer_map = bindings["issuer_id_by_secid"]
    if not instrument_map:
        return {
            "status": "NOT_READY",
            "reason": "no_catalog_instruments_resolved",
            "bindings": bindings,
            "ingested": 0,
        }

    provider = build_issuer_ir_dividend_provider(
        issuer_id_by_secid=issuer_map,
        instrument_id_by_secid=instrument_map,
    )
    result = DividendIngestResult()
    run = start_run(session, PROVIDER_DIVIDENDS, requested_range="issuer_ir_xlsx_catalog")
    result.run_id = run.id

    for secid in sorted(instrument_map):
        for event in provider.fetch_by_secid(secid):
            result.events_received += 1
            if getattr(event, "known_at", None) is None:
                result.events_skipped += 1
                result.rejections.append(f"{DeferralReason.MISSING_KNOWN_AT.value}: {secid}")
                continue
            if _existing_version(session, event) is not None:
                result.events_skipped += 1
                continue
            session.add(
                DividendEvent(
                    issuer_id=event.issuer_id,
                    instrument_id=event.instrument_id,
                    announcement_date=event.announcement_date,
                    known_at=event.known_at,
                    board_recommendation_date=event.board_recommendation_date,
                    shareholder_approval_date=event.shareholder_approval_date,
                    record_date=event.record_date,
                    ex_date=event.ex_date,
                    payment_date=event.payment_date,
                    amount_per_share=event.amount_per_share,
                    currency=event.currency,
                    status=event.status.value,
                    source=event.source,
                    version=event.version,
                    supersedes_id=event.supersedes_id,
                    metadata_=dict(getattr(event, "metadata", None) or {}),
                )
            )
            session.flush()
            result.events_inserted += 1

    if result.events_inserted:
        status = IngestionStatus.PARTIAL if result.rejections else IngestionStatus.SUCCESS
    else:
        status = IngestionStatus.NO_CHANGES
    result.status = status.value
    finish_run(session, run, status=status, summary=result.to_dict())
    payload = result.to_dict()
    payload["bindings"] = bindings
    payload["catalog"] = [s.secid for s in DEFAULT_ISSUER_IR_CATALOG]
    return payload
