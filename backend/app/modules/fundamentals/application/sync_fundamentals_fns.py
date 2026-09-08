"""Bounded polite sync of industrial RAS reports from FNS GIR BO.

Idempotent upsert into existing ``financial_reports`` / ``financial_facts``.
Never runs on page render. Failures are DEGRADED (PARTIAL), not unhealthy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.infrastructure.market.models import Instrument
from app.modules.fundamentals.application.runs import finish_run, start_run
from app.modules.fundamentals.config import PROVIDER_FNS_GIR_BO
from app.modules.fundamentals.domain.types import (
    METRIC_CODES,
    SOURCE_FNS_GIR_BO,
    IngestionStatus,
    MappingStatus,
    NormalizationStatus,
)
from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import (
    BANK_FI_SECIDS,
    FNS_MAP_UNMAPPED,
    SUPPORT_BANK,
    SUPPORT_INDUSTRIAL,
    SUPPORT_UNMAPPED,
    FnsGirBoClient,
    FnsGirBoProvider,
    FnsIdentityResolution,
    resolve_fns_identity,
)
from app.modules.fundamentals.infrastructure.models import (
    FinancialFact,
    FinancialReport,
    Issuer,
    SecurityIssuerMapping,
    SourceDocument,
    fundamentals_schema_ready,
)
from app.modules.market.universe import INSTRUMENTS


@dataclass
class FnsSyncResult:
    status: str = IngestionStatus.NO_CHANGES.value
    issuers_considered: int = 0
    industrial_supported: int = 0
    bank_unsupported: int = 0
    unmapped: int = 0
    ambiguous: int = 0
    reports_received: int = 0
    reports_inserted: int = 0
    reports_skipped: int = 0
    facts_inserted: int = 0
    facts_rejected: int = 0
    errors: list[str] = field(default_factory=list)
    by_secid: dict[str, Any] = field(default_factory=dict)
    run_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "provider": SOURCE_FNS_GIR_BO,
            "issuers_considered": self.issuers_considered,
            "industrial_supported": self.industrial_supported,
            "bank_unsupported": self.bank_unsupported,
            "unmapped": self.unmapped,
            "ambiguous": self.ambiguous,
            "reports_received": self.reports_received,
            "reports_inserted": self.reports_inserted,
            "reports_skipped": self.reports_skipped,
            "facts_inserted": self.facts_inserted,
            "facts_rejected": self.facts_rejected,
            "errors": self.errors[:30],
            "error_count": len(self.errors),
            "by_secid": self.by_secid,
            "health": "DEGRADED" if self.errors else "OK",
        }


def p0_equity_symbols() -> list[str]:
    """Curated research/portfolio equity cohort (universe.py equities)."""
    return sorted(
        {row.symbol.upper() for row in INSTRUMENTS if row.asset_class == "equity"}
    )


def _issuer_for_secid(session: Session, secid: str) -> tuple[Issuer | None, Instrument | None]:
    mapping = session.scalar(
        select(SecurityIssuerMapping).where(
            SecurityIssuerMapping.external_secid == secid,
            SecurityIssuerMapping.source == "MOEX_ISS",
            SecurityIssuerMapping.mapping_status == MappingStatus.MAPPED.value,
            SecurityIssuerMapping.issuer_id.is_not(None),
        )
    )
    if mapping is None or mapping.issuer_id is None:
        instrument = session.scalar(
            select(Instrument).where(Instrument.symbol == secid, Instrument.is_active.is_(True))
        )
        return None, instrument
    issuer = session.get(Issuer, mapping.issuer_id)
    instrument = session.get(Instrument, mapping.instrument_id)
    return issuer, instrument


def _store_fns_identity(issuer: Issuer, resolution: Any) -> None:
    meta = dict(issuer.metadata_ or {})
    meta["fns"] = {
        "mapping_status": resolution.status,
        "support_status": resolution.support_status,
        "reason": resolution.reason,
        "org_id": resolution.org.org_id if resolution.org else None,
        "ogrn": resolution.org.ogrn if resolution.org else None,
        "inn": resolution.org.inn if resolution.org else issuer.inn,
        "short_name": resolution.org.short_name if resolution.org else None,
        "provider": SOURCE_FNS_GIR_BO,
    }
    if resolution.org and resolution.org.ogrn and not meta.get("ogrn"):
        meta["ogrn"] = resolution.org.ogrn
    issuer.metadata_ = meta
    flag_modified(issuer, "metadata_")


def _existing_report(session: Session, report: Any) -> FinancialReport | None:
    return session.scalar(
        select(FinancialReport).where(
            FinancialReport.issuer_id == report.issuer_id,
            FinancialReport.reporting_standard == report.reporting_standard.value,
            FinancialReport.period_type == report.period_type.value,
            FinancialReport.period_end == report.period_end,
            FinancialReport.report_version == report.report_version,
            FinancialReport.source == report.source,
        )
    )


def _persist_bundle(session: Session, bundle: Any, result: FnsSyncResult) -> None:
    report = bundle.report
    result.reports_received += 1
    if report.known_at is None:
        result.reports_skipped += 1
        return
    if _existing_report(session, report) is not None:
        result.reports_skipped += 1
        return

    doc = None
    if bundle.source_url or bundle.provider_document_id:
        doc = SourceDocument(
            provider=SOURCE_FNS_GIR_BO,
            source_url=bundle.source_url,
            provider_document_id=bundle.provider_document_id,
            published_at=bundle.published_at,
            content_hash=bundle.content_hash,
            mime_type="application/json",
            metadata_=dict(bundle.metadata or {}),
        )
        session.add(doc)
        session.flush()

    row = FinancialReport(
        issuer_id=report.issuer_id,
        reporting_standard=report.reporting_standard.value,
        period_type=report.period_type.value,
        period_start=report.period_start,
        period_end=report.period_end,
        published_at=bundle.published_at,
        known_at=report.known_at,
        known_at_precision=bundle.known_at_precision or "DATE",
        source=report.source,
        source_document_id=doc.id if doc else None,
        report_version=report.report_version,
        is_restatement=report.is_restatement,
        currency=report.currency,
        unit_scale=report.unit_scale,
        status=report.status.value,
        metadata_=dict(bundle.metadata or {}),
    )
    session.add(row)
    session.flush()
    result.reports_inserted += 1

    for fact in bundle.facts:
        if (
            fact.normalization_status is NormalizationStatus.NORMALIZED
            and fact.metric_code not in METRIC_CODES
        ):
            result.facts_rejected += 1
            continue
        session.add(
            FinancialFact(
                report_id=row.id,
                metric_code=fact.metric_code,
                value=fact.value,
                currency=fact.currency,
                unit_scale=fact.unit_scale,
                source_metric_name=fact.source_metric_name or "",
                normalization_status=fact.normalization_status.value,
                quality_status=fact.quality_status.value,
                metadata_={"fact_kind": "SOURCE_FACT"},
            )
        )
        result.facts_inserted += 1
    session.flush()


def sync_fundamentals_fns(
    session: Session,
    *,
    symbols: list[str] | None = None,
    client: FnsGirBoClient | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    max_issuers: int | None = None,
) -> FnsSyncResult:
    """Incremental FNS RAS sync for the P0 equity cohort (or explicit symbols)."""
    result = FnsSyncResult()
    if not fundamentals_schema_ready(session):
        result.status = IngestionStatus.FAILED.value
        result.errors.append("fundamentals schema missing")
        return result

    cohort = [s.upper() for s in (symbols or p0_equity_symbols())]
    if max_issuers is not None:
        cohort = cohort[: max(0, max_issuers)]
    run = start_run(
        session,
        PROVIDER_FNS_GIR_BO,
        requested_range=f"{date_from or '-'}..{date_to or '-'}|{len(cohort)}",
    )
    result.run_id = run.id

    owns = client is None
    client = client or FnsGirBoClient()
    try:
        issuer_org: dict[int, int] = {}
        for secid in cohort:
            result.issuers_considered += 1
            sec_info: dict[str, Any] = {"secid": secid}
            try:
                if secid in BANK_FI_SECIDS:
                    result.bank_unsupported += 1
                    sec_info["support_status"] = SUPPORT_BANK
                    result.by_secid[secid] = sec_info
                    issuer, _ = _issuer_for_secid(session, secid)
                    if issuer is not None:
                        _store_fns_identity(
                            issuer,
                            FnsIdentityResolution(
                                status=FNS_MAP_UNMAPPED,
                                support_status=SUPPORT_BANK,
                                reason="BANK_FI_NOT_SUPPORTED_BY_FNS_RAS_V1",
                            ),
                        )
                    continue

                issuer, _instrument = _issuer_for_secid(session, secid)
                if issuer is None:
                    result.unmapped += 1
                    sec_info["support_status"] = SUPPORT_UNMAPPED
                    sec_info["reason"] = "ISSUER_IDENTITY_MISSING"
                    result.by_secid[secid] = sec_info
                    continue

                resolution = resolve_fns_identity(client, inn=issuer.inn, secid=secid)
                _store_fns_identity(issuer, resolution)
                sec_info["fns_mapping"] = resolution.status
                sec_info["support_status"] = resolution.support_status
                sec_info["reason"] = resolution.reason
                sec_info["fns_org_id"] = resolution.org.org_id if resolution.org else None

                if resolution.support_status == SUPPORT_BANK:
                    result.bank_unsupported += 1
                    result.by_secid[secid] = sec_info
                    continue
                if resolution.status == "AMBIGUOUS":
                    result.ambiguous += 1
                    result.by_secid[secid] = sec_info
                    continue
                if resolution.org is None or resolution.support_status != SUPPORT_INDUSTRIAL:
                    result.unmapped += 1
                    result.by_secid[secid] = sec_info
                    continue

                result.industrial_supported += 1
                issuer_org[issuer.id] = resolution.org.org_id
                result.by_secid[secid] = sec_info
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"{secid}: identity {exc}")
                sec_info["error"] = str(exc)
                result.by_secid[secid] = sec_info

        session.flush()
        provider = FnsGirBoProvider(client, issuer_org_ids=issuer_org)
        for issuer_id, org_id in issuer_org.items():
            try:
                bundles = provider.fetch_report_bundles(
                    issuer_id, date_from=date_from, date_to=date_to
                )
                for bundle in bundles:
                    _persist_bundle(session, bundle, result)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"issuer {issuer_id} org {org_id}: {exc}")
    finally:
        if owns:
            client.close()

    if result.reports_inserted:
        status = IngestionStatus.PARTIAL if result.errors else IngestionStatus.SUCCESS
    elif result.errors:
        status = IngestionStatus.PARTIAL
    else:
        status = IngestionStatus.NO_CHANGES
    result.status = status.value
    finish_run(session, run, status=status, summary=result.to_dict())
    return result
