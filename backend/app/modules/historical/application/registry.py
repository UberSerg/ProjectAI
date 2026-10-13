"""Registry of historical adapters that actually exist in this tree.

Status values describe the verified pilot, not a completed archive.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceRegistration:
    source_id: str
    adapter: str
    pilot_status: str
    pit_note: str


def registered_sources() -> tuple[SourceRegistration, ...]:
    return (
        SourceRegistration(
            "CBR-01",
            "historical.sources.cbr_rates",
            "READY",
            "key rate sample is RESEARCH_ONLY; no publication timestamp",
        ),
        SourceRegistration(
            "CBR-02",
            "historical.sources.cbr_rates",
            "READY",
            "USD/RUB sample is RESEARCH_ONLY",
        ),
        SourceRegistration(
            "CBR-03",
            "historical.sources.cbr_rates",
            "READY",
            "RUONIA DateUpdate is a feed stamp, so the sample stays PIT_PROXY",
        ),
        SourceRegistration(
            "CBR-04",
            "historical.sources.cbr_macro",
            "READY",
            "16 CBR gold accounting prices, 2024-01-10..2024-01-31, RESEARCH_ONLY",
        ),
        SourceRegistration(
            "CBR-05",
            "historical.sources.cbr_reviews",
            "BLOCKED",
            "banking-sector review catalog returned HTTP 404; zero metrics",
        ),
        SourceRegistration(
            "CBR-06",
            "historical.sources.cbr_banks",
            "PARTIAL",
            "form 101 returned no metrics",
        ),
        SourceRegistration(
            "CBR-07",
            "historical.sources.cbr_banks",
            "PARTIAL",
            "one live net-profit slice, PIT_PROXY",
        ),
        SourceRegistration(
            "CBR-08",
            "historical.sources.cbr_banks",
            "PARTIAL",
            "one live equity slice, PIT_PROXY",
        ),
        SourceRegistration(
            "CBR-09",
            "historical.sources.cbr_banks",
            "PARTIAL",
            "one live N1.0 slice, PIT_PROXY",
        ),
        SourceRegistration(
            "CBR-10",
            "historical.sources.cbr_news",
            "READY",
            "14 current press RSS items with pubDate, PIT_PROXY; not an archive",
        ),
        SourceRegistration(
            "CBR-11",
            "historical.sources.cbr_news",
            "READY",
            "20 of 1000 regulatory RSS items, PIT_PROXY; act files not downloaded",
        ),
        SourceRegistration(
            "MOEX-01",
            "historical.sources.moex_market",
            "READY",
            "first 100 of 512 TQBR rows; catalogue is RESEARCH_ONLY",
        ),
        SourceRegistration(
            "MOEX-04",
            "historical.sources.moex_market",
            "READY",
            "29 sessions for SBER, LKOH, MGNT; PIT_PROXY",
        ),
        SourceRegistration(
            "MOEX-05",
            "historical.sources.moex_index",
            "READY",
            "30 IMOEX sessions, 2026-09-01..2026-10-12, PIT_PROXY",
        ),
        SourceRegistration(
            "MOEX-06",
            "historical.sources.moex_corporate_actions",
            "BLOCKED",
            "CCI dividends are subscriber-only; zero payout rows",
        ),
        SourceRegistration(
            "MOEX-07",
            "historical.sources.moex_announcements",
            "PARTIAL",
            "20 IR-calendar rows without published_at; corp-actions stay subscriber-only",
        ),
        SourceRegistration(
            "FNS-01",
            "historical.sources.fns",
            "READY",
            "Lukoil FY2021-2025; mixed PIT_PROXY and RESEARCH_ONLY",
        ),
        SourceRegistration(
            "FNS-02",
            "historical.sources.fns",
            "READY",
            "identity by INN and OGRN for one industrial issuer",
        ),
        SourceRegistration(
            "IR-05",
            "historical.sources.issuer_dividends",
            "PARTIAL",
            "30 Lukoil rows with registry date and per-share amount; no payment date",
        ),
        SourceRegistration(
            "FNS-03",
            "historical.sources.fns",
            "BLOCKED",
            "public GIR BO returns only the latest correction; prior revisions are absent",
        ),
        SourceRegistration(
            "ROS-01",
            "historical.sources.macro",
            "PARTIAL",
            "72 CPI months, 2017-2022, RESEARCH_ONLY",
        ),
        SourceRegistration(
            "INT-01",
            "historical.sources.macro",
            "BLOCKED",
            "EIA petroleum API_KEY_MISSING",
        ),
        SourceRegistration(
            "INT-02",
            "historical.sources.macro",
            "BLOCKED",
            "EIA natural gas API_KEY_MISSING",
        ),
        SourceRegistration(
            "INT-03",
            "historical.sources.official_macro",
            "READY",
            "88 CBR precious-metal quotes, September 2026, RESEARCH_ONLY",
        ),
        SourceRegistration(
            "INT-04",
            "historical.sources.official_macro",
            "PARTIAL",
            "metal codes mapped from the CBR table; the XML has no unit",
        ),
        SourceRegistration(
            "DISC-01",
            "historical.sources.disclosure",
            "BLOCKED",
            "e-disclosure anti-bot shell is not a filing",
        ),
        SourceRegistration(
            "DISC-02",
            "historical.sources.disclosure",
            "BLOCKED",
            "no machine-readable disclosure feed without a challenge",
        ),
        SourceRegistration(
            "NEWS-02",
            "historical.sources.disclosure",
            "PARTIAL",
            "20 MOEX headlines with published_at; bodies not fetched",
        ),
        SourceRegistration(
            "NEWS-01",
            "historical.sources.issuer_news",
            "READY",
            "20 Lukoil press cards, 2026-05-13..2026-10-09, PIT_PROXY, bodies not stored",
        ),
        SourceRegistration(
            "NEWS-03",
            "historical.sources.issuer_news",
            "READY",
            "same 20 Lukoil cards; Sber TLS failed and Magnit had no dated list",
        ),
    )


def registration_for(source_id: str) -> SourceRegistration | None:
    for item in registered_sources():
        if item.source_id == source_id:
            return item
    return None


def require_registered(source_id: str) -> SourceRegistration:
    """Return the verified registration, or raise when the source is unknown."""
    found = registration_for(source_id)
    if found is None:
        raise ValueError(f"unknown historical source: {source_id}")
    return found
