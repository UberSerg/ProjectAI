"""Bank / FI issuer classification for Intelligence Stack V1.

Reuses the hard-deny list from FNS industrial RAS so Dataset V4 and
intelligence agree on which SECIDs must never receive industrial ratios.
"""

from __future__ import annotations

from app.modules.fundamentals.infrastructure.fns_gir_bo_provider import (
    BANK_FI_SECIDS as _FNS_BANK_FI_SECIDS,
)

# Canonical bank/FI equity SECIDs for Intelligence Stack V1.
# Keep in sync with FNS industrial hard-deny (single source of truth below).
BANK_FI_SECIDS: frozenset[str] = frozenset(_FNS_BANK_FI_SECIDS)

ISSUER_KIND_BANK_FI = "BANK_FI"
ISSUER_KIND_INDUSTRIAL = "INDUSTRIAL"
ISSUER_KIND_UNKNOWN = "UNKNOWN"


def is_bank_fi_secid(secid: str | None) -> bool:
    if not secid:
        return False
    return secid.strip().upper() in BANK_FI_SECIDS


def issuer_kind_for_secid(secid: str | None) -> str:
    if is_bank_fi_secid(secid):
        return ISSUER_KIND_BANK_FI
    if secid and secid.strip():
        return ISSUER_KIND_INDUSTRIAL
    return ISSUER_KIND_UNKNOWN
