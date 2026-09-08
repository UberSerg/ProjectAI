"""FNS GIR BO (bo.nalog.gov.ru) public RAS report provider.

Live contract (probed 2026-09-08):
- Search: ``/advanced-search/organizations/search?query={INN}``
- Card: ``/nbo/organizations/{id}``
- Reports: ``/nbo/organizations/{id}/bfo/`` → JSON with nested forms

PIT anchors:
- ``correction.datePresent`` (timestamp) preferred for ``published_at``;
  ``known_at`` uses the date part only (DATE_ONLY, conservative).
- else ``period.actualBfoDate`` (date).

Industrial RAS only. Banks / ``isCb=true`` → NOT_SUPPORTED_BY_FNS_RAS_V1.
Missing line items stay null — never coerced to 0.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import httpx

from app.modules.fundamentals.domain.types import (
    SOURCE_FNS_GIR_BO,
    FactRef,
    NormalizationStatus,
    PeriodType,
    QualityStatus,
    ReportingStandard,
    ReportRef,
    ReportStatus,
)

FNS_BASE_URL = "https://bo.nalog.gov.ru"
FNS_SEARCH_PATH = "/advanced-search/organizations/search"
FNS_ORG_PATH = "/nbo/organizations/{org_id}"
FNS_BFO_PATH = "/nbo/organizations/{org_id}/bfo/"

SUPPORT_INDUSTRIAL = "INDUSTRIAL_RAS_V1"
SUPPORT_BANK = "NOT_SUPPORTED_BY_FNS_RAS_V1"
SUPPORT_UNMAPPED = "UNMAPPED"

FNS_MAP_EXACT = "EXACT_IDENTIFIER"
FNS_MAP_VERIFIED = "VERIFIED"
FNS_MAP_AMBIGUOUS = "AMBIGUOUS"
FNS_MAP_UNMAPPED = "UNMAPPED"

# Bank / FI equity tickers that must never receive industrial RAS metrics.
BANK_FI_SECIDS: frozenset[str] = frozenset(
    {"SBER", "SBERP", "VTBR", "BSPB", "CBOM"}
)

# RAS line codes (ОКУД) → normalised metric. SOURCE FACT only.
_BALANCE_LINES: tuple[tuple[str, str], ...] = (
    ("1600", "TOTAL_ASSETS"),
    ("1300", "TOTAL_EQUITY"),
    ("1250", "CASH_AND_EQUIVALENTS"),
)
_RESULT_LINES: tuple[tuple[str, str], ...] = (
    ("2110", "REVENUE"),
    ("2200", "OPERATING_INCOME"),
    ("2400", "NET_INCOME"),
)
_CASHFLOW_LINES: tuple[tuple[str, str], ...] = (("4100", "OPERATING_CASH_FLOW"),)

# Debt = LT borrowings (1410) + ST borrowings (1510). Both keys must be present
# (value may be 0.0); a missing key means the fact is omitted, not zeroed.
_DEBT_LINES: tuple[str, str] = ("1410", "1510")

_PERIOD_TYPE_BY_BFO: dict[int, PeriodType] = {
    12: PeriodType.FY,
    3: PeriodType.Q1,
    6: PeriodType.H1,
    9: PeriodType.NINE_MONTHS,
}


@dataclass(frozen=True, slots=True)
class FnsOrgHit:
    org_id: int
    inn: str
    ogrn: str | None
    short_name: str | None
    is_cb: bool | None = None
    latest_period: str | None = None
    actual_bfo_date: str | None = None


@dataclass(frozen=True, slots=True)
class FnsIdentityResolution:
    status: str
    support_status: str
    org: FnsOrgHit | None = None
    reason: str | None = None
    candidates: tuple[FnsOrgHit, ...] = ()


@dataclass(frozen=True, slots=True)
class FnsReportBundle:
    report: ReportRef
    facts: tuple[FactRef, ...]
    published_at: datetime | None
    known_at_precision: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_url: str | None = None
    provider_document_id: str | None = None
    content_hash: str | None = None


def _strip_html(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"<[^>]+>", "", str(value)).strip() or None


def _parse_date(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        d = _parse_date(text)
        return datetime(d.year, d.month, d.day) if d else None


def _line_value(form: Mapping[str, Any] | None, code: str) -> float | None:
    """Return currentXXXX when the key exists; missing key → None (never invent 0)."""
    if not form:
        return None
    key = f"current{code}"
    if key not in form:
        return None
    raw = form.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def extract_facts_from_correction(correction: Mapping[str, Any]) -> list[FactRef]:
    balance = correction.get("balance") or {}
    result = correction.get("financialResult") or {}
    cashflow = correction.get("fundsMovement") or {}
    facts: list[FactRef] = []

    for code, metric in _BALANCE_LINES:
        value = _line_value(balance, code)
        if value is None:
            continue
        facts.append(
            FactRef(
                metric_code=metric,
                value=value,
                normalization_status=NormalizationStatus.NORMALIZED,
                quality_status=QualityStatus.OK,
                currency="RUB",
                unit_scale="THOUSANDS",
                source_metric_name=f"balance.current{code}",
            )
        )

    debt_parts: list[float] = []
    debt_ok = True
    for code in _DEBT_LINES:
        key = f"current{code}"
        if key not in balance:
            debt_ok = False
            break
        raw = balance.get(key)
        if raw is None:
            debt_parts.append(0.0)
        else:
            try:
                debt_parts.append(float(raw))
            except (TypeError, ValueError):
                debt_ok = False
                break
    if debt_ok:
        facts.append(
            FactRef(
                metric_code="TOTAL_DEBT",
                value=sum(debt_parts),
                normalization_status=NormalizationStatus.NORMALIZED,
                quality_status=QualityStatus.OK,
                currency="RUB",
                unit_scale="THOUSANDS",
                source_metric_name="balance.current1410+current1510",
            )
        )

    for code, metric in _RESULT_LINES:
        value = _line_value(result, code)
        if value is None:
            continue
        facts.append(
            FactRef(
                metric_code=metric,
                value=value,
                normalization_status=NormalizationStatus.NORMALIZED,
                quality_status=QualityStatus.OK,
                currency="RUB",
                unit_scale="THOUSANDS",
                source_metric_name=f"financialResult.current{code}",
            )
        )

    for code, metric in _CASHFLOW_LINES:
        value = _line_value(cashflow, code)
        if value is None:
            continue
        facts.append(
            FactRef(
                metric_code=metric,
                value=value,
                normalization_status=NormalizationStatus.NORMALIZED,
                quality_status=QualityStatus.OK,
                currency="RUB",
                unit_scale="THOUSANDS",
                source_metric_name=f"fundsMovement.current{code}",
            )
        )
    return facts


def resolve_known_at(period: Mapping[str, Any], correction: Mapping[str, Any]) -> tuple[date, datetime | None, str]:
    """Return (known_at date, published_at datetime|None, precision)."""
    present = _parse_datetime(correction.get("datePresent"))
    actual = _parse_date(period.get("actualBfoDate"))
    if present is not None:
        return present.date(), present, "DATE"
    if actual is not None:
        return actual, datetime(actual.year, actual.month, actual.day), "DATE"
    raise ValueError("MISSING_KNOWN_AT: neither datePresent nor actualBfoDate")


def _fy_period_end(year: int) -> date:
    return date(year, 12, 31)


def _fy_period_start(year: int) -> date:
    return date(year, 1, 1)


class FnsGirBoClient:
    """Polite HTTP client for public FNS GIR BO JSON endpoints."""

    def __init__(
        self,
        *,
        base_url: str = FNS_BASE_URL,
        timeout: float = 45.0,
        pacing_seconds: float = 0.35,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.pacing_seconds = max(0.0, pacing_seconds)
        self._last_request_at = 0.0
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
            headers={
                "Accept": "application/json",
                "User-Agent": "ProjectAI-Fundamentals/1.0 (+research; polite)",
                "Referer": f"{self.base_url}/",
            },
        )

    def close(self) -> None:
        self._client.close()

    def _pace(self) -> None:
        if self.pacing_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.pacing_seconds:
            time.sleep(self.pacing_seconds - elapsed)

    def get_json(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        self._pace()
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        response = self._client.get(url, params=dict(params or {}))
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response.json()

    def search_by_inn(self, inn: str) -> list[FnsOrgHit]:
        payload = self.get_json(FNS_SEARCH_PATH, params={"query": inn, "page": 0, "size": 10})
        content = payload.get("content") or []
        hits: list[FnsOrgHit] = []
        for row in content:
            org_id = row.get("id")
            matched_inn = _strip_html(row.get("inn"))
            if org_id is None or not matched_inn:
                continue
            bfo = row.get("bfo") or {}
            hits.append(
                FnsOrgHit(
                    org_id=int(org_id),
                    inn=matched_inn,
                    ogrn=_strip_html(row.get("ogrn")),
                    short_name=_strip_html(row.get("shortName")),
                    is_cb=bfo.get("isCb"),
                    latest_period=str(bfo.get("period")) if bfo.get("period") is not None else None,
                    actual_bfo_date=str(bfo.get("actualBfoDate"))
                    if bfo.get("actualBfoDate") is not None
                    else None,
                )
            )
        return hits

    def fetch_bfo(self, org_id: int) -> list[dict[str, Any]]:
        path = FNS_BFO_PATH.format(org_id=org_id)
        payload = self.get_json(path)
        if not isinstance(payload, list):
            return []
        return list(payload)


def resolve_fns_identity(
    client: FnsGirBoClient,
    *,
    inn: str | None,
    secid: str | None = None,
) -> FnsIdentityResolution:
    """Map MOEX INN → FNS org. Exact INN match only; no name guessing."""
    if secid and secid.upper() in BANK_FI_SECIDS:
        return FnsIdentityResolution(
            status=FNS_MAP_UNMAPPED,
            support_status=SUPPORT_BANK,
            reason="BANK_FI_NOT_SUPPORTED_BY_FNS_RAS_V1",
        )
    if not inn:
        return FnsIdentityResolution(
            status=FNS_MAP_UNMAPPED,
            support_status=SUPPORT_UNMAPPED,
            reason="MISSING_INN",
        )

    hits = client.search_by_inn(inn)
    exact = [h for h in hits if h.inn == inn]
    if not exact:
        return FnsIdentityResolution(
            status=FNS_MAP_UNMAPPED,
            support_status=SUPPORT_UNMAPPED,
            reason="FNS_INN_SEARCH_EMPTY",
            candidates=tuple(hits),
        )
    if len(exact) > 1:
        return FnsIdentityResolution(
            status=FNS_MAP_AMBIGUOUS,
            support_status=SUPPORT_UNMAPPED,
            reason="MULTIPLE_EXACT_INN_HITS",
            candidates=tuple(exact),
        )
    org = exact[0]
    if org.is_cb is True:
        return FnsIdentityResolution(
            status=FNS_MAP_EXACT,
            support_status=SUPPORT_BANK,
            org=org,
            reason="IS_CB_TRUE",
        )
    return FnsIdentityResolution(
        status=FNS_MAP_EXACT,
        support_status=SUPPORT_INDUSTRIAL,
        org=org,
    )


def parse_bfo_periods(
    periods: Sequence[Mapping[str, Any]],
    *,
    issuer_id: int,
    org_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[FnsReportBundle]:
    """Convert FNS BFO JSON periods into ReportRef + facts. Latest correction only."""
    bundles: list[FnsReportBundle] = []
    for period in periods:
        if period.get("isCb") is True:
            continue
        year_raw = period.get("period")
        try:
            year = int(str(year_raw))
        except (TypeError, ValueError):
            continue
        period_end = _fy_period_end(year)
        if date_from and period_end < date_from:
            continue
        if date_to and period_end > date_to:
            continue

        corrections = period.get("typeCorrections") or []
        if not corrections:
            continue
        # Prefer annual type=12; else first available. Online feed = latest only.
        preferred = None
        for item in corrections:
            if int(item.get("type") or 0) == 12:
                preferred = item
                break
        if preferred is None:
            preferred = corrections[0]
        correction = preferred.get("correction") or {}
        if not correction:
            continue

        try:
            known_at, published_at, precision = resolve_known_at(period, correction)
        except ValueError:
            continue

        period_type_code = int(correction.get("periodType") or preferred.get("type") or 12)
        period_type = _PERIOD_TYPE_BY_BFO.get(period_type_code, PeriodType.FY)
        facts = tuple(extract_facts_from_correction(correction))
        corr_num = int(
            period.get("actualCorrectionNumber")
            or correction.get("correctionVersion")
            or 0
        )
        report_version = max(1, corr_num + 1)
        bfo_id = period.get("id")
        source_url = f"{FNS_BASE_URL}{FNS_BFO_PATH.format(org_id=org_id)}"
        metadata = {
            "fns_org_id": org_id,
            "fns_bfo_id": bfo_id,
            "fns_correction_id": correction.get("id"),
            "reporting_standard": ReportingStandard.RAS.value,
            "revision_history_incomplete": True,
            "revision_note": (
                "FNS online BFO exposes the latest correction for the period; "
                "earlier superseding history is incomplete."
            ),
            "actual_bfo_date": period.get("actualBfoDate"),
            "date_present": correction.get("datePresent"),
            "knd": period.get("knd") or correction.get("knd"),
            "fact_kind": "SOURCE_FACT",
        }
        report = ReportRef(
            issuer_id=issuer_id,
            reporting_standard=ReportingStandard.RAS,
            period_type=period_type,
            period_start=_fy_period_start(year) if period_type is PeriodType.FY else None,
            period_end=period_end,
            known_at=known_at,
            report_version=report_version,
            is_restatement=corr_num > 0,
            source=SOURCE_FNS_GIR_BO,
            status=ReportStatus.ACTIVE,
            currency="RUB",
            unit_scale="THOUSANDS",
            published_at_known=published_at is not None,
        )
        bundles.append(
            FnsReportBundle(
                report=report,
                facts=facts,
                published_at=published_at,
                known_at_precision=precision,
                metadata=metadata,
                source_url=source_url,
                provider_document_id=str(bfo_id) if bfo_id is not None else None,
            )
        )
    return bundles


class FnsGirBoProvider:
    """``FundamentalReportProvider`` adapter around public FNS GIR BO JSON."""

    source = SOURCE_FNS_GIR_BO

    def __init__(
        self,
        client: FnsGirBoClient | None = None,
        *,
        issuer_org_ids: Mapping[int, int] | None = None,
    ) -> None:
        self.client = client or FnsGirBoClient()
        self._owns_client = client is None
        # issuer_id → fns_org_id (resolved upstream by sync)
        self.issuer_org_ids = dict(issuer_org_ids or {})

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def fetch_reports(
        self, issuer: int, *, date_from: date | None = None, date_to: date | None = None
    ) -> Sequence[tuple[ReportRef, Sequence[FactRef]]]:
        org_id = self.issuer_org_ids.get(issuer)
        if org_id is None:
            return []
        periods = self.client.fetch_bfo(org_id)
        bundles = parse_bfo_periods(
            periods, issuer_id=issuer, org_id=org_id, date_from=date_from, date_to=date_to
        )
        return [(b.report, b.facts) for b in bundles]

    def fetch_report_bundles(
        self, issuer: int, *, date_from: date | None = None, date_to: date | None = None
    ) -> list[FnsReportBundle]:
        org_id = self.issuer_org_ids.get(issuer)
        if org_id is None:
            return []
        periods = self.client.fetch_bfo(org_id)
        return parse_bfo_periods(
            periods, issuer_id=issuer, org_id=org_id, date_from=date_from, date_to=date_to
        )
