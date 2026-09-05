"""GIR BO → FundamentalReportProvider adapter (opt-in via GIR_BO_ENABLED).

Maps issuer INN → exact GIR org → BFO rows with actualBfoDate as known_at (DATE_ONLY).
Does not invent timestamps. Does not run unless the client is enabled.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fundamentals.domain.types import (
    SOURCE_GIR_BO,
    PeriodType,
    ReportingStandard,
    ReportRef,
)
from app.modules.fundamentals.infrastructure.gir_bo_client import (
    GirBoClient,
    extract_ras_forms_from_bfo_row,
)
from app.modules.fundamentals.infrastructure.models import Issuer
from app.modules.fundamentals.infrastructure.ras_report_parser import parse_ras_payload, to_fact_refs


class GirBoReportProvider:
    """FundamentalReportProvider backed by public GIR BO JSON."""

    source = SOURCE_GIR_BO

    def __init__(self, session: Session, client: GirBoClient | None = None) -> None:
        self._session = session
        self._client = client or GirBoClient()
        self._owns = client is None

    def close(self) -> None:
        if self._owns:
            self._client.close()

    def fetch_reports(
        self, issuer: int, *, date_from: date | None = None, date_to: date | None = None
    ) -> Sequence[tuple[ReportRef, Sequence[Any]]]:
        if not self._client.enabled:
            return []
        row = self._session.get(Issuer, issuer)
        if row is None or not row.inn:
            return []
        org = self._client.search_by_inn(str(row.inn))
        if org is None:
            return []
        out: list[tuple[ReportRef, Sequence[Any]]] = []
        for bfo in self._client.list_bfo(org.org_id):
            if bfo.actual_bfo_date is None:
                continue
            if date_from and bfo.actual_bfo_date < date_from:
                continue
            if date_to and bfo.actual_bfo_date > date_to:
                continue
            period_end = date(bfo.period_year, 12, 31)
            version = int(bfo.correction_number or 0) + 1
            raw = bfo.raw or {}
            # Prefer live row with typeCorrections when present on list payload.
            payload = extract_ras_forms_from_bfo_row(raw)
            if not any(str(k).startswith("current") for k in payload):
                # Re-fetch list is already full; if empty forms, skip facts but keep metadata-only? 
                # Without line items we still skip — no invented metrics.
                continue
            parsed = parse_ras_payload(payload)
            facts = to_fact_refs(parsed)
            report = ReportRef(
                issuer_id=issuer,
                reporting_standard=ReportingStandard.RAS,
                period_type=PeriodType.FY,
                period_end=period_end,
                period_start=date(bfo.period_year, 1, 1),
                known_at=bfo.actual_bfo_date,
                source=SOURCE_GIR_BO,
                report_version=version,
                is_restatement=version > 1,
                published_at_known=True,
                unit_scale="RUB",
                currency="RUB",
            )
            out.append((report, facts))
        return out


def resolve_issuer_ids_by_inn(session: Session, inns: Sequence[str]) -> list[int]:
    wanted = {"".join(ch for ch in inn if ch.isdigit()) for inn in inns}
    wanted.discard("")
    if not wanted:
        return []
    rows = session.scalars(select(Issuer).where(Issuer.inn.in_(wanted))).all()
    return [int(r.id) for r in rows if r.id is not None]
