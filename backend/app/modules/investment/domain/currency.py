"""Source-aware MOEX currency normalization for fixed-income ISS fields.

Canonical currency codes used by ProjectAI are ISO-like (`RUB`, `USD`, `CNY`, …)
plus explicit `UNKNOWN` when the source value is missing or unrecognized.

For the bonds board securities block used by Investment Foundation V0:

* ``FACEUNIT`` — currency of the face value / номинал (MOEX: «валюта номинала»).
  Observed OFZ use ``SUR`` for the Russian ruble. Official MOEX ISS added FACEUNIT
  as face-value currency; live OFZ rows confirm ``SUR`` ≡ ruble face.
* ``CURRENCYID`` — trading/settlement quotation currency on the board row. Frequently
  ``SUR`` even when ``FACEUNIT`` is ``USD``/``CNY``. Must NOT be treated as nominal
  currency by itself.
* ``SEC_CURRENCY`` / similar — not present on the TQOB/TQCB securities board payload
  we consume; if observed later, treat as UNKNOWN until field-specific audit exists.

Normalization of ``SUR``/``RUR`` → ``RUB`` is therefore allowed only for fields whose
semantics are confirmed as ruble aliases (FACEUNIT, and CURRENCYID when used purely
as settlement/quotation on this board — but CURRENCYID alone never decides face).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MoexCurrencyField(StrEnum):
    FACEUNIT = "FACEUNIT"
    CURRENCYID = "CURRENCYID"
    SEC_CURRENCY = "SEC_CURRENCY"
    OTHER = "OTHER"


class CanonicalCurrency(StrEnum):
    RUB = "RUB"
    USD = "USD"
    CNY = "CNY"
    EUR = "EUR"
    UNKNOWN = "UNKNOWN"


# Fields where MOEX historically encodes the Russian ruble as SUR/RUR.
_RUBLE_ALIAS_FIELDS: frozenset[MoexCurrencyField] = frozenset(
    {
        MoexCurrencyField.FACEUNIT,
        MoexCurrencyField.CURRENCYID,  # settlement/quotation on bonds boards
    }
)

_RUBLE_ALIASES = frozenset({"SUR", "RUR", "RUB"})

_KNOWN_ISO = frozenset({"USD", "CNY", "EUR", "GBP", "CHF", "JPY", "HKD", "TRY", "AED", "KZT"})


@dataclass(frozen=True, slots=True)
class CurrencyResolution:
    """Canonical currency plus provenance of the raw MOEX value."""

    canonical: str
    raw_value: str | None
    source_field: MoexCurrencyField
    role: str  # nominal | settlement_or_quotation | unknown
    display_ru: str


def display_currency_ru(canonical: str) -> str:
    if canonical == CanonicalCurrency.RUB.value:
        return "Рубли"
    if canonical == CanonicalCurrency.UNKNOWN.value:
        return "Неизвестно"
    return canonical


def normalize_moex_currency_token(
    raw: str | None,
    *,
    field: MoexCurrencyField,
) -> CurrencyResolution:
    """Normalize one MOEX currency token for a known field role."""
    if raw is None or not str(raw).strip():
        return CurrencyResolution(
            canonical=CanonicalCurrency.UNKNOWN.value,
            raw_value=None if raw is None else str(raw),
            source_field=field,
            role=_role_for(field),
            display_ru=display_currency_ru(CanonicalCurrency.UNKNOWN.value),
        )
    text = str(raw).strip().upper()
    if field in _RUBLE_ALIAS_FIELDS and text in _RUBLE_ALIASES:
        return CurrencyResolution(
            canonical=CanonicalCurrency.RUB.value,
            raw_value=str(raw).strip(),
            source_field=field,
            role=_role_for(field),
            display_ru=display_currency_ru(CanonicalCurrency.RUB.value),
        )
    if text in _KNOWN_ISO:
        return CurrencyResolution(
            canonical=text,
            raw_value=str(raw).strip(),
            source_field=field,
            role=_role_for(field),
            display_ru=display_currency_ru(text),
        )
    # Unknown token — never invent RUB.
    return CurrencyResolution(
        canonical=CanonicalCurrency.UNKNOWN.value,
        raw_value=str(raw).strip(),
        source_field=field,
        role=_role_for(field),
        display_ru=display_currency_ru(CanonicalCurrency.UNKNOWN.value),
    )


def resolve_bond_currencies(
    *,
    face_unit: str | None = None,
    currency_id: str | None = None,
    sec_currency: str | None = None,
) -> dict[str, CurrencyResolution]:
    """Resolve nominal vs settlement currencies without conflating them."""
    nominal = normalize_moex_currency_token(face_unit, field=MoexCurrencyField.FACEUNIT)
    settlement = normalize_moex_currency_token(
        currency_id, field=MoexCurrencyField.CURRENCYID
    )
    sec = normalize_moex_currency_token(sec_currency, field=MoexCurrencyField.SEC_CURRENCY)
    return {
        "nominal_currency": nominal,
        "settlement_or_quotation_currency": settlement,
        "sec_currency": sec,
    }


def resolve_nominal_currency(
    *,
    face_unit: str | None = None,
    currency_id: str | None = None,
) -> CurrencyResolution:
    """Nominal/face currency for support classification.

    Prefer FACEUNIT. Do **not** fall back to CURRENCYID for face/nominal decisions:
    on TQOB/TQCB CURRENCYID is often SUR while FACEUNIT is USD/CNY.
    Missing FACEUNIT → UNKNOWN (not RUB).
    """
    if face_unit is not None and str(face_unit).strip():
        return normalize_moex_currency_token(face_unit, field=MoexCurrencyField.FACEUNIT)
    # Explicit absence of FACEUNIT — UNKNOWN. currency_id is settlement, not face.
    _ = currency_id  # retained for call-site clarity; intentionally unused for face.
    return CurrencyResolution(
        canonical=CanonicalCurrency.UNKNOWN.value,
        raw_value=None,
        source_field=MoexCurrencyField.FACEUNIT,
        role="nominal",
        display_ru=display_currency_ru(CanonicalCurrency.UNKNOWN.value),
    )


def _role_for(field: MoexCurrencyField) -> str:
    if field is MoexCurrencyField.FACEUNIT:
        return "nominal"
    if field is MoexCurrencyField.CURRENCYID:
        return "settlement_or_quotation"
    return "unknown"
