"""Public API for bank / FI fundamentals intelligence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from app.modules.intelligence.banks.cbr_catalog import (
    CbrCatalogIndex,
    fetch_cbr_reports_index_html,
    parse_cbr_reports_index_html,
)
from app.modules.intelligence.banks.classification import is_bank_fi_secid
from app.modules.intelligence.banks.providers import (
    CBR_CREDIT_ORG_BY_SECID,
    bank_source_registry,
    overall_bank_fundamentals_status,
)
from app.modules.intelligence.banks.snapshot import (
    assert_no_industrial_fallback,
    build_bank_fundamental_snapshot,
)
from app.modules.intelligence.contracts.snapshots_domain import FundamentalSnapshotV1


def provider_status_report() -> dict[str, Any]:
    sources = bank_source_registry()
    return {
        "schema": "BankFundamentalsProviderStatusV1",
        "overall_status": overall_bank_fundamentals_status(sources),
        "industrial_fns_fallback": "FORBIDDEN",
        "providers": [s.to_dict() for s in sources],
        "curated_cbr_credit_orgs": {
            k: {
                "secid": v.secid,
                "regnum": v.regnum,
                "ogrn": v.ogrn,
                "inn": v.inn,
                "title": v.title,
            }
            for k, v in CBR_CREDIT_ORG_BY_SECID.items()
        },
    }


def maybe_load_cbr_catalog(
    secid: str,
    *,
    live: bool = False,
    html_fixture: str | None = None,
) -> CbrCatalogIndex | None:
    """Load CBR form coverage for a curated SECID.

    Tests pass ``html_fixture``. Smoke may set ``live=True``.
    """
    symbol = secid.strip().upper()
    ref = CBR_CREDIT_ORG_BY_SECID.get(symbol)
    if ref is None:
        return None
    if html_fixture is not None:
        return parse_cbr_reports_index_html(
            html_fixture,
            ogrn=ref.ogrn,
        )
    if not live:
        return None
    html = fetch_cbr_reports_index_html(ref.ogrn)
    return parse_cbr_reports_index_html(html, ogrn=ref.ogrn)


def build_bank_fi_fundamental_snapshot(
    *,
    secid: str,
    instrument_id: int = 0,
    as_of: date | None = None,
    known_at: date | datetime | None = None,
    period_end: date | None = None,
    bank_metrics: Mapping[str, Any] | None = None,
    cbr_catalog: Mapping[str, Any] | CbrCatalogIndex | None = None,
    load_cbr_catalog_live: bool = False,
    cbr_html_fixture: str | None = None,
) -> FundamentalSnapshotV1:
    """Build an honest bank/FI FundamentalSnapshotV1.

    Never substitutes industrial FNS RAS ratios. SBER receives BANK_FI semantics
    with PARTIAL/NOT_AVAILABLE status unless explicit bank metrics are supplied.
    """
    catalog_payload: dict[str, Any] | None
    if isinstance(cbr_catalog, CbrCatalogIndex):
        catalog_payload = cbr_catalog.to_dict()
    elif isinstance(cbr_catalog, Mapping):
        catalog_payload = dict(cbr_catalog)
    else:
        loaded = maybe_load_cbr_catalog(
            secid,
            live=load_cbr_catalog_live,
            html_fixture=cbr_html_fixture,
        )
        catalog_payload = loaded.to_dict() if loaded is not None else None

    snapshot = build_bank_fundamental_snapshot(
        secid=secid,
        instrument_id=instrument_id,
        as_of=as_of,
        known_at=known_at,
        period_end=period_end,
        bank_metrics=bank_metrics,
        cbr_catalog=catalog_payload,
    )
    if is_bank_fi_secid(secid):
        assert_no_industrial_fallback(snapshot)
    return snapshot
