"""Session-backed industrial FundamentalSnapshotV1 builder (reuses fundamentals PIT)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.market.models import Instrument
from app.modules.fundamentals.application import pit
from app.modules.fundamentals.domain import pit_rules
from app.modules.fundamentals.domain.types import (
    FactRef,
    ReportingStandard,
    ReportRef,
)
from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import (
    BANK_FI_SECIDS,
    SUPPORT_BANK,
)
from app.modules.fundamentals.infrastructure.models import (
    Issuer,
    SecurityIssuerMapping,
    fundamentals_schema_ready,
)
from app.modules.intelligence.contracts.snapshots_domain import FundamentalSnapshotV1
from app.modules.intelligence.fundamentals.constants import (
    ISSUER_KIND_BANK_FI,
    ISSUER_KIND_INDUSTRIAL,
    ISSUER_KIND_UNKNOWN,
    LIMITATION_BANK_FI,
    PROVIDER,
    SNAPSHOT_BUILDER,
    STATUS_NOT_AVAILABLE,
    STATUS_UNKNOWN,
)
from app.modules.intelligence.fundamentals.peers import compute_peer_ranks
from app.modules.intelligence.fundamentals.persistence import persist_fundamental_snapshot
from app.modules.intelligence.fundamentals.profile import (
    PriorPeriodFacts,
    build_industrial_profile,
    facts_used_payload,
    normalized_fact_map,
    select_comparable_prior,
)


def _issuer_fns_meta(issuer: Issuer | None) -> dict[str, Any]:
    if issuer is None:
        return {}
    meta = issuer.metadata_ if isinstance(issuer.metadata_, dict) else {}
    fns = meta.get("fns")
    return fns if isinstance(fns, dict) else {}


def _symbol_for_instrument(session: Session, instrument_id: int) -> str | None:
    row = session.get(Instrument, instrument_id)
    return row.symbol.upper() if row and row.symbol else None


def _mapping_secid(session: Session, instrument_id: int) -> str | None:
    row = session.scalar(
        select(SecurityIssuerMapping)
        .where(
            SecurityIssuerMapping.instrument_id == instrument_id,
            SecurityIssuerMapping.mapping_status == "MAPPED",
        )
        .limit(1)
    )
    if row is None:
        return None
    if row.external_secid:
        return str(row.external_secid).upper()
    return _symbol_for_instrument(session, instrument_id)


def resolve_issuer_kind(
    session: Session,
    instrument_id: int,
    issuer: Issuer | None,
) -> tuple[str, tuple[str, ...]]:
    """BANK_FI when ticker or FNS support_status says so — never apply industrial ratios."""
    secid = _mapping_secid(session, instrument_id)
    fns = _issuer_fns_meta(issuer)
    if (secid and secid in BANK_FI_SECIDS) or fns.get("support_status") == SUPPORT_BANK:
        return ISSUER_KIND_BANK_FI, (LIMITATION_BANK_FI,)
    if issuer is None:
        return ISSUER_KIND_UNKNOWN, ("ISSUER_UNRESOLVED",)
    return ISSUER_KIND_INDUSTRIAL, ()


def _prior_facts(
    session: Session,
    reports: Sequence[ReportRef],
    latest: ReportRef,
) -> PriorPeriodFacts | None:
    prior_report = select_comparable_prior(reports, latest)
    if prior_report is None or prior_report.report_id is None:
        return None
    facts = pit.load_facts(session, prior_report.report_id)
    by_code, _ = normalized_fact_map(facts)
    values = {
        code: float(fact.value)
        for code, fact in by_code.items()
        if fact.value is not None
    }
    if not values:
        return None
    return PriorPeriodFacts(report=prior_report, facts=values)


def _empty_snapshot(
    *,
    instrument_id: int,
    as_of: date,
    issuer_kind: str,
    status: str,
    limitations: Sequence[str],
    known_at: date | None = None,
    period_end: date | None = None,
    missing: Sequence[str] = (),
) -> FundamentalSnapshotV1:
    return FundamentalSnapshotV1(
        instrument_id=instrument_id,
        as_of=as_of,
        known_at=known_at,
        period_end=period_end,
        issuer_kind=issuer_kind,
        status=status,
        metrics={"builder": SNAPSHOT_BUILDER},
        missing_metrics=tuple(missing),
        facts_used=(),
        limitations=tuple(limitations),
        provider=PROVIDER,
    )


def build_fundamental_snapshot(
    session: Session,
    instrument_id: int,
    as_of: date,
    *,
    peer_instrument_ids: Sequence[int] | None = None,
    persist: bool = False,
) -> FundamentalSnapshotV1:
    """Build PIT-safe industrial FundamentalSnapshotV1 for one instrument."""
    if not fundamentals_schema_ready(session):
        snap = _empty_snapshot(
            instrument_id=instrument_id,
            as_of=as_of,
            issuer_kind=ISSUER_KIND_UNKNOWN,
            status=STATUS_NOT_AVAILABLE,
            limitations=("fundamentals schema missing; apply alembic 20260905_0018",),
        )
        return snap

    resolution = pit.resolve_issuer_for_instrument(session, instrument_id, as_of)
    issuer = session.get(Issuer, resolution.issuer_id) if resolution.issuer_id else None
    issuer_kind, kind_limits = resolve_issuer_kind(session, instrument_id, issuer)

    if issuer_kind == ISSUER_KIND_BANK_FI:
        return _empty_snapshot(
            instrument_id=instrument_id,
            as_of=as_of,
            issuer_kind=issuer_kind,
            status=STATUS_NOT_AVAILABLE,
            limitations=kind_limits,
            missing=("industrial_ratios",),
        )

    if resolution.issuer_id is None:
        return _empty_snapshot(
            instrument_id=instrument_id,
            as_of=as_of,
            issuer_kind=issuer_kind,
            status=STATUS_NOT_AVAILABLE,
            limitations=("UNMAPPED_ISSUER", *kind_limits),
        )

    reports = pit.load_visible_reports(
        session,
        resolution.issuer_id,
        as_of,
        reporting_standard=ReportingStandard.RAS,
    )
    latest = pit_rules.latest_report(reports, as_of)
    if latest is None or latest.report_id is None:
        return _empty_snapshot(
            instrument_id=instrument_id,
            as_of=as_of,
            issuer_kind=issuer_kind,
            status=STATUS_NOT_AVAILABLE,
            limitations=("NO_VISIBLE_RAS_REPORT", *kind_limits),
        )

    facts: tuple[FactRef, ...] = pit.load_facts(session, latest.report_id)
    prior = _prior_facts(session, reports, latest)
    metrics, missing, limitations, status = build_industrial_profile(
        as_of=as_of,
        latest=latest,
        facts=facts,
        visible_reports=reports,
        prior=prior,
    )
    by_code, _ = normalized_fact_map(facts)
    used = facts_used_payload(by_code, known_at=latest.known_at, period_end=latest.period_end)

    all_limitations = list(kind_limits) + list(limitations)
    if resolution.basis == pit.BASIS_CURRENT_ONLY:
        all_limitations.append("ISSUER_RESOLUTION_BASIS_CURRENT_ONLY")

    if peer_instrument_ids:
        peer_derived: list[dict[str, float]] = []
        for peer_id in peer_instrument_ids:
            if int(peer_id) == int(instrument_id):
                continue
            peer_snap = build_fundamental_snapshot(
                session, int(peer_id), as_of, peer_instrument_ids=None, persist=False
            )
            if peer_snap.issuer_kind != ISSUER_KIND_INDUSTRIAL:
                continue
            if peer_snap.status in (STATUS_NOT_AVAILABLE, STATUS_UNKNOWN):
                continue
            derived = (peer_snap.metrics or {}).get("derived") or {}
            if isinstance(derived, dict) and derived:
                peer_derived.append(
                    {k: float(v) for k, v in derived.items() if isinstance(v, int | float)}
                )
        subject_derived = metrics.get("derived") or {}
        metrics["peer_ranks"] = compute_peer_ranks(subject_derived, peer_derived)

    metrics["builder"] = SNAPSHOT_BUILDER
    metrics["issuer_id"] = resolution.issuer_id
    metrics["issuer_resolution_basis"] = resolution.basis

    snapshot = FundamentalSnapshotV1(
        instrument_id=instrument_id,
        as_of=as_of,
        known_at=latest.known_at,
        period_end=latest.period_end,
        issuer_kind=issuer_kind,
        status=status,
        metrics=metrics,
        missing_metrics=missing,
        facts_used=used,
        limitations=tuple(dict.fromkeys(all_limitations)),
        provider=PROVIDER,
    )
    if persist:
        persist_fundamental_snapshot(session, snapshot)
    return snapshot


class IndustrialFundamentalService:
    """Facade for UI / models / optional persistence."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def snapshot(
        self,
        instrument_id: int,
        as_of: date,
        *,
        peer_instrument_ids: Sequence[int] | None = None,
        persist: bool = False,
    ) -> FundamentalSnapshotV1:
        return build_fundamental_snapshot(
            self.session,
            instrument_id,
            as_of,
            peer_instrument_ids=peer_instrument_ids,
            persist=persist,
        )

    def snapshots_for_symbols(
        self,
        symbols: Sequence[str],
        as_of: date,
        *,
        persist: bool = False,
        with_peer_ranks: bool = False,
    ) -> list[FundamentalSnapshotV1]:
        ids: list[int] = []
        for symbol in symbols:
            row = self.session.scalar(
                select(Instrument).where(Instrument.symbol == symbol.upper()).limit(1)
            )
            if row is not None:
                ids.append(int(row.id))
        peer_ids = ids if with_peer_ranks else None
        return [
            self.snapshot(instrument_id, as_of, peer_instrument_ids=peer_ids, persist=persist)
            for instrument_id in ids
        ]
