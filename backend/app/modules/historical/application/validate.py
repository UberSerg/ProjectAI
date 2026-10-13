"""Universal numerical and provenance checks for one parsed observation.

Inputs are not mutated. A missing value stays missing and is never stored
as zero. Point-in-time quality is left untouched: this module does not
upgrade an artifact or an observation to a verified publication state.
No network, database, or prospective-memory writes.
"""

from __future__ import annotations

import math
from dataclasses import replace

from app.modules.historical.domain.evidence import (
    HistoricalArtifact,
    ParsedObservation,
    RecordQuality,
)

VALUE_NOT_FINITE = "value_not_finite"
ACCEPTED_FACT_REQUIRES_EVIDENCE = "accepted_fact_requires_evidence"
ZERO_REQUIRES_EXPLICIT_ZERO_MARK = "zero_requires_explicit_zero_mark"
ISSUER_FACT_REQUIRES_IDENTITY = "issuer_fact_requires_identity"
MONETARY_METRIC_MISSING_CURRENCY = "monetary_metric_missing_currency"
CONTENT_HASH_EMPTY = "content_hash_empty"

# Money scales and quote units used by the historical adapters.
# Dimensionless units (percent, ratio, index, lot, count) are not monetary.
_MONEY_SCALE_UNITS = frozenset(
    {
        "rub",
        "thousand_rub",
        "million_rub",
        "thousands",
        "millions",
        "per_share",
        "rub_per_unit",
    }
)
_ISO_CURRENCY_CODES = frozenset(
    {"RUB", "USD", "EUR", "CNY", "GBP", "CHF", "JPY", "HKD", "TRY", "AED", "KZT"}
)
_MISSING_CURRENCY = frozenset({"", "UNKNOWN"})


def validate_observation(
    artifact: HistoricalArtifact,
    observation: ParsedObservation,
) -> ParsedObservation:
    """Return a new observation marked ACCEPTED or QUARANTINE.

    Quarantine reasons are appended to the existing limitations. The date
    rules are whatever ``artifact.chronology_errors()`` already returns.
    """
    reasons = _quarantine_reasons(artifact, observation)
    status = RecordQuality.QUARANTINE if reasons else RecordQuality.ACCEPTED
    return replace(
        observation,
        quality_status=status,
        limitations=_append_reasons(observation.limitations, reasons),
        issuer_identity=dict(observation.issuer_identity),
        extra=dict(observation.extra),
    )


def _quarantine_reasons(
    artifact: HistoricalArtifact,
    observation: ParsedObservation,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if _value_not_finite(observation.value):
        reasons.append(VALUE_NOT_FINITE)
    for code in _errors_if_accepted(observation):
        if code not in reasons:
            reasons.append(code)
    if _monetary_missing_currency(observation):
        reasons.append(MONETARY_METRIC_MISSING_CURRENCY)
    if _content_hash_empty(artifact, observation):
        reasons.append(CONTENT_HASH_EMPTY)
    for code in artifact.chronology_errors():
        if code not in reasons:
            reasons.append(code)
    return tuple(reasons)


def _errors_if_accepted(observation: ParsedObservation) -> tuple[str, ...]:
    """Domain acceptance rules, evaluated as if the fact were accepted.

    ``ParsedObservation.quality_errors`` gates evidence and issuer identity
    on ACCEPTED. Asking that question on a copy keeps the input unchanged
    and still refuses to accept a fact the domain contract rejects.
    """
    candidate = replace(
        observation,
        quality_status=RecordQuality.ACCEPTED,
        issuer_identity=dict(observation.issuer_identity),
        extra=dict(observation.extra),
    )
    return candidate.quality_errors()


def _value_not_finite(value: object) -> bool:
    if value is None:
        return False
    try:
        return not math.isfinite(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return True


def _monetary_missing_currency(observation: ParsedObservation) -> bool:
    if not _is_monetary(observation):
        return False
    if observation.currency is None:
        return True
    token = str(observation.currency).strip().upper()
    return token in _MISSING_CURRENCY


def _is_monetary(observation: ParsedObservation) -> bool:
    unit = (observation.unit or "").strip()
    if not unit:
        return False
    if unit.casefold() in _MONEY_SCALE_UNITS:
        return True
    return unit.upper() in _ISO_CURRENCY_CODES


def _content_hash_empty(artifact: HistoricalArtifact, observation: ParsedObservation) -> bool:
    return (not artifact.content_hash.strip()) or (not observation.content_hash.strip())


def _append_reasons(existing: tuple[str, ...], reasons: tuple[str, ...]) -> tuple[str, ...]:
    present = set(existing)
    added = tuple(reason for reason in reasons if reason not in present)
    return existing + added
