"""GIR BO (bo.nalog.gov.ru) public JSON adapter — exact INN match only.

Bulk subscription endpoints exist in the UI but are not scraped around access controls.
The adapter is disabled by default via GIR_BO_ENABLED=false.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import httpx

from app.core.config import Settings, get_settings
from app.infrastructure.market.http_client import MarketHttpClient
from app.modules.fundamentals.domain.types import (
    SOURCE_GIR_BO,
    AccessModel,
    TimestampQuality,
)

DETAIL_TYPES = ("balance", "financial_result", "funds_movement")
SUBSCRIPTION_PATHS = ("/subscriptions", "/bfo-subscriptions", "/foiv/subscriptions")


@dataclass(frozen=True, slots=True)
class GirBoOrgRef:
    org_id: int
    inn: str
    short_name: str | None = None
    ogrn: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class GirBoBfoRef:
    bfo_id: int
    period_year: int
    actual_bfo_date: date | None
    known_at_quality: TimestampQuality
    correction_number: int | None = None
    published_correction_date: date | None = None
    knd: str | None = None
    has_az: bool | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class GirBoAccessClassification:
    access_model: AccessModel
    bulk_automation: str
    public_search: bool
    details_endpoint: str
    note: str


def normalize_inn(value: str | None) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", "", text)
    digits = re.sub(r"\D", "", text)
    return digits or None


def parse_search_page(payload: dict[str, Any], *, inn: str) -> GirBoOrgRef | None:
    """Exact INN match only — fuzzy name hits are rejected."""
    wanted = normalize_inn(inn)
    if not wanted:
        return None
    content = payload.get("content")
    if not isinstance(content, list):
        return None
    exact: list[dict[str, Any]] = []
    for row in content:
        if not isinstance(row, dict):
            continue
        row_inn = normalize_inn(row.get("inn"))
        if row_inn == wanted:
            exact.append(row)
    if len(exact) != 1:
        return None
    row = exact[0]
    org_id = row.get("id")
    if org_id is None:
        return None
    return GirBoOrgRef(
        org_id=int(org_id),
        inn=wanted,
        short_name=row.get("shortName"),
        ogrn=row.get("ogrn"),
        raw=row,
    )


def parse_bfo_list(payload: list[dict[str, Any]] | dict[str, Any]) -> list[GirBoBfoRef]:
    rows = payload if isinstance(payload, list) else payload.get("content") or []
    result: list[GirBoBfoRef] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        bfo_id = row.get("id")
        period_raw = row.get("period")
        if bfo_id is None or period_raw is None:
            continue
        actual_date = _parse_date(row.get("actualBfoDate"))
        result.append(
            GirBoBfoRef(
                bfo_id=int(bfo_id),
                period_year=int(str(period_raw)[:4]),
                actual_bfo_date=actual_date,
                known_at_quality=TimestampQuality.DATE_ONLY if actual_date else TimestampQuality.NONE,
                correction_number=_optional_int(row.get("actualCorrectionNumber")),
                published_correction_date=_parse_date(row.get("publishedCorrectionDate")),
                knd=row.get("knd"),
                has_az=row.get("hasAz"),
                raw=row,
            )
        )
    return result


def extract_ras_forms_from_bfo_row(row: dict[str, Any]) -> dict[str, Any]:
    """Merge balance + P&L (+ cash flow) lines from typeCorrections into one payload.

    GIR BO embeds form lines on ``typeCorrections[].correction`` (not on the BFO id itself).
    ``/nbo/details/{type}?id={bfoId}`` is empty; use correction.id for detail breakdowns.
    """
    merged: dict[str, Any] = {}
    if row.get("actives") is not None:
        merged["actives"] = row.get("actives")
    merged["unitScale"] = "RUB"
    corrections = row.get("typeCorrections") or []
    if not isinstance(corrections, list):
        return merged
    # Prefer highest correction number / last entry (latest restatement semantics).
    for item in corrections:
        if not isinstance(item, dict):
            continue
        corr = item.get("correction")
        if not isinstance(corr, dict):
            continue
        for form_key in ("balance", "financialResult", "fundsMovement"):
            form = corr.get(form_key)
            if not isinstance(form, dict):
                continue
            for key, value in form.items():
                if str(key).startswith(("current", "previous", "beforePrevious")):
                    merged[key] = value
        merged["correction_id"] = corr.get("id") or merged.get("correction_id")
    return merged


def classify_gir_bo_access(*, enabled: bool, probe_ok: bool | None = None) -> GirBoAccessClassification:
    if not enabled:
        return GirBoAccessClassification(
            access_model=AccessModel.DISABLED,
            bulk_automation="DISABLED",
            public_search=False,
            details_endpoint="/nbo/details/{type}?id={id}",
            note="GIR_BO_ENABLED=false — адаптер выключен по умолчанию.",
        )
    if probe_ok is False:
        return GirBoAccessClassification(
            access_model=AccessModel.PUBLIC_API,
            bulk_automation="PARTIAL",
            public_search=True,
            details_endpoint="/nbo/details/{type}?id={id}",
            note=(
                "Публичный поиск по ИНН частично доступен; часть крупных эмитентов "
                "(в т.ч. банки) не находится; массовая подписка — отдельная заявка."
            ),
        )
    return GirBoAccessClassification(
        access_model=AccessModel.PUBLIC_API,
        bulk_automation="REQUIRES_APPLICATION",
        public_search=True,
        details_endpoint="/nbo/details/{type}?id={id}",
            note=(
                "Публичные JSON: поиск, /nbo/organizations/{id}/bfo со встроенными формами "
                "РСБУ в typeCorrections (balance/financialResult, коды 2110/2400/1600…), "
                "actualBfoDate = DATE_ONLY. Детализация /nbo/details/* — по correction.id. "
                "Массовая выгрузка /subscriptions — заявка. Адаптер выключен по умолчанию."
            ),
        )


def _classification_dict(classification: GirBoAccessClassification) -> dict[str, Any]:
    return {
        "access_model": classification.access_model.value,
        "bulk_automation": classification.bulk_automation,
        "public_search": classification.public_search,
        "details_endpoint": classification.details_endpoint,
        "note": classification.note,
    }


def subscription_required_message(status_code: int) -> str:
    if status_code in {402, 403}:
        return "Массовая выгрузка ГИР БО требует подписки или заявки — это не общая ошибка сети."
    return f"ГИР БО вернул HTTP {status_code}."


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


class GirBoClient:
    source = SOURCE_GIR_BO

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: MarketHttpClient | httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self.base_url = self._settings.gir_bo_base_url.rstrip("/")
        self.user_agent = self._settings.gir_bo_user_agent
        if isinstance(client, MarketHttpClient):
            self._http = client
            self._owns_client = False
        elif client is not None:
            self._http = client
            self._owns_client = False
        else:
            self._http = httpx.Client(
                timeout=self._settings.http_timeout_seconds,
                follow_redirects=True,
                transport=transport,
                trust_env=False,
            )
            self._owns_client = True

    def close(self) -> None:
        if self._owns_client and isinstance(self._http, httpx.Client):
            self._http.close()

    @property
    def enabled(self) -> bool:
        return bool(self._settings.gir_bo_enabled)

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json,*/*",
            "Referer": f"{self.base_url}/",
            "X-Requested-With": "XMLHttpRequest",
        }

    def _request(
        self,
        method: Literal["GET"],
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        headers = self._headers()
        if isinstance(self._http, MarketHttpClient):
            return self._http.get(url, params=params, headers=headers)
        response = self._http.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response

    def search_by_inn(self, inn: str, *, page: int = 0, size: int = 10) -> GirBoOrgRef | None:
        if not self.enabled:
            raise RuntimeError("GIR_BO_ENABLED=false")
        response = self._request(
            "GET",
            "/advanced-search/organizations/search",
            params={"query": inn, "page": page, "size": size},
        )
        return parse_search_page(response.json(), inn=inn)

    def get_organization(self, org_id: int) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("GIR_BO_ENABLED=false")
        response = self._request("GET", f"/nbo/organizations/{org_id}")
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def list_bfo(self, org_id: int) -> list[GirBoBfoRef]:
        if not self.enabled:
            raise RuntimeError("GIR_BO_ENABLED=false")
        response = self._request("GET", f"/nbo/organizations/{org_id}/bfo")
        payload = response.json()
        return parse_bfo_list(payload)

    def fetch_details(self, detail_type: str, bfo_id: int) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("GIR_BO_ENABLED=false")
        if detail_type not in DETAIL_TYPES:
            raise ValueError(f"unsupported detail type: {detail_type}")
        # SPA base API is host+"/nbo"; bare "/details/..." falls through to the HTML shell.
        response = self._request("GET", f"/nbo/details/{detail_type}", params={"id": bfo_id})
        payload = response.json()
        return payload if isinstance(payload, dict) else {"raw": payload}

    def sample_probe(self, *, sample_inn: str = "7736050003") -> dict[str, Any]:
        """Non-destructive capability probe for CLI/API status — no secrets."""
        classification = classify_gir_bo_access(enabled=self.enabled)
        if not self.enabled:
            return {
                "enabled": False,
                "classification": _classification_dict(classification),
                "reachable": None,
                "authenticated": None,
                "sample_inn": sample_inn,
                "note": classification.note,
            }
        try:
            org = self.search_by_inn(sample_inn)
            reachable = org is not None
            bfo_count = 0
            if org is not None:
                bfo_count = len(self.list_bfo(org.org_id))
            classification = classify_gir_bo_access(enabled=True, probe_ok=reachable)
            return {
                "enabled": True,
                "reachable": reachable,
                "authenticated": True,
                "sample_inn": sample_inn,
                "sample_org_id": org.org_id if org else None,
                "sample_bfo_count": bfo_count,
                "classification": {
                    "access_model": classification.access_model.value,
                    "bulk_automation": classification.bulk_automation,
                    "public_search": classification.public_search,
                    "details_endpoint": classification.details_endpoint,
                    "note": classification.note,
                },
            }
        except httpx.HTTPStatusError as exc:
            return {
                "enabled": True,
                "reachable": False,
                "authenticated": exc.response.status_code not in {401, 403},
                "sample_inn": sample_inn,
                "error": subscription_required_message(exc.response.status_code),
                "classification": _classification_dict(
                    classify_gir_bo_access(enabled=True, probe_ok=False)
                ),
            }
        except Exception as exc:
            return {
                "enabled": True,
                "reachable": False,
                "authenticated": None,
                "sample_inn": sample_inn,
                "error": str(exc),
                "classification": _classification_dict(
                    classify_gir_bo_access(enabled=True, probe_ok=False)
                ),
            }
