"""Live MOEX ISS issuer identity.

The only fundamentals-adjacent MOEX endpoint the live audit accepted:
``/iss/securities.json?q={SECID}`` returns ``emitent_id`` / ``emitent_title`` /
``emitent_inn`` / ``emitent_okpo`` / ``isin`` / ``type`` per security.

Matching is exact on SECID. Fuzzy search hits are ignored, and two exact hits with
different issuers produce AMBIGUOUS rather than a choice.
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.infrastructure.market.http_client import MarketHttpClient
from app.modules.fundamentals.config import MOEX_SECURITIES_SEARCH_PATH
from app.modules.fundamentals.domain.types import (
    SOURCE_MOEX_ISS,
    IssuerIdentity,
    MappingStatus,
)

_SECURITIES_BLOCK = "securities"


def _clean(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _emitent_id(value: Any) -> int | None:
    cleaned = _clean(value)
    if cleaned is None:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_securities_search(payload: dict[str, Any], secid: str) -> IssuerIdentity:
    """Pure parser. Never invents an issuer: every failure mode has an explicit status."""
    block = payload.get(_SECURITIES_BLOCK) or {}
    columns = block.get("columns") or []
    wanted = secid.strip().upper()
    exact: list[dict[str, Any]] = []
    for values in block.get("data") or []:
        row = dict(zip(columns, values, strict=False))
        if str(row.get("secid") or "").strip().upper() == wanted:
            exact.append(row)
    if not exact:
        return IssuerIdentity(
            secid=secid,
            mapping_status=MappingStatus.UNMAPPED,
            reason="NO_EXACT_SECID_MATCH",
        )

    issuer_ids = {_emitent_id(row.get("emitent_id")) for row in exact}
    issuer_ids.discard(None)
    if len(issuer_ids) > 1:
        return IssuerIdentity(
            secid=secid,
            mapping_status=MappingStatus.AMBIGUOUS,
            reason="MULTIPLE_EMITENT_IDS",
            raw={"emitent_ids": sorted(int(i) for i in issuer_ids)},
        )

    row = exact[0]
    emitent_id = _emitent_id(row.get("emitent_id"))
    if emitent_id is None:
        return IssuerIdentity(
            secid=secid,
            mapping_status=MappingStatus.UNMAPPED,
            reason="NO_EMITENT_ID",
            isin=_clean(row.get("isin")),
            security_type=_clean(row.get("type")),
            raw=row,
        )
    return IssuerIdentity(
        secid=secid,
        mapping_status=MappingStatus.MAPPED,
        moex_emitent_id=emitent_id,
        title=_clean(row.get("emitent_title")) or _clean(row.get("name")) or secid,
        title_en=_clean(row.get("name")),
        inn=_clean(row.get("emitent_inn")),
        okpo=_clean(row.get("emitent_okpo")),
        isin=_clean(row.get("isin")),
        security_type=_clean(row.get("type")),
        raw=row,
    )


class MoexIssuerIdentityProvider:
    """IssuerIdentityProvider over live MOEX ISS."""

    source = SOURCE_MOEX_ISS

    def __init__(
        self, client: MarketHttpClient | None = None, base_url: str | None = None
    ) -> None:
        self.client = client or MarketHttpClient()
        self.base_url = (base_url or get_settings().moex_base_url).rstrip("/")

    def fetch_issuer(self, secid: str) -> IssuerIdentity:
        url = f"{self.base_url}{MOEX_SECURITIES_SEARCH_PATH}"
        response = self.client.get(
            url,
            params={
                "q": secid,
                "iss.meta": "off",
                "securities.columns": (
                    "secid,shortname,name,isin,type,emitent_id,emitent_title,"
                    "emitent_inn,emitent_okpo,is_traded,primary_boardid"
                ),
            },
        )
        return parse_securities_search(response.json(), secid)
