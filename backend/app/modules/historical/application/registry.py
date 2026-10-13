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
            "RUONIA DateUpdate can be PIT_VERIFIED",
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
            "MOEX-06",
            "historical.sources.moex_corporate_actions",
            "BLOCKED",
            "CCI dividends are subscriber-only; zero payout rows",
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
    )


def registration_for(source_id: str) -> SourceRegistration | None:
    for item in registered_sources():
        if item.source_id == source_id:
            return item
    return None
