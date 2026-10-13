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
            "MOEX-02",
            "historical.sources.moex_listing",
            "BLOCKED",
            "listing.json has history windows only; no identifier-change journal",
        ),
        SourceRegistration(
            "MOEX-03",
            "historical.sources.moex_listing",
            "PARTIAL",
            "35 share boards and 51 SBER board windows; snapshot, not a board history",
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
            "MOEX-08",
            "historical.sources.moex_bonds",
            "READY",
            "61 TQOB names and 29 sessions of RU000A10DQA8; catalogue RESEARCH_ONLY, history PIT_PROXY",
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
            "IR-01",
            "historical.sources.issuer_statements",
            "READY",
            "seven IFRS lines from the Lukoil 2021 databook, RESEARCH_ONLY",
        ),
        SourceRegistration(
            "IR-03",
            "historical.sources.issuer_operating",
            "PARTIAL",
            "20 Magnit operating figures for 2021-2025, RESEARCH_ONLY; no publication date",
        ),
        SourceRegistration(
            "IR-07",
            "historical.sources.issuer_statements",
            "BLOCKED",
            "the same databook has no RAS statements; zero invented rows",
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
            "ROS-02",
            "historical.sources.macro",
            "PARTIAL",
            "72 industrial-production months, 2017-2022; 2023-2026 returned zero rows",
        ),
        SourceRegistration(
            "ROS-03",
            "historical.sources.macro",
            "PARTIAL",
            "30 unemployment points, 2017-2022; later years absent",
        ),
        SourceRegistration(
            "ROS-04",
            "historical.sources.macro",
            "PARTIAL",
            "passport update date is not a per-point publication time",
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
