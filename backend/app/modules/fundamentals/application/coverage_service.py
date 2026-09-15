"""Fundamental coverage + PIT snapshot services (read models)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.fundamentals.application import pit
from app.modules.fundamentals.application.sync_fundamentals_fns import p0_equity_symbols
from app.modules.fundamentals.domain.types import (
    FUNDAMENTALS_VERSION,
    MappingStatus,
    ReadinessStatus,
    ReportingStandard,
)
from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import (
    BANK_FI_SECIDS,
    SUPPORT_BANK,
    SUPPORT_INDUSTRIAL,
    SUPPORT_UNMAPPED,
)
from app.modules.fundamentals.infrastructure.models import (
    FinancialFact,
    FinancialReport,
    Issuer,
    SecurityIssuerMapping,
    fundamentals_schema_ready,
)


def _issuer_fns_meta(issuer: Issuer) -> dict[str, Any]:
    return dict((issuer.metadata_ or {}).get("fns") or {})


class FundamentalCoverageService:
    """Research-cohort and store-wide fundamental coverage (honest empty)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def cohort_table(self, symbols: list[str] | None = None) -> dict[str, Any]:
        if not fundamentals_schema_ready(self.session):
            return {
                "status": ReadinessStatus.NOT_READY.value,
                "reason": "fundamentals schema missing",
                "rows": [],
            }
        cohort = [s.upper() for s in (symbols or p0_equity_symbols())]
        rows: list[dict[str, Any]] = []
        for secid in cohort:
            mapping = self.session.scalar(
                select(SecurityIssuerMapping).where(
                    SecurityIssuerMapping.external_secid == secid,
                    SecurityIssuerMapping.mapping_status == MappingStatus.MAPPED.value,
                )
            )
            issuer = (
                self.session.get(Issuer, mapping.issuer_id)
                if mapping and mapping.issuer_id
                else None
            )
            fns = _issuer_fns_meta(issuer) if issuer else {}
            support = fns.get("support_status")
            if secid in BANK_FI_SECIDS:
                support = SUPPORT_BANK
            reports = 0
            latest_known = None
            latest_period = None
            if issuer is not None:
                reports = int(
                    self.session.execute(
                        select(func.count())
                        .select_from(FinancialReport)
                        .where(
                            FinancialReport.issuer_id == issuer.id,
                            FinancialReport.source == "FNS_GIR_BO",
                        )
                    ).scalar_one()
                )
                latest = self.session.scalar(
                    select(FinancialReport)
                    .where(FinancialReport.issuer_id == issuer.id)
                    .order_by(FinancialReport.period_end.desc(), FinancialReport.known_at.desc())
                    .limit(1)
                )
                if latest:
                    latest_known = latest.known_at.isoformat()
                    latest_period = latest.period_end.isoformat()
            rows.append(
                {
                    "secid": secid,
                    "issuer_id": issuer.id if issuer else None,
                    "inn": issuer.inn if issuer else None,
                    "moex_mapping": mapping.mapping_status if mapping else "UNMAPPED",
                    "fns_mapping": fns.get("mapping_status") or "UNMAPPED",
                    "support_status": support or SUPPORT_UNMAPPED,
                    "fns_org_id": fns.get("org_id"),
                    "ogrn": fns.get("ogrn"),
                    "reports": reports,
                    "latest_period_end": latest_period,
                    "latest_known_at": latest_known,
                    "bank_control": secid in BANK_FI_SECIDS,
                }
            )
        industrial = [r for r in rows if r["support_status"] == SUPPORT_INDUSTRIAL]
        with_reports = [r for r in industrial if r["reports"] > 0]
        return {
            "status": "OK",
            "version": FUNDAMENTALS_VERSION,
            "provider": "FNS_GIR_BO",
            "reporting_standard": ReportingStandard.RAS.value,
            "cohort_size": len(rows),
            "industrial_mapped": len(industrial),
            "industrial_with_reports": len(with_reports),
            "bank_unsupported": sum(1 for r in rows if r["support_status"] == SUPPORT_BANK),
            "unmapped": sum(1 for r in rows if r["support_status"] == SUPPORT_UNMAPPED),
            "rows": rows,
        }

    def store_summary(self) -> dict[str, Any]:
        if not fundamentals_schema_ready(self.session):
            return {"status": ReadinessStatus.NOT_READY.value, "coverage": {}}
        ras_reports = int(
            self.session.execute(
                select(func.count())
                .select_from(FinancialReport)
                .where(FinancialReport.reporting_standard == ReportingStandard.RAS.value)
            ).scalar_one()
        )
        fns_reports = int(
            self.session.execute(
                select(func.count())
                .select_from(FinancialReport)
                .where(FinancialReport.source == "FNS_GIR_BO")
            ).scalar_one()
        )
        facts = int(
            self.session.execute(select(func.count()).select_from(FinancialFact)).scalar_one()
        )
        return {
            "status": "OK",
            "ras_reports": ras_reports,
            "fns_gir_bo_reports": fns_reports,
            "financial_facts": facts,
            "issuers": int(
                self.session.execute(select(func.count()).select_from(Issuer)).scalar_one()
            ),
        }


class FundamentalSnapshotService:
    """Latest fundamentals as-of a decision date — PIT-safe."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def latest_as_of(
        self,
        issuer_id: int,
        as_of: date | None = None,
        *,
        reporting_standard: ReportingStandard | None = ReportingStandard.RAS,
    ) -> dict[str, Any]:
        effective = as_of or date.today()
        if not fundamentals_schema_ready(self.session):
            return {
                "status": ReadinessStatus.NOT_READY.value,
                "as_of": effective.isoformat(),
                "issuer_id": issuer_id,
            }
        state = pit.get_fundamentals_as_of(
            self.session,
            issuer_id,
            effective,
            reporting_standard=reporting_standard,
        )
        issuer = self.session.get(Issuer, issuer_id)
        fns = _issuer_fns_meta(issuer) if issuer else {}
        if fns.get("support_status") == SUPPORT_BANK:
            return {
                "status": SUPPORT_BANK,
                "as_of": effective.isoformat(),
                "issuer_id": issuer_id,
                "message": (
                    "Банки / финансовые институты не поддерживаются контуром FNS RAS V1. "
                    "Industrial metrics (REVENUE/EBITDA-style) не применяются."
                ),
                "report": None,
                "facts": [],
            }
        report = state.latest_report
        if report is None:
            return {
                "status": ReadinessStatus.NOT_READY.value,
                "as_of": effective.isoformat(),
                "issuer_id": issuer_id,
                "visible_reports": 0,
                "report": None,
                "facts": [],
            }
        facts = [
            {
                "metric_code": f.metric_code,
                "value": f.value,
                "unit_scale": f.unit_scale,
                "currency": f.currency,
                "normalization_status": str(f.normalization_status),
                "source_metric_name": f.source_metric_name,
                "missing": f.value is None,
            }
            for f in state.facts
        ]
        return {
            "status": "OK",
            "as_of": effective.isoformat(),
            "issuer_id": issuer_id,
            "visible_reports": state.visible_reports,
            "reporting_standard": str(report.reporting_standard),
            "badge": "РСБУ",
            "report": {
                "report_id": report.report_id,
                "period_end": report.period_end.isoformat(),
                "period_type": str(report.period_type),
                "known_at": report.known_at.isoformat(),
                "published_at_known": report.published_at_known,
                "source": report.source,
                "report_version": report.report_version,
                "is_restatement": report.is_restatement,
                "unit_scale": report.unit_scale,
            },
            "facts": facts,
            "derived": derive_defensible_metrics(facts),
        }

    def pit_acceptance_pair(
        self, issuer_id: int, known_at: date, *, period_end: date | None = None
    ) -> dict[str, Any]:
        """Mandatory before/after publication check for a specific disclosure."""
        before_as_of = known_at - timedelta(days=1)
        before_state = pit.get_fundamentals_as_of(
            self.session, issuer_id, before_as_of, reporting_standard=ReportingStandard.RAS
        )
        after_state = pit.get_fundamentals_as_of(
            self.session, issuer_id, known_at, reporting_standard=ReportingStandard.RAS
        )

        def _has_target(state_reports_count: int, state: Any) -> bool:
            # Target disclosure: a visible report with this known_at (and period if given).
            if state.latest_report is None:
                return False
            reports = pit.load_visible_reports(
                self.session, issuer_id, state.as_of, reporting_standard=ReportingStandard.RAS
            )
            for r in reports:
                if r.known_at != known_at:
                    continue
                if period_end is not None and r.period_end != period_end:
                    continue
                return True
            return False

        before_has = _has_target(before_state.visible_reports, before_state)
        after_has = _has_target(after_state.visible_reports, after_state)
        return {
            "issuer_id": issuer_id,
            "publication_known_at": known_at.isoformat(),
            "period_end": period_end.isoformat() if period_end else None,
            "before_as_of": before_as_of.isoformat(),
            "before_has_target_report": before_has,
            "after_has_target_report": after_has,
            "before_visible_reports": before_state.visible_reports,
            "after_visible_reports": after_state.visible_reports,
            "pass": (not before_has) and after_has,
            "rule": (
                "specific report with known_at=K must be invisible at K-1 day and "
                "visible at K (older reports may already be visible)"
            ),
        }


def derive_defensible_metrics(facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Only ratios from SOURCE facts. No fake EBITDA/FCF."""
    by_code = {f["metric_code"]: f.get("value") for f in facts if f.get("value") is not None}
    out: dict[str, Any] = {"note": "DERIVED only from present SOURCE facts; never invent EBITDA/FCF"}
    equity = by_code.get("TOTAL_EQUITY")
    assets = by_code.get("TOTAL_ASSETS")
    net = by_code.get("NET_INCOME")
    debt = by_code.get("TOTAL_DEBT")
    cash = by_code.get("CASH_AND_EQUIVALENTS")
    if equity not in (None, 0) and net is not None:
        out["roe"] = net / equity
    if assets not in (None, 0) and net is not None:
        out["roa"] = net / assets
    if equity is not None and debt is not None:
        out["debt_to_equity"] = None if equity == 0 else debt / equity
    if debt is not None and cash is not None:
        out["net_debt"] = debt - cash
    # Explicitly absent:
    out["ebitda"] = None
    out["fcf"] = None
    out["ebitda_status"] = "NOT_DERIVED_AMBIGUOUS"
    out["fcf_status"] = "NOT_DERIVED"
    return out


def portfolio_equity_fundamental_coverage(session: Session) -> dict[str, Any]:
    """Read-only portfolio coverage summary for equities in the curated cohort."""
    svc = FundamentalCoverageService(session)
    table = svc.cohort_table()
    return {
        "status": table.get("status"),
        "read_only": True,
        "industrial_with_reports": table.get("industrial_with_reports"),
        "industrial_mapped": table.get("industrial_mapped"),
        "bank_unsupported": table.get("bank_unsupported"),
        "unmapped": table.get("unmapped"),
        "note": (
            "Portfolio shows fundamental coverage read-only. Sync runs via "
            "sync_fundamentals_fns / Celery, never on page render."
        ),
        "rows": table.get("rows") or [],
    }
