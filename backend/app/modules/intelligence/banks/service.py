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
from app.modules.intelligence.banks.cbr_soap import (
    PROVIDER_ID as CBR_SOAP_PROVIDER_ID,
)
from app.modules.intelligence.banks.cbr_soap import (
    CbrSoapParseResult,
    fetch_cbr_soap_bundle,
    parse_cbr_soap_metrics,
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


def _soap_result_for_secid(
    secid: str,
    *,
    live: bool,
    fixtures: Mapping[str, str] | None,
) -> CbrSoapParseResult | None:
    """Parse SOAP fixtures, or optionally fetch. Never invents metrics."""
    symbol = secid.strip().upper()
    ref = CBR_CREDIT_ORG_BY_SECID.get(symbol)
    if ref is None or ref.ogrn is None:
        return None
    bundle = dict(fixtures) if fixtures is not None else None
    fetch_limitation: str | None = None
    if bundle is None and live:
        try:
            bundle = fetch_cbr_soap_bundle(regnum=ref.regnum)
        except Exception as exc:  # noqa: BLE001 — live probe must not invent metrics
            fetch_limitation = f"cbr_soap_fetch_failed:{type(exc).__name__}"
            bundle = {}
    if bundle is None:
        return None
    parsed = parse_cbr_soap_metrics(
        form123_xml=bundle.get("form123"),
        form135_xml=bundle.get("form135"),
        form102_xml=bundle.get("form102"),
        form102_enum_xml=bundle.get("form102_enum"),
        identity_xml=bundle.get("identity"),
        expected_regnum=ref.regnum,
        expected_ogrn=ref.ogrn,
    )
    if fetch_limitation is None:
        return parsed
    return CbrSoapParseResult(
        metrics={},
        period_end=None,
        limitations=(*parsed.limitations, fetch_limitation),
        facts=parsed.facts,
    )


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
    cbr_soap_fixtures: Mapping[str, str] | None = None,
    load_cbr_soap_live: bool = False,
) -> FundamentalSnapshotV1:
    """Build an honest bank/FI FundamentalSnapshotV1.

    Never substitutes industrial FNS RAS ratios. SOAP fixtures or an optional
    live fetch may supply PARTIAL SBER metrics (own funds, N1.0, RAS profit).
    known_at is whatever the caller passes; it is never copied from period_end.
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

    soap = _soap_result_for_secid(
        secid,
        live=load_cbr_soap_live,
        fixtures=cbr_soap_fixtures,
    )
    merged_metrics: dict[str, Any] = {}
    extra_facts: tuple[dict[str, Any], ...] | None = None
    extra_limitations: tuple[str, ...] | None = None
    provider_override: str | None = None
    resolved_period_end = period_end
    if soap is not None:
        merged_metrics.update(soap.metrics)
        extra_facts = soap.facts
        extra_limitations = soap.limitations
        provider_override = CBR_SOAP_PROVIDER_ID
        if resolved_period_end is None:
            resolved_period_end = soap.period_end
    if bank_metrics:
        merged_metrics.update(dict(bank_metrics))

    snapshot = build_bank_fundamental_snapshot(
        secid=secid,
        instrument_id=instrument_id,
        as_of=as_of,
        known_at=known_at,
        period_end=resolved_period_end,
        bank_metrics=merged_metrics or None,
        cbr_catalog=catalog_payload,
        provider_override=provider_override,
        extra_facts=extra_facts,
        extra_limitations=extra_limitations,
    )
    if is_bank_fi_secid(secid):
        assert_no_industrial_fallback(snapshot)
    return snapshot
