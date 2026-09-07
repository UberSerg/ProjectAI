"""MOEX Instrument Master classification → subtype + support_level."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Subtypes
EQUITY_COMMON = "equity_common"
EQUITY_PREFERRED = "equity_preferred"
OFZ_GOV = "ofz_gov"
CORPORATE_BOND = "corporate_bond"
MUNICIPAL_BOND = "municipal_bond"
FUND = "fund"
OTHER = "other"
INDEX = "index"

# Support levels
FULL = "FULL"
PARTIAL = "PARTIAL"
CATALOG_ONLY = "CATALOG_ONLY"
INACTIVE = "INACTIVE"

SHARE_BOARDS = frozenset({"TQBR", "TQTF", "SMAL"})
BOND_BOARDS = frozenset({"TQOB", "TQCB"})
PREFERRED_EQUITY_BOARDS = ("TQBR", "TQTF", "SMAL")


@dataclass(frozen=True, slots=True)
class Classification:
    instrument_subtype: str
    support_level: str
    asset_class: str
    reason: str


def classify_moex_row(
    *,
    secid: str,
    board: str,
    name: str | None = None,
    sec_type: str | None = None,
    isin: str | None = None,
    market: str | None = None,
    is_traded: bool | None = True,
    extra: dict[str, Any] | None = None,
) -> Classification:
    """Map one MOEX securities row to subtype + support_level.

    Does not consult research membership — catalog presence ≠ predict capability.
    """
    _ = (isin, extra)
    board_u = (board or "").strip().upper()
    secid_u = (secid or "").strip().upper()
    name_u = (name or "").upper()
    type_u = (sec_type or "").strip().upper()
    market_u = (market or "").strip().lower()

    if is_traded is False:
        subtype = _subtype_active(secid_u, board_u, name_u, type_u, market_u)
        return Classification(subtype, INACTIVE, _asset_class(subtype), "not_traded")

    if board_u == "TQTF" or "ETF" in type_u or "ПИФ" in name_u or "ETF" in name_u:
        return Classification(FUND, PARTIAL, "fund", "board_tqtf_or_fund_type")

    if board_u == "TQOB" or secid_u.startswith("SU") or "OFZ" in type_u or "ОФЗ" in name_u:
        return Classification(OFZ_GOV, PARTIAL, "bond", "gov_or_ofz")

    if board_u == "TQCB":
        if "MUNI" in type_u or "МУНИЦ" in name_u or "ОБЛ.МОСКВ" in name_u:
            return Classification(MUNICIPAL_BOND, CATALOG_ONLY, "bond", "municipal_heuristic")
        return Classification(CORPORATE_BOND, PARTIAL, "bond", "board_tqcb")

    if market_u == "bonds" or board_u in BOND_BOARDS:
        return Classification(CORPORATE_BOND, PARTIAL, "bond", "bonds_market")

    if board_u in {"SNDX", "RTSI"} or market_u == "index":
        return Classification(INDEX, CATALOG_ONLY, "index", "index_board")

    if board_u == "SMAL":
        subtype = (
            EQUITY_PREFERRED
            if _is_preferred(secid_u, name_u, type_u)
            else EQUITY_COMMON
        )
        return Classification(subtype, CATALOG_ONLY, "equity", "board_smal")

    if board_u == "TQBR" or market_u in {"", "shares", "stock"}:
        if _is_preferred(secid_u, name_u, type_u):
            return Classification(EQUITY_PREFERRED, FULL, "equity", "preferred_tqbr")
        return Classification(EQUITY_COMMON, FULL, "equity", "common_tqbr")

    return Classification(OTHER, CATALOG_ONLY, "other", "unclassified")


def _is_preferred(secid: str, name: str, sec_type: str) -> bool:
    if secid.endswith("P") and not secid.endswith("SP"):  # SBERP, TATNP, etc.
        # Prefer ending with single P after letters; SNGSP also preferred.
        pass
    if secid.endswith("P"):
        return True
    if "PREFERRED" in sec_type or "PREF" in sec_type:
        return True
    if "ПРЕФ" in name or "PREFERRED" in name:
        return True
    return False


def _subtype_active(
    secid: str, board: str, name: str, sec_type: str, market: str
) -> str:
    c = classify_moex_row(
        secid=secid,
        board=board,
        name=name,
        sec_type=sec_type,
        market=market,
        is_traded=True,
    )
    return c.instrument_subtype


def _asset_class(subtype: str) -> str:
    if subtype in {EQUITY_COMMON, EQUITY_PREFERRED}:
        return "equity"
    if subtype in {OFZ_GOV, CORPORATE_BOND, MUNICIPAL_BOND}:
        return "bond"
    if subtype == FUND:
        return "fund"
    if subtype == INDEX:
        return "index"
    return "other"


def pick_primary_board(boards: list[str]) -> str | None:
    upper = [b.strip().upper() for b in boards if b]
    for preferred in PREFERRED_EQUITY_BOARDS:
        if preferred in upper:
            return preferred
    for preferred in ("TQOB", "TQCB"):
        if preferred in upper:
            return preferred
    return upper[0] if upper else None
