"""Versioned RAS line-item parser for GIR BO / balance sheet JSON.

Maps only trustworthy RAS codes to canonical metrics. Unknown schema → SOURCE_ONLY.
Never silently rescales units — scale must be explicit and consistent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.fundamentals.domain.types import (
    FactRef,
    NormalizationStatus,
    QualityStatus,
)

PARSER_VERSION = "RAS_GIR_BO_V1"

# current{code} fields from GIR BO embedded balance / financial_result blocks.
RAS_LINE_MAP_V1: dict[str, tuple[str, str]] = {
    "2110": ("REVENUE", "Выручка"),
    "2400": ("NET_INCOME", "Чистая прибыль (убыток)"),
    "1600": ("TOTAL_ASSETS", "Баланс (актив)"),
    "1300": ("TOTAL_EQUITY", "Итого капитал"),
    "1250": ("CASH_AND_EQUIVALENTS", "Денежные средства и эквиваленты"),
}

PARSER_REGISTRY: dict[str, dict[str, tuple[str, str]]] = {
    PARSER_VERSION: RAS_LINE_MAP_V1,
}


@dataclass(frozen=True, slots=True)
class ParsedRasFact:
    source_metric_code: str
    source_metric_name: str
    canonical_metric_code: str | None
    value: float | None
    normalization_status: NormalizationStatus
    unit_scale: str | None
    currency: str | None = "RUB"


@dataclass(frozen=True, slots=True)
class RasParseResult:
    parser_version: str
    facts: tuple[ParsedRasFact, ...]
    unit_scale: str | None
    rejected_scale_mismatch: bool


def detect_unit_scale(payload: dict[str, Any]) -> str | None:
    """Infer declared scale from metadata — never guess silently."""
    for key in ("unitScale", "unit_scale", "scale", "measure"):
        raw = payload.get(key)
        if raw not in (None, ""):
            return str(raw)
    # GIR BO stores monetary lines in rubles matching top-level actives when present.
    if payload.get("actives") is not None:
        return "RUB"
    return None


def _current_field(line_code: str) -> str:
    return f"current{line_code}"


def parse_ras_payload(
    payload: dict[str, Any],
    *,
    parser_version: str = PARSER_VERSION,
    expected_scale: str | None = None,
) -> RasParseResult:
    line_map = PARSER_REGISTRY.get(parser_version)
    if line_map is None:
        return RasParseResult(parser_version, (), None, False)

    declared_scale = detect_unit_scale(payload)
    rejected = False
    if expected_scale and declared_scale and expected_scale != declared_scale:
        rejected = True
        return RasParseResult(parser_version, (), declared_scale, rejected)

    facts: list[ParsedRasFact] = []
    for line_code, (canonical, title) in line_map.items():
        field = _current_field(line_code)
        if field not in payload and line_code not in payload:
            continue
        raw_value = payload.get(field, payload.get(line_code))
        value = _to_float(raw_value)
        facts.append(
            ParsedRasFact(
                source_metric_code=line_code,
                source_metric_name=title,
                canonical_metric_code=canonical,
                value=value,
                normalization_status=NormalizationStatus.NORMALIZED,
                unit_scale=declared_scale,
            )
        )

    # Lines present but unknown → SOURCE_ONLY (no fuzzy mapping).
    for key, raw_value in payload.items():
        if not str(key).startswith("current") or key in {_current_field(c) for c in line_map}:
            continue
        code = str(key)[7:]
        if code in line_map or raw_value in (None, ""):
            continue
        facts.append(
            ParsedRasFact(
                source_metric_code=code,
                source_metric_name=f"RAS line {code}",
                canonical_metric_code=None,
                value=_to_float(raw_value),
                normalization_status=NormalizationStatus.SOURCE_ONLY,
                unit_scale=declared_scale,
            )
        )

    return RasParseResult(parser_version, tuple(facts), declared_scale, rejected)


def to_fact_refs(result: RasParseResult) -> list[FactRef]:
    refs: list[FactRef] = []
    for fact in result.facts:
        metric_code = fact.canonical_metric_code or f"RAS_{fact.source_metric_code}"
        refs.append(
            FactRef(
                metric_code=metric_code,
                value=fact.value,
                normalization_status=fact.normalization_status,
                quality_status=QualityStatus.OK if fact.value is not None else QualityStatus.UNKNOWN,
                currency=fact.currency,
                unit_scale=fact.unit_scale,
                source_metric_name=f"{fact.source_metric_name} ({fact.source_metric_code})",
            )
        )
    return refs


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
