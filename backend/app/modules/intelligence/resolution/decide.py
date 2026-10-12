"""Pure company/issuer resolution for one source document.

Candidates in, decision out. No database, no clocks, no network.

Deterministic identifiers are tried before text, and the first tier that
matches any candidate wins:

1. SECID / ticker as a whole token (never a substring)
2. ISIN
3. INN
4. OGRN
5. official name or known alias, exact after high-precision normalisation

Several candidates on that tier => AMBIGUOUS. Nothing matches => UNMAPPED.
The first plausible company is never chosen.

``confidence_semantic`` is a label for the association itself. It is not a
probability of profit, return, or trade success.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.fundamentals.domain.types import MappingStatus

RESOLVER_VERSION = "company-resolution-v1"

BASIS_SECID = "SECID"
BASIS_ISIN = "ISIN"
BASIS_INN = "INN"
BASIS_OGRN = "OGRN"
BASIS_NAME = "NAME"
BASIS_UNMAPPED = "UNMAPPED"

# Association quality only — not a probability of profit.
CONFIDENCE_EXACT = "exact"
CONFIDENCE_HIGH = "high"
CONFIDENCE_CONFLICT = "conflict"
CONFIDENCE_NONE = "none"

_LEGAL_PHRASES: tuple[str, ...] = (
    "публичное акционерное общество",
    "открытое акционерное общество",
    "закрытое акционерное общество",
    "акционерное общество",
    "public joint stock company",
    "open joint stock company",
    "joint stock company",
)
_LEGAL_PHRASE_RES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)") for phrase in _LEGAL_PHRASES
)
_LEGAL_TOKENS = frozenset(
    {"пао", "оао", "зао", "ао", "ооо", "pjsc", "ojsc", "cjsc", "jsc", "llc", "ltd", "plc", "inc"}
)
# Full normalised phrase only. A sector word inside a longer official name stays.
_GENERIC_NAMES = frozenset(
    {
        "банк",
        "банки",
        "банка",
        "банковский",
        "банковский сектор",
        "сектор",
        "кредитная организация",
        "кредитные организации",
        "компания",
        "акция",
        "акции",
        "обыкновенная акция",
        "обыкновенные акции",
        "привилегированная акция",
        "привилегированные акции",
        "акция обыкновенная",
        "акции обыкновенные",
        "bank",
        "banks",
        "banking",
        "banking sector",
        "share",
        "shares",
        "stock",
        "equity",
        "ordinary share",
        "ordinary shares",
        "common share",
        "common shares",
        "preferred share",
        "preferred shares",
    }
)

# Whole token: not a prefix/suffix of a longer latin word, and not the stem of
# a hyphenated series such as SBER-03. Cyrillic letters are boundaries too,
# so a ticker glued to a Russian word does not match.
_TICKER_RE = re.compile(r"(?<!\w)([A-Za-z][A-Za-z0-9]{1,15})(?![\w-])")
_ISIN_RE = re.compile(r"(?<!\w)([A-Za-z]{2}[A-Za-z0-9]{9}\d)(?!\w)")
_INN_RE = re.compile(r"(?<!\w)(\d{12}|\d{10})(?!\w)")
_OGRN_RE = re.compile(r"(?<!\w)(\d{15}|\d{13})(?!\w)")
_SECID_VALUE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,15}$")
_ISIN_VALUE_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
_INN_VALUE_RE = re.compile(r"^\d{10}(\d{2})?$")
_OGRN_VALUE_RE = re.compile(r"^\d{13}(\d{2})?$")

_MIN_NAME_CHARS = 5


@dataclass(frozen=True, slots=True)
class ResolutionCandidate:
    """One instrument already linked to an issuer by the master. Ids come from the caller."""

    instrument_id: int
    issuer_id: int
    symbol: str
    secids: tuple[str, ...] = ()
    isins: tuple[str, ...] = ()
    inns: tuple[str, ...] = ()
    ogrns: tuple[str, ...] = ()
    names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MasterIdentityRow:
    """Flat master row. The session loader builds these; tests can pass fakes."""

    instrument_id: int
    symbol: str
    instrument_name: str
    instrument_isin: str | None
    issuer_id: int
    title: str
    title_en: str | None
    inn: str | None
    issuer_metadata: Mapping[str, Any]
    external_secid: str | None
    mapping_isin: str | None
    mapping_status: str


@dataclass(frozen=True, slots=True)
class MatchedIdentifier:
    kind: str
    value: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "value": self.value}


@dataclass(frozen=True, slots=True)
class CandidateConflict:
    symbol: str
    instrument_id: int
    issuer_id: int
    matched_identifiers: tuple[MatchedIdentifier, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "instrument_id": self.instrument_id,
            "issuer_id": self.issuer_id,
            "matched_identifiers": [item.as_dict() for item in self.matched_identifiers],
        }


@dataclass(frozen=True, slots=True)
class CompanyResolution:
    status: str
    mapping_basis: str
    confidence_semantic: str
    instrument_id: int | None
    issuer_id: int | None
    matched_identifiers: tuple[MatchedIdentifier, ...]
    candidate_conflicts: tuple[CandidateConflict, ...]

    def as_metadata(self) -> dict[str, Any]:
        return {
            "resolver_version": RESOLVER_VERSION,
            "status": self.status,
            "confidence_semantic": self.confidence_semantic,
            "matched_identifiers": [item.as_dict() for item in self.matched_identifiers],
            "candidate_conflicts": [item.as_dict() for item in self.candidate_conflicts],
        }


def normalize_match_text(value: str) -> str:
    """Casefold, drop punctuation and legal-form tokens. No fuzzy edit distance."""
    text = value.casefold().replace("ё", "е")
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    for pattern in _LEGAL_PHRASE_RES:
        text = pattern.sub(" ", text)
    tokens = [token for token in text.split() if token not in _LEGAL_TOKENS]
    return " ".join(tokens)


def eligible_name(value: str) -> str | None:
    normalized = normalize_match_text(value)
    if len(normalized.replace(" ", "")) < _MIN_NAME_CHARS:
        return None
    if normalized in _GENERIC_NAMES or normalized.isdigit():
        return None
    return normalized


def resolve_company(
    text: str,
    candidates: Sequence[ResolutionCandidate],
    *,
    explicit_secids: Sequence[str] = (),
    explicit_isins: Sequence[str] = (),
    explicit_inns: Sequence[str] = (),
    explicit_ogrns: Sequence[str] = (),
) -> CompanyResolution:
    """Resolve ``text`` against ``candidates``. Pure: same inputs, same decision."""
    prepared = _merge_candidates(candidates)
    ticker_tokens = _ticker_tokens(text) | _clean_secids(explicit_secids)
    isin_tokens = _isin_tokens(text) | _clean_isins(explicit_isins)
    inn_tokens = _inn_tokens(text) | _clean_inns(explicit_inns)
    ogrn_tokens = _ogrn_tokens(text) | _clean_ogrns(explicit_ogrns)
    normalized_text = normalize_match_text(text)
    padded_text = f" {normalized_text} "

    tiers: tuple[tuple[str, str, Any], ...] = (
        (BASIS_SECID, CONFIDENCE_EXACT, lambda item: _identifier_hits(item.secids, ticker_tokens)),
        (BASIS_ISIN, CONFIDENCE_EXACT, lambda item: _identifier_hits(item.isins, isin_tokens)),
        (BASIS_INN, CONFIDENCE_EXACT, lambda item: _identifier_hits(item.inns, inn_tokens)),
        (BASIS_OGRN, CONFIDENCE_EXACT, lambda item: _identifier_hits(item.ogrns, ogrn_tokens)),
        (BASIS_NAME, CONFIDENCE_HIGH, lambda item: _name_hits(item.names, padded_text)),
    )
    for basis, confidence, extract in tiers:
        hits: list[tuple[_Prepared, tuple[str, ...]]] = []
        for item in prepared:
            values = extract(item)
            if values:
                hits.append((item, values))
        if not hits:
            continue
        hits.sort(key=lambda pair: (pair[0].symbol, pair[0].instrument_id, pair[0].issuer_id))
        if len(hits) == 1:
            return _mapped(hits[0][0], basis, confidence, hits[0][1])
        return _ambiguous(basis, hits)
    return _unmapped()


def assemble_candidates(
    rows: Sequence[MasterIdentityRow],
    pit_by_instrument: Mapping[int, tuple[str, int | None]],
) -> list[ResolutionCandidate]:
    """Keep a row only when the point-in-time issuer link is MAPPED to that issuer."""
    grouped: dict[tuple[int, int], list[MasterIdentityRow]] = {}
    for row in rows:
        if row.mapping_status != MappingStatus.MAPPED.value:
            continue
        status, pit_issuer_id = pit_by_instrument.get(
            row.instrument_id, (MappingStatus.UNMAPPED.value, None)
        )
        if status != MappingStatus.MAPPED.value or pit_issuer_id is None:
            continue
        if row.issuer_id != pit_issuer_id:
            continue
        grouped.setdefault((row.instrument_id, pit_issuer_id), []).append(row)

    candidates: list[ResolutionCandidate] = []
    for instrument_id, issuer_id in sorted(grouped):
        candidates.append(_candidate_from_group(instrument_id, issuer_id, grouped[(instrument_id, issuer_id)]))
    return candidates


def ogrns_from_metadata(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    found: list[str] = []
    _take_ogrn(metadata.get("ogrn"), found)
    fns = metadata.get("fns")
    if isinstance(fns, dict):
        _take_ogrn(fns.get("ogrn"), found)
    return tuple(dict.fromkeys(found))


def names_from_identity(
    *,
    title: str | None,
    title_en: str | None,
    instrument_name: str | None,
    metadata: Mapping[str, Any],
) -> tuple[str, ...]:
    raw: list[str] = []
    for value in (title, title_en, instrument_name):
        if isinstance(value, str) and value.strip():
            raw.append(value.strip())
    _take_name(metadata.get("short_name"), raw)
    fns = metadata.get("fns")
    if isinstance(fns, dict):
        _take_name(fns.get("short_name"), raw)
    for key in ("aliases", "known_aliases"):
        value = metadata.get(key)
        if isinstance(value, str):
            _take_name(value, raw)
        elif isinstance(value, list | tuple):
            for item in value:
                _take_name(item, raw)
    return tuple(dict.fromkeys(raw))


@dataclass(frozen=True, slots=True)
class _Prepared:
    instrument_id: int
    issuer_id: int
    symbol: str
    secids: frozenset[str]
    isins: frozenset[str]
    inns: frozenset[str]
    ogrns: frozenset[str]
    names: tuple[str, ...]


def _merge_candidates(candidates: Sequence[ResolutionCandidate]) -> list[_Prepared]:
    grouped: dict[tuple[int, int], ResolutionCandidate] = {}
    for candidate in candidates:
        key = (candidate.instrument_id, candidate.issuer_id)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = candidate
            continue
        grouped[key] = ResolutionCandidate(
            instrument_id=candidate.instrument_id,
            issuer_id=candidate.issuer_id,
            symbol=existing.symbol or candidate.symbol,
            secids=_uniq((*existing.secids, *candidate.secids)),
            isins=_uniq((*existing.isins, *candidate.isins)),
            inns=_uniq((*existing.inns, *candidate.inns)),
            ogrns=_uniq((*existing.ogrns, *candidate.ogrns)),
            names=_uniq((*existing.names, *candidate.names)),
        )
    prepared: list[_Prepared] = []
    for candidate in grouped.values():
        symbol = candidate.symbol.strip().upper()
        secids = _clean_secids((symbol, *candidate.secids))
        names = tuple(
            dict.fromkeys(
                normalized
                for normalized in (eligible_name(name) for name in candidate.names)
                if normalized is not None
            )
        )
        prepared.append(
            _Prepared(
                instrument_id=candidate.instrument_id,
                issuer_id=candidate.issuer_id,
                symbol=symbol,
                secids=secids,
                isins=_clean_isins(candidate.isins),
                inns=_clean_inns(candidate.inns),
                ogrns=_clean_ogrns(candidate.ogrns),
                names=names,
            )
        )
    return prepared


def _candidate_from_group(
    instrument_id: int,
    issuer_id: int,
    rows: Sequence[MasterIdentityRow],
) -> ResolutionCandidate:
    ordered = sorted(rows, key=lambda row: (row.symbol or "", row.external_secid or ""))
    symbol = next((row.symbol.strip().upper() for row in ordered if row.symbol and row.symbol.strip()), "")
    secids = [symbol] if symbol else []
    isins: list[str] = []
    inns: list[str] = []
    ogrns: list[str] = []
    names: list[str] = []
    for row in ordered:
        if row.external_secid:
            secids.append(row.external_secid)
        if row.instrument_isin:
            isins.append(row.instrument_isin)
        if row.mapping_isin:
            isins.append(row.mapping_isin)
        if row.inn:
            inns.append(row.inn)
        ogrns.extend(ogrns_from_metadata(row.issuer_metadata))
        names.extend(
            names_from_identity(
                title=row.title,
                title_en=row.title_en,
                instrument_name=row.instrument_name,
                metadata=row.issuer_metadata,
            )
        )
    return ResolutionCandidate(
        instrument_id=instrument_id,
        issuer_id=issuer_id,
        symbol=symbol,
        secids=_uniq(secids),
        isins=_uniq(isins),
        inns=_uniq(inns),
        ogrns=_uniq(ogrns),
        names=_uniq(names),
    )


def _mapped(
    candidate: _Prepared,
    basis: str,
    confidence: str,
    values: tuple[str, ...],
) -> CompanyResolution:
    identifiers = tuple(MatchedIdentifier(basis, value) for value in values)
    return CompanyResolution(
        status=MappingStatus.MAPPED.value,
        mapping_basis=basis,
        confidence_semantic=confidence,
        instrument_id=candidate.instrument_id,
        issuer_id=candidate.issuer_id,
        matched_identifiers=identifiers,
        candidate_conflicts=(),
    )


def _ambiguous(basis: str, hits: Sequence[tuple[_Prepared, tuple[str, ...]]]) -> CompanyResolution:
    conflicts = tuple(
        CandidateConflict(
            symbol=candidate.symbol,
            instrument_id=candidate.instrument_id,
            issuer_id=candidate.issuer_id,
            matched_identifiers=tuple(MatchedIdentifier(basis, value) for value in values),
        )
        for candidate, values in hits
    )
    flat: list[MatchedIdentifier] = []
    for conflict in conflicts:
        for identifier in conflict.matched_identifiers:
            if identifier not in flat:
                flat.append(identifier)
    return CompanyResolution(
        status=MappingStatus.AMBIGUOUS.value,
        mapping_basis=basis,
        confidence_semantic=CONFIDENCE_CONFLICT,
        instrument_id=None,
        issuer_id=None,
        matched_identifiers=tuple(flat),
        candidate_conflicts=conflicts,
    )


def _unmapped() -> CompanyResolution:
    return CompanyResolution(
        status=MappingStatus.UNMAPPED.value,
        mapping_basis=BASIS_UNMAPPED,
        confidence_semantic=CONFIDENCE_NONE,
        instrument_id=None,
        issuer_id=None,
        matched_identifiers=(),
        candidate_conflicts=(),
    )


def _identifier_hits(known: frozenset[str], found: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted(known & found))


def _name_hits(names: tuple[str, ...], padded_text: str) -> tuple[str, ...]:
    return tuple(name for name in names if f" {name} " in padded_text)


def _ticker_tokens(text: str) -> frozenset[str]:
    return frozenset(match.group(1).upper() for match in _TICKER_RE.finditer(text))


def _isin_tokens(text: str) -> frozenset[str]:
    return frozenset(match.group(1).upper() for match in _ISIN_RE.finditer(text))


def _inn_tokens(text: str) -> frozenset[str]:
    return frozenset(match.group(1) for match in _INN_RE.finditer(text))


def _ogrn_tokens(text: str) -> frozenset[str]:
    return frozenset(match.group(1) for match in _OGRN_RE.finditer(text))


def _clean_secids(values: Sequence[str]) -> frozenset[str]:
    cleaned: set[str] = set()
    for value in values:
        token = value.strip().upper()
        if _SECID_VALUE_RE.fullmatch(token):
            cleaned.add(token)
    return frozenset(cleaned)


def _clean_isins(values: Sequence[str]) -> frozenset[str]:
    cleaned: set[str] = set()
    for value in values:
        token = value.strip().upper()
        if _ISIN_VALUE_RE.fullmatch(token):
            cleaned.add(token)
    return frozenset(cleaned)


def _clean_inns(values: Sequence[str]) -> frozenset[str]:
    cleaned: set[str] = set()
    for value in values:
        token = value.strip()
        if _INN_VALUE_RE.fullmatch(token):
            cleaned.add(token)
    return frozenset(cleaned)


def _clean_ogrns(values: Sequence[str]) -> frozenset[str]:
    cleaned: set[str] = set()
    for value in values:
        token = value.strip()
        if _OGRN_VALUE_RE.fullmatch(token):
            cleaned.add(token)
    return frozenset(cleaned)


def _uniq(values: Sequence[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    for value in values:
        text = value.strip()
        if text and text not in ordered:
            ordered.append(text)
    return tuple(ordered)


def _take_ogrn(value: object, found: list[str]) -> None:
    if isinstance(value, str):
        token = value.strip()
        if _OGRN_VALUE_RE.fullmatch(token):
            found.append(token)


def _take_name(value: object, found: list[str]) -> None:
    if isinstance(value, str) and value.strip():
        found.append(value.strip())
