"""Issuer identity sync from MOEX ISS for the current instrument cohort.

The cohort is taken from the *current* MOEX source mappings (``valid_to IS NULL``) of
active equities. Tickers are never guessed: the SECID we already trade is the only key
sent to the provider, and anything the provider cannot resolve exactly is stored as
UNMAPPED / AMBIGUOUS with a reason instead of a fabricated issuer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.infrastructure.market.models import Instrument
from app.modules.fundamentals.application.runs import finish_run, start_run
from app.modules.fundamentals.config import MAPPED_ASSET_CLASSES, PROVIDER_MOEX_IDENTITY
from app.modules.fundamentals.domain.types import (
    SOURCE_MOEX_ISS,
    IngestionStatus,
    IssuerIdentity,
    MappingStatus,
)
from app.modules.fundamentals.infrastructure.models import (
    Issuer,
    SecurityIssuerMapping,
    fundamentals_schema_ready,
)
from app.modules.fundamentals.ports import IssuerIdentityProvider
from app.modules.market.application.identity import SOURCE_MOEX, resolve_current_source


@dataclass
class IdentitySyncResult:
    status: str = IngestionStatus.NO_CHANGES.value
    instruments_considered: int = 0
    secids_resolved: int = 0
    mapped: int = 0
    ambiguous: int = 0
    unmapped: int = 0
    issuers_inserted: int = 0
    issuers_updated: int = 0
    mappings_inserted: int = 0
    mappings_updated: int = 0
    mappings_unchanged: int = 0
    without_current_secid: int = 0
    errors: list[str] = field(default_factory=list)
    run_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "instruments_considered": self.instruments_considered,
            "secids_resolved": self.secids_resolved,
            "without_current_secid": self.without_current_secid,
            "mapping_status_counts": {
                MappingStatus.MAPPED.value: self.mapped,
                MappingStatus.AMBIGUOUS.value: self.ambiguous,
                MappingStatus.UNMAPPED.value: self.unmapped,
            },
            "issuers_inserted": self.issuers_inserted,
            "issuers_updated": self.issuers_updated,
            "mappings_inserted": self.mappings_inserted,
            "mappings_updated": self.mappings_updated,
            "mappings_unchanged": self.mappings_unchanged,
            "errors": self.errors[:20],
            "error_count": len(self.errors),
        }


def cohort_instruments(session: Session, symbols: list[str] | None = None) -> list[Instrument]:
    """Active equities only. Indices have no issuer and are never mapped."""
    stmt = select(Instrument).where(
        Instrument.asset_class.in_(MAPPED_ASSET_CLASSES),
        Instrument.is_active.is_(True),
    )
    if symbols:
        stmt = stmt.where(Instrument.symbol.in_([s.strip().upper() for s in symbols]))
    return list(session.scalars(stmt.order_by(Instrument.symbol)))


def upsert_issuer(session: Session, identity: IssuerIdentity, result: IdentitySyncResult) -> Issuer:
    """Issuer identity is keyed on moex_emitent_id — the only stable key ISS exposes."""
    issuer = session.scalar(
        select(Issuer).where(Issuer.moex_emitent_id == identity.moex_emitent_id)
    )
    title = identity.title or identity.secid
    if issuer is None:
        issuer = Issuer(
            moex_emitent_id=identity.moex_emitent_id,
            inn=identity.inn,
            okpo=identity.okpo,
            title=title,
            title_en=identity.title_en,
            metadata_={"source": SOURCE_MOEX_ISS},
        )
        session.add(issuer)
        session.flush()
        result.issuers_inserted += 1
        return issuer

    changed = False
    for attr, value in (
        ("title", title),
        ("title_en", identity.title_en),
        ("inn", identity.inn),
        ("okpo", identity.okpo),
    ):
        if value is not None and getattr(issuer, attr) != value:
            setattr(issuer, attr, value)
            changed = True
    if changed:
        session.flush()
        result.issuers_updated += 1
    return issuer


def _find_mapping(
    session: Session, instrument_id: int, secid: str
) -> SecurityIssuerMapping | None:
    return session.scalar(
        select(SecurityIssuerMapping).where(
            SecurityIssuerMapping.instrument_id == instrument_id,
            SecurityIssuerMapping.source == SOURCE_MOEX_ISS,
            SecurityIssuerMapping.external_secid == secid,
            SecurityIssuerMapping.valid_from.is_(None),
        )
    )


def upsert_mapping(
    session: Session,
    *,
    instrument_id: int,
    secid: str,
    identity: IssuerIdentity,
    issuer_id: int | None,
    result: IdentitySyncResult,
) -> SecurityIssuerMapping:
    """Insert or refresh one current mapping. A conflicting issuer becomes AMBIGUOUS."""
    metadata: dict[str, Any] = {"provider": SOURCE_MOEX_ISS}
    if identity.reason:
        metadata["reason"] = identity.reason
    if identity.security_type:
        metadata["security_type"] = identity.security_type

    existing = _find_mapping(session, instrument_id, secid)
    if existing is None:
        mapping = SecurityIssuerMapping(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            source=SOURCE_MOEX_ISS,
            external_secid=secid,
            isin=identity.isin,
            mapping_status=identity.mapping_status.value,
            metadata_=metadata,
        )
        session.add(mapping)
        session.flush()
        result.mappings_inserted += 1
        return mapping

    conflicting_issuer = (
        existing.issuer_id is not None
        and issuer_id is not None
        and existing.issuer_id != issuer_id
    )
    target_status = (
        MappingStatus.AMBIGUOUS.value if conflicting_issuer else identity.mapping_status.value
    )
    if conflicting_issuer:
        metadata["reason"] = "ISSUER_CONFLICT"
        metadata["previous_issuer_id"] = existing.issuer_id
        metadata["provider_issuer_id"] = issuer_id

    changed = False
    if not conflicting_issuer and issuer_id is not None and existing.issuer_id != issuer_id:
        existing.issuer_id = issuer_id
        changed = True
    if identity.isin is not None and existing.isin != identity.isin:
        existing.isin = identity.isin
        changed = True
    if existing.mapping_status != target_status:
        existing.mapping_status = target_status
        changed = True
    if changed:
        existing.metadata_ = {**(existing.metadata_ or {}), **metadata}
        flag_modified(existing, "metadata_")
        session.flush()
        result.mappings_updated += 1
    else:
        result.mappings_unchanged += 1
    return existing


def sync_issuer_identity(
    session: Session,
    provider: IssuerIdentityProvider,
    *,
    symbols: list[str] | None = None,
) -> IdentitySyncResult:
    """Resolve issuers for the current cohort. Idempotent; writes no market data."""
    result = IdentitySyncResult()
    if not fundamentals_schema_ready(session):
        result.status = IngestionStatus.FAILED.value
        result.errors.append("fundamentals schema missing; apply alembic 20260905_0018")
        return result

    run = start_run(session, PROVIDER_MOEX_IDENTITY, requested_range="current_cohort")
    result.run_id = run.id

    for instrument in cohort_instruments(session, symbols):
        result.instruments_considered += 1
        current = resolve_current_source(session, instrument.id, SOURCE_MOEX)
        if current is None or not current.external_id:
            result.without_current_secid += 1
            continue
        secid = current.external_id
        result.secids_resolved += 1
        try:
            identity = provider.fetch_issuer(secid)
        except Exception as exc:  # noqa: BLE001 — one bad SECID must not abort the sync
            result.errors.append(f"{secid}: {exc}")
            continue

        issuer_id: int | None = None
        if identity.mapping_status is MappingStatus.MAPPED:
            issuer_id = upsert_issuer(session, identity, result).id
            result.mapped += 1
        elif identity.mapping_status is MappingStatus.AMBIGUOUS:
            result.ambiguous += 1
        else:
            result.unmapped += 1

        upsert_mapping(
            session,
            instrument_id=instrument.id,
            secid=secid,
            identity=identity,
            issuer_id=issuer_id,
            result=result,
        )

    wrote_something = (
        result.issuers_inserted
        or result.issuers_updated
        or result.mappings_inserted
        or result.mappings_updated
    )
    if result.errors and not wrote_something:
        status = IngestionStatus.FAILED
    elif result.errors:
        status = IngestionStatus.PARTIAL
    elif wrote_something:
        status = IngestionStatus.SUCCESS
    else:
        status = IngestionStatus.NO_CHANGES
    result.status = status.value
    finish_run(session, run, status=status, summary=result.to_dict())
    return result
