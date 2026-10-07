"""Honest free-source status for Russian bank / FI fundamentals.

Statuses are intentional:
- PARTIAL — public surface exists, but not a stable universe-wide metric feed
- NOT_AVAILABLE — no acceptable free programmatic metric path
- RESEARCH_ONLY — human/IR usable, not Kraken ingest
- REJECTED — paid / captcha / ToS-hostile paths (never implemented)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PROVIDER_STATUSES: frozenset[str] = frozenset(
    {"READY", "PARTIAL", "NOT_AVAILABLE", "RESEARCH_ONLY", "REJECTED"}
)


@dataclass(frozen=True, slots=True)
class BankSourceStatus:
    provider_id: str
    title: str
    status: str
    programmatic: bool
    auth: str
    notes: str
    candidate_metrics: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    evidence_urls: tuple[str, ...] = ()
    audit_date: str = "2026-10-07"

    def __post_init__(self) -> None:
        if self.status not in PROVIDER_STATUSES:
            raise ValueError(f"invalid provider status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CbrCreditOrgRef:
    """Curated MOEX SECID → CBR credit organisation identifiers (SBER probed)."""

    secid: str
    regnum: str
    ogrn: str
    inn: str | None = None
    title: str | None = None


# Only SECIDs with probed CBR identifiers. Do not invent mappings.
CBR_CREDIT_ORG_BY_SECID: dict[str, CbrCreditOrgRef] = {
    "SBER": CbrCreditOrgRef(
        secid="SBER",
        regnum="1481",
        ogrn="1027700132195",
        inn="7707083893",
        title="ПАО Сбербанк",
    ),
}


def bank_source_registry() -> tuple[BankSourceStatus, ...]:
    """Static audit registry used by snapshot lineage and docs."""
    return (
        BankSourceStatus(
            provider_id="FNS_GIR_BO_INDUSTRIAL_RAS",
            title="FNS GIR BO industrial RAS (bo.nalog.gov.ru)",
            status="NOT_AVAILABLE",
            programmatic=True,
            auth="NONE",
            notes=(
                "Industrial RAS JSON is available for many non-banks, but bank/FI "
                "SECIDs are hard-denied. SBER INN search returns 0 hits. "
                "Industrial ratios must never be applied to banks."
            ),
            candidate_metrics=(),
            limitations=(
                "BANK_FI_NOT_SUPPORTED_BY_FNS_RAS_V1",
                "industrial_ratios_forbidden_for_banks",
            ),
            evidence_urls=(
                "https://bo.nalog.gov.ru/advanced-search/organizations/search?query=7707083893",
            ),
        ),
        BankSourceStatus(
            provider_id="CBR_CREDIT_ORG_FORMS_HTML",
            title="CBR credit organisation forms 101/102/123/135 (HTML)",
            status="PARTIAL",
            programmatic=False,
            auth="NONE",
            notes=(
                "Public HTML form pages exist for SBER (regnum 1481) with multi-year "
                "coverage. No stable JSON API, no Excel export on form pages, no "
                "universe-wide SECID→regnum registry in this module. Metric extraction "
                "from HTML is intentionally not claimed as READY."
            ),
            candidate_metrics=(
                "TOTAL_ASSETS",
                "EQUITY",
                "NET_PROFIT",
                "CAPITAL_ADEQUACY",
            ),
            limitations=(
                "html_only_no_json_api",
                "no_universe_wide_regnum_map",
                "known_at_policy_not_established",
                "metric_parser_not_accepted",
            ),
            evidence_urls=(
                "https://www.cbr.ru/finorg/foinfo/reports/?ogrn=1027700132195",
                "https://www.cbr.ru/banking_sector/credit/coinfo/f101?regnum=1481&dt=2026-09-01",
            ),
        ),
        BankSourceStatus(
            provider_id="CBR_RATINGS_PORTAL",
            title="ratings.cbr.ru credit ratings",
            status="REJECTED",
            programmatic=False,
            auth="CSRF+CAPTCHA",
            notes=(
                "Public HTML UI exists, but machine JSON requires CSRF + captcha. "
                "No captcha bypass. Leave ratings UNKNOWN."
            ),
            limitations=("captcha_blocks_automation", "no_bypass"),
            evidence_urls=("https://ratings.cbr.ru/",),
        ),
        BankSourceStatus(
            provider_id="MOEX_ISS_IDENTITY",
            title="MOEX ISS issuer identity",
            status="PARTIAL",
            programmatic=True,
            auth="NONE",
            notes=(
                "Useful for SECID/ISIN/emitent identity and issuesize snapshots. "
                "Does not provide bank P&L, capital adequacy, NIM, or NPL."
            ),
            candidate_metrics=(),
            limitations=("identity_only_not_bank_fundamentals",),
            evidence_urls=(
                "https://iss.moex.com/iss/securities/SBER.json?iss.meta=off",
            ),
        ),
        BankSourceStatus(
            provider_id="ISSUER_IR_IFRS",
            title="Issuer IR IFRS/RAS filings (PDF/XLS)",
            status="RESEARCH_ONLY",
            programmatic=False,
            auth="NONE",
            notes=(
                "Sber and peers publish IFRS packs on IR sites. Access may be "
                "environment/SSL fragile; formats are issuer-specific PDFs/XLS. "
                "Not a universe-wide machine feed. No one-off PDF scrape as READY."
            ),
            candidate_metrics=(
                "NET_INTEREST_INCOME",
                "NET_FEE_INCOME",
                "NET_PROFIT",
                "EQUITY",
                "TOTAL_ASSETS",
                "LOAN_BOOK",
                "DEPOSITS",
                "NIM",
                "ROE",
                "COST_INCOME",
                "NPL_RATIO",
            ),
            limitations=(
                "issuer_specific_formats",
                "no_stable_universe_feed",
                "pdf_scrape_not_accepted_as_ready",
            ),
            evidence_urls=(
                "https://www.sberbank.com/ru/investor-relations",
            ),
        ),
        BankSourceStatus(
            provider_id="IFRS_STRUCTURED_FREE_FEED",
            title="Structured free IFRS feed for Russian banks",
            status="NOT_AVAILABLE",
            programmatic=False,
            auth="N/A",
            notes=(
                "No free structured IFRS feed found for Russian banks comparable to "
                "FNS industrial RAS JSON. FNS BFO does not cover bank FI semantics."
            ),
            limitations=("no_free_structured_ifrs_feed",),
        ),
    )


@dataclass(frozen=True, slots=True)
class ProviderProbeResult:
    provider_id: str
    status: str
    ok: bool
    detail: str
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def overall_bank_fundamentals_status(
    sources: tuple[BankSourceStatus, ...] | None = None,
) -> str:
    """Aggregate status for bank fundamentals layer.

    READY only if a metric-capable programmatic provider is READY.
    Otherwise PARTIAL when any PARTIAL source exists, else NOT_AVAILABLE.
    """
    rows = sources if sources is not None else bank_source_registry()
    if any(s.status == "READY" and s.programmatic for s in rows):
        return "READY"
    if any(s.status == "PARTIAL" for s in rows):
        return "PARTIAL"
    return "NOT_AVAILABLE"
