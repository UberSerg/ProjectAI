"""Load master candidates and write a resolution onto a source document.

Uses ``fundamentals.issuers``, ``fundamentals.security_issuer_mappings`` and
``market.instruments``. Issuer identity at the document's own ``known_at``
comes from ``resolve_issuer_for_instrument``. No new table: the result is
``instrument_id`` / ``issuer_id`` (only when MAPPED), ``mapping_basis``, and
``metadata["company_resolution"]``.

``known_at``, ``observed_at`` and ``published_at`` are never rewritten and
never backdated. The calendar date of the stored ``known_at`` is only read,
and it is not converted into another timezone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.infrastructure.market.models import Instrument
from app.modules.fundamentals.application.pit import resolve_issuer_for_instrument
from app.modules.fundamentals.domain.types import MappingStatus
from app.modules.fundamentals.infrastructure.models import Issuer, SecurityIssuerMapping
from app.modules.intelligence.news.models import IntelligenceSourceDocument
from app.modules.intelligence.resolution.decide import (
    CompanyResolution,
    MasterIdentityRow,
    ResolutionCandidate,
    assemble_candidates,
    resolve_company,
)

_EXPLICIT_SECID_KEYS = ("secid", "ticker", "external_secid")
_EXPLICIT_ISIN_KEYS = ("isin",)
_EXPLICIT_INN_KEYS = ("inn",)
_EXPLICIT_OGRN_KEYS = ("ogrn",)


def resolve_source_document(
    session: Session,
    document: IntelligenceSourceDocument,
) -> CompanyResolution:
    """Resolve one document in place. Clocks on the document stay as they were."""
    known_at = document.known_at
    as_of = _calendar_date(known_at)
    if as_of is None:
        decision = resolve_company("", ())
    else:
        candidates = load_resolution_candidates(session, as_of)
        explicit = _explicit_identifiers(document.metadata_ or {})
        decision = resolve_company(
            _document_text(document),
            candidates,
            explicit_secids=explicit[0],
            explicit_isins=explicit[1],
            explicit_inns=explicit[2],
            explicit_ogrns=explicit[3],
        )
    apply_company_resolution(document, decision)
    return decision


def load_resolution_candidates(session: Session, as_of: date) -> list[ResolutionCandidate]:
    """MAPPED instrument/issuer rows whose point-in-time link agrees at ``as_of``."""
    rows = list(
        session.execute(
            select(Instrument, SecurityIssuerMapping, Issuer)
            .join(SecurityIssuerMapping, SecurityIssuerMapping.instrument_id == Instrument.id)
            .join(Issuer, Issuer.id == SecurityIssuerMapping.issuer_id)
            .where(
                SecurityIssuerMapping.mapping_status == MappingStatus.MAPPED.value,
                SecurityIssuerMapping.issuer_id.is_not(None),
            )
        ).all()
    )
    master_rows = [_master_row(instrument, mapping, issuer) for instrument, mapping, issuer in rows]
    instrument_ids = sorted({row.instrument_id for row in master_rows})
    pit_by_instrument = {
        instrument_id: _pit_pair(session, instrument_id, as_of) for instrument_id in instrument_ids
    }
    return assemble_candidates(master_rows, pit_by_instrument)


def apply_company_resolution(
    document: IntelligenceSourceDocument,
    decision: CompanyResolution,
) -> None:
    """Write the association. Ids are stored only for MAPPED. Clocks are restored."""
    known_at = document.known_at
    observed_at = document.observed_at
    published_at = document.published_at
    if decision.status == MappingStatus.MAPPED.value:
        document.instrument_id = decision.instrument_id
        document.issuer_id = decision.issuer_id
    else:
        document.instrument_id = None
        document.issuer_id = None
    document.mapping_basis = decision.mapping_basis
    metadata = dict(document.metadata_ or {})
    metadata["company_resolution"] = decision.as_metadata()
    document.metadata_ = metadata
    flag_modified(document, "metadata_")
    document.known_at = known_at
    document.observed_at = observed_at
    document.published_at = published_at


def _pit_pair(session: Session, instrument_id: int, as_of: date) -> tuple[str, int | None]:
    resolution = resolve_issuer_for_instrument(session, instrument_id, as_of)
    return resolution.mapping_status, resolution.issuer_id


def _master_row(
    instrument: Instrument,
    mapping: SecurityIssuerMapping,
    issuer: Issuer,
) -> MasterIdentityRow:
    return MasterIdentityRow(
        instrument_id=instrument.id,
        symbol=instrument.symbol,
        instrument_name=instrument.name,
        instrument_isin=instrument.isin,
        issuer_id=mapping.issuer_id if mapping.issuer_id is not None else issuer.id,
        title=issuer.title,
        title_en=issuer.title_en,
        inn=issuer.inn,
        issuer_metadata=dict(issuer.metadata_ or {}),
        external_secid=mapping.external_secid,
        mapping_isin=mapping.isin,
        mapping_status=mapping.mapping_status,
    )


def _document_text(document: IntelligenceSourceDocument) -> str:
    parts = [part for part in (document.title, document.raw_text) if part]
    return "\n".join(parts)


def _explicit_identifiers(
    metadata: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Structured identifiers already on the document. Ignores our own resolution blob."""
    return (
        _metadata_values(metadata, _EXPLICIT_SECID_KEYS),
        _metadata_values(metadata, _EXPLICIT_ISIN_KEYS),
        _metadata_values(metadata, _EXPLICIT_INN_KEYS),
        _metadata_values(metadata, _EXPLICIT_OGRN_KEYS),
    )


def _metadata_values(metadata: Mapping[str, Any], keys: Sequence[str]) -> tuple[str, ...]:
    found: list[str] = []
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value.strip())
        elif isinstance(value, list | tuple):
            for item in value:
                if isinstance(item, str) and item.strip():
                    found.append(item.strip())
    return tuple(found)


def _calendar_date(value: datetime | date | None) -> date | None:
    """Date of the stored clock. ``datetime`` is checked first because it subclasses ``date``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None
