"""Cross-source identity for the three historical pilot issuers.

The map is assembled from identifiers that already live in this repository.
An FNS INN is attached to a MOEX SECID only when both values already name that
same issuer. No network, no database, and no decision-memory writes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.modules.historical.application.enrich import (
    INDUSTRIAL_RATIO_CODES,
    industrial_ratio_allowed,
)
from app.modules.historical.sources.fns.adapter import PILOT_INN, PILOT_SECID
from app.modules.historical.sources.moex_corporate_actions.source import EXACT_ISIN
from app.modules.historical.sources.moex_market.source import PILOT_SYMBOLS
from app.modules.intelligence.banks.classification import (
    ISSUER_KIND_BANK_FI,
    ISSUER_KIND_INDUSTRIAL,
    is_bank_fi_secid,
)
from app.modules.intelligence.banks.providers import CBR_CREDIT_ORG_BY_SECID

STATUS_MATCH = "match"
STATUS_UNRESOLVED = "unresolved"
STATUS_CONFLICT = "conflict"

_SOURCE_MOEX_SECID = "backend/app/modules/historical/sources/moex_market/source.py:PILOT_SYMBOLS"
_SOURCE_FNS_INN = "backend/app/modules/historical/sources/fns/adapter.py:PILOT_INN"
_SOURCE_FNS_SECID = "backend/app/modules/historical/sources/fns/adapter.py:PILOT_SECID"
_SOURCE_CBR = "backend/app/modules/intelligence/banks/providers.py:CBR_CREDIT_ORG_BY_SECID"
_SOURCE_ISIN = "backend/app/modules/historical/sources/moex_corporate_actions/source.py:EXACT_ISIN"
_SOURCE_KIND = "backend/app/modules/intelligence/banks/classification.py:is_bank_fi_secid"

_IDENTIFIER_FIELDS = ("secid", "inn", "ogrn", "regnum", "isin")
_RATIO_KEYS = frozenset({"metric", "metric_id", "ratio", "requested_ratio"})


@dataclass(frozen=True, slots=True)
class LinkedIdentifier:
    """One identifier value copied from an existing in-repo map."""

    issuer_key: str
    field: str
    value: str
    source: str


@dataclass(frozen=True, slots=True)
class PilotIssuer:
    key: str
    secid: str
    issuer_kind: str
    inn: str | None = None
    ogrn: str | None = None
    regnum: str | None = None
    isin: str | None = None
    title: str | None = None
    inn_source: str | None = None


@dataclass(frozen=True, slots=True)
class EntityResolution:
    """A match, an unresolved result, or a conflict. Never a guessed issuer."""

    status: str
    reason: str
    issuer_key: str | None = None
    identity: dict[str, str] | None = None
    conflict_keys: tuple[str, ...] = ()
    requested_ratios: tuple[str, ...] = ()
    ratio_refused: bool = False

    def __post_init__(self) -> None:
        if self.identity is None:
            object.__setattr__(self, "identity", {})


def pilot_issuers() -> tuple[PilotIssuer, ...]:
    return tuple(pilot for pilot, _links in _catalog())


def linked_identifiers() -> tuple[LinkedIdentifier, ...]:
    """Identifier map actually taken from in-repo constants, with source paths."""
    return tuple(link for _pilot, links in _catalog() for link in links)


def resolve(
    identifiers: Mapping[str, str],
    *,
    requested_ratio: str | None = None,
) -> EntityResolution:
    """Resolve pilot identifiers to one issuer, or refuse to guess.

    ``requested_ratio`` (or a ``metric`` / ``metric_id`` / ``ratio`` entry)
    asks whether EBITDA, REVENUE, or TOTAL_DEBT may be applied. A bank match
    is refused via :func:`industrial_ratio_allowed`.
    """
    ratios = _requested_ratios(identifiers, requested_ratio)
    provided = _provided_identifiers(identifiers)
    if not provided:
        return _result(STATUS_UNRESOLVED, "no_identifier", ratios=ratios)

    pilots = pilot_issuers()
    index = _index(pilots)
    by_key = {pilot.key: pilot for pilot in pilots}
    matched: set[str] = set()
    unknown: list[str] = []
    for field, value in provided:
        owner = index[field].get(value)
        if owner is None:
            unknown.append(field)
        else:
            matched.add(owner)

    if len(matched) > 1:
        return _result(
            STATUS_CONFLICT,
            "identifiers_belong_to_different_issuers",
            conflict_keys=tuple(sorted(matched)),
            ratios=ratios,
        )
    if not matched or unknown:
        reason = "unknown_identifier" if not matched else "identifier_not_in_map"
        return _result(STATUS_UNRESOLVED, reason, ratios=ratios)

    pilot = by_key[next(iter(matched))]
    identity = _identity(pilot)
    refused = _refuses_industrial_ratios(identity, ratios)
    return _result(
        STATUS_MATCH,
        "industrial_ratio_refused" if refused else "exact",
        issuer_key=pilot.key,
        identity=identity,
        ratios=ratios,
        ratio_refused=refused,
    )


def _catalog() -> tuple[tuple[PilotIssuer, tuple[LinkedIdentifier, ...]], ...]:
    fns_secid = _normalize("secid", PILOT_SECID)
    fns_inn = _normalize("inn", PILOT_INN)
    rows: list[tuple[PilotIssuer, tuple[LinkedIdentifier, ...]]] = []
    for symbol in PILOT_SYMBOLS:
        secid = _normalize("secid", symbol)
        links: list[LinkedIdentifier] = [
            LinkedIdentifier(secid, "secid", secid, _SOURCE_MOEX_SECID),
        ]
        inn: str | None = None
        ogrn: str | None = None
        regnum: str | None = None
        isin: str | None = None
        title: str | None = None
        inn_source: str | None = None

        cbr = CBR_CREDIT_ORG_BY_SECID.get(secid)
        if cbr is not None and _normalize("secid", cbr.secid) == secid:
            inn, ogrn, regnum, title, inn_source = _link_cbr(secid, cbr, links)

        if secid == fns_secid and fns_inn:
            links.append(LinkedIdentifier(secid, "secid", secid, _SOURCE_FNS_SECID))
            if inn is None or inn == fns_inn:
                inn = fns_inn
                inn_source = "fns"
                links.append(LinkedIdentifier(secid, "inn", fns_inn, _SOURCE_FNS_INN))

        raw_isin = EXACT_ISIN.get(secid)
        if raw_isin and raw_isin.strip():
            isin = _normalize("isin", raw_isin)
            links.append(LinkedIdentifier(secid, "isin", isin, _SOURCE_ISIN))

        kind = ISSUER_KIND_BANK_FI if is_bank_fi_secid(secid) else ISSUER_KIND_INDUSTRIAL
        links.append(LinkedIdentifier(secid, "issuer_kind", kind, _SOURCE_KIND))
        pilot = PilotIssuer(
            key=secid,
            secid=secid,
            issuer_kind=kind,
            inn=inn,
            ogrn=ogrn,
            regnum=regnum,
            isin=isin,
            title=title,
            inn_source=inn_source,
        )
        rows.append((pilot, tuple(links)))
    return tuple(rows)


def _link_cbr(
    secid: str,
    cbr: object,
    links: list[LinkedIdentifier],
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    inn = _optional("inn", getattr(cbr, "inn", None))
    ogrn = _optional("ogrn", getattr(cbr, "ogrn", None))
    regnum = _optional("regnum", getattr(cbr, "regnum", None))
    title_raw = getattr(cbr, "title", None)
    title = str(title_raw).strip() if title_raw else None
    inn_source: str | None = None
    if inn is not None:
        inn_source = "cbr"
        links.append(LinkedIdentifier(secid, "inn", inn, _SOURCE_CBR))
    if ogrn is not None:
        links.append(LinkedIdentifier(secid, "ogrn", ogrn, _SOURCE_CBR))
    if regnum is not None:
        links.append(LinkedIdentifier(secid, "regnum", regnum, _SOURCE_CBR))
    if title:
        links.append(LinkedIdentifier(secid, "title", title, _SOURCE_CBR))
    return inn, ogrn, regnum, title or None, inn_source


def _index(pilots: tuple[PilotIssuer, ...]) -> dict[str, dict[str, str]]:
    index = {field: {} for field in _IDENTIFIER_FIELDS}
    for pilot in pilots:
        for field in _IDENTIFIER_FIELDS:
            raw = getattr(pilot, field)
            if not raw:
                continue
            value = _normalize(field, raw)
            current = index[field].get(value)
            if current is not None and current != pilot.key:
                raise ValueError(f"duplicate {field} {value} on {current} and {pilot.key}")
            index[field][value] = pilot.key
    return index


def _identity(pilot: PilotIssuer) -> dict[str, str]:
    identity = {"secid": pilot.secid, "issuer_kind": pilot.issuer_kind}
    for field in ("inn", "ogrn", "regnum", "isin", "title"):
        value = getattr(pilot, field)
        if value:
            identity[field] = value
    return identity


def _provided_identifiers(identifiers: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    provided: list[tuple[str, str]] = []
    for key, raw in identifiers.items():
        field = str(key).strip().lower()
        if field not in _IDENTIFIER_FIELDS or raw is None:
            continue
        value = _normalize(field, raw)
        if value:
            provided.append((field, value))
    return tuple(provided)


def _requested_ratios(
    identifiers: Mapping[str, str],
    requested_ratio: str | None,
) -> tuple[str, ...]:
    found: list[str] = []
    if requested_ratio is not None and str(requested_ratio).strip():
        found.append(str(requested_ratio).strip().upper())
    for key, raw in identifiers.items():
        if str(key).strip().lower() in _RATIO_KEYS and raw is not None and str(raw).strip():
            found.append(str(raw).strip().upper())
    return tuple(dict.fromkeys(found))


def _refuses_industrial_ratios(identity: Mapping[str, str], ratios: tuple[str, ...]) -> bool:
    industrial = [code for code in ratios if code in INDUSTRIAL_RATIO_CODES]
    if not industrial:
        return False
    return not industrial_ratio_allowed(identity)


def _result(
    status: str,
    reason: str,
    *,
    issuer_key: str | None = None,
    identity: dict[str, str] | None = None,
    conflict_keys: tuple[str, ...] = (),
    ratios: tuple[str, ...] = (),
    ratio_refused: bool = False,
) -> EntityResolution:
    return EntityResolution(
        status=status,
        reason=reason,
        issuer_key=issuer_key,
        identity=identity if identity is not None else {},
        conflict_keys=conflict_keys,
        requested_ratios=ratios,
        ratio_refused=ratio_refused,
    )


def _optional(field: str, raw: object) -> str | None:
    if raw is None:
        return None
    value = _normalize(field, raw)
    return value or None


def _normalize(field: str, raw: object) -> str:
    text = "".join(str(raw).split())
    if field in {"secid", "isin"}:
        return text.upper()
    return text


__all__ = [
    "STATUS_CONFLICT",
    "STATUS_MATCH",
    "STATUS_UNRESOLVED",
    "EntityResolution",
    "LinkedIdentifier",
    "PilotIssuer",
    "industrial_ratio_allowed",
    "linked_identifiers",
    "pilot_issuers",
    "resolve",
]
