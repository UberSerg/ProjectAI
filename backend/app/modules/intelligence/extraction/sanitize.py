"""Post-validation for extractor output — reject prompt-injection / action obedience."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from app.modules.intelligence.contracts.snapshots_domain import SourceDocumentV1
from app.modules.intelligence.extraction.schema import (
    DIRECTION_VALUES,
    EVENT_TYPES,
    EXTRACTOR_VERSION,
    FORBIDDEN_ACTION_TOKENS,
    FORBIDDEN_PERSISTENCE_KEYS,
    LLM_CLAIM_KEYS,
    LLM_EVENT_KEYS,
    LLM_EXTRACTOR_VERSION,
    LLM_METADATA_KEYS,
    LLM_NUMERICAL_KEYS,
    LLM_PAYLOAD_KEYS,
    MATERIALITY_VALUES,
    MAX_LLM_INPUT_CHARS,
    MAX_LLM_OUTPUT_CHARS,
    ExtractedClaimV1,
    ExtractedEventV1,
    ExtractionResultV1,
    NumericalFactV1,
)

_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|system)\s+instructions", re.I),
    re.compile(r"mark\s+this\s+company\s+buy", re.I),
    re.compile(r"\b(you\s+must|always)\s+(buy|sell)\b", re.I),
)

_ACTION_IN_TEXT = re.compile(
    r"\b(BUY|SELL|EXECUTE|ORDER|TRADE_INTENT)\b",
    re.I,
)
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.I)


class _LlmSchemaError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def document_contains_injection(text: str | None) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _INJECTION_PATTERNS)


def strip_forbidden_keys(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop hidden chain-of-thought keys from a provider payload."""
    return {k: v for k, v in payload.items() if k not in FORBIDDEN_PERSISTENCE_KEYS}


def strip_forbidden_tree(value: Any) -> Any:
    """Drop chain-of-thought keys at every object level. Values are not executed."""
    if isinstance(value, dict):
        return {
            key: strip_forbidden_tree(item)
            for key, item in value.items()
            if key not in FORBIDDEN_PERSISTENCE_KEYS
        }
    if isinstance(value, list):
        return [strip_forbidden_tree(item) for item in value]
    return value


def _normalize_direction(raw: Any) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip().upper()
    if value in FORBIDDEN_ACTION_TOKENS:
        return None
    if value in DIRECTION_VALUES:
        return value
    return None


def claim_looks_like_action(text: str) -> bool:
    upper = text.upper()
    if "IGNORE PREVIOUS" in upper or "IGNORE ALL PREVIOUS" in upper:
        return True
    if _ACTION_IN_TEXT.search(text) and any(
        token in upper for token in ("MARK", "MUST", "INSTRUCTION", "OBEY", "OVERRIDE")
    ):
        return True
    # Bare trading imperative without factual framing.
    if re.search(r"^\s*(BUY|SELL)\b", text, re.I):
        return True
    return False


def sanitize_provider_payload(
    *,
    source_document_id: str,
    provider_name: str,
    payload: dict[str, Any],
    source_text: str | None,
) -> ExtractionResultV1:
    """Validate provider JSON-like payload into ExtractionResultV1 or REJECTED."""
    clean = strip_forbidden_keys(payload)
    limitations: list[str] = []
    if document_contains_injection(source_text):
        limitations.append("source_prompt_injection_detected")

    raw_events = clean.get("events") or []
    if not isinstance(raw_events, list):
        return ExtractionResultV1(
            status="REJECTED",
            source_document_id=source_document_id,
            extractor_version=EXTRACTOR_VERSION,
            provider_name=provider_name,
            events=(),
            limitations=("invalid_events_payload", *limitations),
            summary="Provider payload rejected",
            metadata={"fabricated": False},
        )

    events: list[ExtractedEventV1] = []
    rejected_action_obedience = False

    for raw in raw_events:
        if not isinstance(raw, dict):
            limitations.append("skipped_non_object_event")
            continue
        raw = strip_forbidden_keys(raw)
        event_type = str(raw.get("event_type", "OTHER")).upper()
        if event_type not in EVENT_TYPES:
            event_type = "OTHER"
            limitations.append("event_type_coerced_to_OTHER")

        materiality = str(raw.get("materiality", "UNKNOWN")).upper()
        if materiality not in MATERIALITY_VALUES:
            materiality = "UNKNOWN"

        direction = _normalize_direction(raw.get("direction"))
        if direction is None:
            # Provider tried BUY/SELL or unknown — do not obey.
            if str(raw.get("direction", "")).strip().upper() in FORBIDDEN_ACTION_TOKENS:
                rejected_action_obedience = True
                limitations.append("rejected_trading_action_direction")
            direction = "UNKNOWN"

        claims: list[ExtractedClaimV1] = []
        for idx, claim_raw in enumerate(raw.get("claims") or []):
            if not isinstance(claim_raw, dict):
                continue
            claim_raw = strip_forbidden_keys(claim_raw)
            text = str(claim_raw.get("text") or "").strip()
            if not text:
                continue
            if claim_looks_like_action(text):
                rejected_action_obedience = True
                limitations.append("rejected_action_claim")
                continue
            evidence = str(claim_raw.get("evidence_fragment") or "").strip()
            if not evidence:
                limitations.append("claim_missing_evidence")
                continue
            doc_id = str(claim_raw.get("source_document_id") or source_document_id).strip()
            if doc_id != source_document_id:
                limitations.append("claim_document_id_mismatch_corrected")
                doc_id = source_document_id
            conf = float(claim_raw.get("confidence", 0.0))
            conf = min(1.0, max(0.0, conf))
            numerical = None
            num_raw = claim_raw.get("numerical")
            if isinstance(num_raw, dict):
                numerical = _parse_numerical(num_raw, limitations)
            try:
                claims.append(
                    ExtractedClaimV1(
                        claim_id=str(claim_raw.get("claim_id") or f"c{idx+1}"),
                        text=text,
                        source_document_id=doc_id,
                        evidence_fragment=evidence,
                        extractor_version=str(
                            claim_raw.get("extractor_version") or EXTRACTOR_VERSION
                        ),
                        confidence=conf,
                        numerical=numerical,
                        claim_type=str(claim_raw.get("claim_type") or "FACTUAL"),
                    )
                )
            except ValueError as exc:
                limitations.append(f"claim_rejected:{exc}")

        if rejected_action_obedience and not claims:
            # Injection-only document: keep an honest empty/rejected event set.
            continue

        rationale = str(raw.get("rationale") or "").strip()
        if claim_looks_like_action(rationale):
            rationale = "Evidence-based extraction only; trading instructions ignored."
            limitations.append("rationale_sanitized")

        conf_event = raw.get("confidence")
        conf_val = None if conf_event is None else min(1.0, max(0.0, float(conf_event)))
        events.append(
            ExtractedEventV1(
                event_type=event_type,  # type: ignore[arg-type]
                materiality=materiality,  # type: ignore[arg-type]
                direction=direction,  # type: ignore[arg-type]
                affected_horizon=str(raw.get("affected_horizon") or "unspecified"),
                claims=tuple(claims),
                rationale=rationale,
                confidence=conf_val,
                limitations=tuple(
                    x for x in (raw.get("limitations") or []) if isinstance(x, str)
                ),
            )
        )

    status: str
    if rejected_action_obedience and not events:
        status = "REJECTED"
        limitations.append("prompt_injection_not_obeyed")
    elif not events:
        status = "EMPTY"
        limitations.append("empty_ok")
    else:
        status = "OK"

    summary = clean.get("summary")
    if isinstance(summary, str) and claim_looks_like_action(summary):
        summary = "Structured extraction completed; untrusted instructions ignored."
        limitations.append("summary_sanitized")

    meta = strip_forbidden_keys(dict(clean.get("metadata") or {}))
    meta["fabricated"] = False
    if rejected_action_obedience:
        meta["prompt_injection_obeyed"] = False

    return ExtractionResultV1(
        status=status,  # type: ignore[arg-type]
        source_document_id=source_document_id,
        extractor_version=EXTRACTOR_VERSION,
        provider_name=provider_name,
        events=tuple(events),
        limitations=tuple(dict.fromkeys(limitations)),
        summary=summary if isinstance(summary, str) else None,
        metadata=meta,
    )


def _parse_numerical(
    num_raw: dict[str, Any], limitations: list[str]
) -> NumericalFactV1 | None:
    status = str(num_raw.get("status") or "OK").upper()
    if status not in {"OK", "UNKNOWN", "REJECTED"}:
        status = "UNKNOWN"
    value = num_raw.get("value")
    evidence = str(num_raw.get("evidence_fragment") or "").strip() or None
    if status == "OK" and (value is None or not evidence):
        limitations.append("numerical_unsupported")
        return NumericalFactV1(
            value=None,
            unit=num_raw.get("unit"),
            currency=num_raw.get("currency"),
            period=num_raw.get("period"),
            evidence_fragment=evidence,
            status="UNKNOWN",
        )
    try:
        return NumericalFactV1(
            value=None if value is None else float(value),
            unit=num_raw.get("unit"),
            currency=num_raw.get("currency"),
            period=num_raw.get("period"),
            evidence_fragment=evidence,
            status=status,
        )
    except (TypeError, ValueError):
        limitations.append("numerical_parse_failed")
        return NumericalFactV1(value=None, status="REJECTED", evidence_fragment=evidence)


def interpret_llm_output(
    *,
    document: SourceDocumentV1,
    raw_output: str,
    provider_name: str,
    source_text: str | None = None,
    extractor_version: str = LLM_EXTRACTOR_VERSION,
) -> ExtractionResultV1:
    """Parse one model string into ExtractionResultV1. Malformed JSON is REJECTED.

    The model text is data. It is not evaluated, and URLs inside it are not fetched.
    """
    source = document.raw_text if source_text is None else source_text
    source = source or ""
    limitations: list[str] = []
    if len(source) > MAX_LLM_INPUT_CHARS:
        source = source[:MAX_LLM_INPUT_CHARS]
        limitations.append("input_truncated")
    if len(raw_output) > MAX_LLM_OUTPUT_CHARS:
        limitations.append("output_bound_exceeded")
        return _llm_rejected(
            source_document_id=document.id,
            provider_name=provider_name,
            extractor_version=extractor_version,
            limitations=limitations,
            source_text=source,
        )
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError:
        limitations.append("malformed_json")
        return _llm_rejected(
            source_document_id=document.id,
            provider_name=provider_name,
            extractor_version=extractor_version,
            limitations=limitations,
            source_text=source,
        )
    return validate_llm_payload(
        source_document_id=document.id,
        provider_name=provider_name,
        payload=payload,
        source_text=source,
        extractor_version=extractor_version,
        limitations=limitations,
    )


def validate_llm_payload(
    *,
    source_document_id: str,
    provider_name: str,
    payload: Any,
    source_text: str | None,
    extractor_version: str = LLM_EXTRACTOR_VERSION,
    limitations: list[str] | None = None,
) -> ExtractionResultV1:
    """Accept only the strict schema, exact evidence spans, and non-action labels."""
    notes = list(limitations or [])
    source = source_text or ""
    if document_contains_injection(source):
        notes.append("source_prompt_injection_detected")
    if not isinstance(payload, dict):
        notes.append("malformed_json")
        return _llm_rejected(
            source_document_id=source_document_id,
            provider_name=provider_name,
            extractor_version=extractor_version,
            limitations=notes,
            source_text=source,
        )
    clean = strip_forbidden_tree(payload)
    if not isinstance(clean, dict):
        notes.append("malformed_json")
        return _llm_rejected(
            source_document_id=source_document_id,
            provider_name=provider_name,
            extractor_version=extractor_version,
            limitations=notes,
            source_text=source,
        )
    try:
        events, action_rejected, span_rejected = _strict_events(
            clean,
            source_document_id=source_document_id,
            source_text=source,
            extractor_version=extractor_version,
            notes=notes,
        )
    except _LlmSchemaError as exc:
        notes.append(exc.reason)
        return _llm_rejected(
            source_document_id=source_document_id,
            provider_name=provider_name,
            extractor_version=extractor_version,
            limitations=notes,
            source_text=source,
        )

    if events:
        status = "OK"
    elif action_rejected or span_rejected:
        status = "REJECTED"
        if action_rejected:
            notes.append("prompt_injection_not_obeyed")
    else:
        status = "EMPTY"
        notes.append("empty_ok")

    summary = clean.get("summary")
    summary_text = summary if isinstance(summary, str) else None
    if summary_text and (
        claim_looks_like_action(summary_text) or _has_invented_url(summary_text, source)
    ):
        summary_text = "Structured extraction completed; untrusted instructions ignored."
        notes.append("summary_sanitized")

    meta_raw = clean.get("metadata") or {}
    meta = strip_forbidden_keys(meta_raw) if isinstance(meta_raw, dict) else {}
    meta = {key: value for key, value in meta.items() if key in LLM_METADATA_KEYS}
    meta["fabricated"] = False
    if action_rejected or document_contains_injection(source):
        meta["prompt_injection_obeyed"] = False

    return ExtractionResultV1(
        status=status,  # type: ignore[arg-type]
        source_document_id=source_document_id,
        extractor_version=extractor_version,
        provider_name=provider_name,
        events=tuple(events),
        limitations=tuple(dict.fromkeys(notes)),
        summary=summary_text,
        metadata=meta,
    )


def _strict_events(
    clean: dict[str, Any],
    *,
    source_document_id: str,
    source_text: str,
    extractor_version: str,
    notes: list[str],
) -> tuple[list[ExtractedEventV1], bool, bool]:
    unknown_top = set(clean) - LLM_PAYLOAD_KEYS
    if unknown_top:
        raise _LlmSchemaError("unknown_fields")
    meta = clean.get("metadata", {})
    if meta is None:
        meta = {}
    if not isinstance(meta, dict) or set(meta) - LLM_METADATA_KEYS:
        raise _LlmSchemaError("unknown_fields")
    raw_events = clean.get("events", [])
    if not isinstance(raw_events, list):
        raise _LlmSchemaError("malformed_json")

    events: list[ExtractedEventV1] = []
    action_rejected = False
    span_rejected = False
    for raw in raw_events:
        if not isinstance(raw, dict):
            raise _LlmSchemaError("malformed_json")
        event, event_action, event_span = _strict_event(
            raw,
            source_document_id=source_document_id,
            source_text=source_text,
            extractor_version=extractor_version,
            notes=notes,
        )
        action_rejected = action_rejected or event_action
        span_rejected = span_rejected or event_span
        if event is not None:
            events.append(event)
    return events, action_rejected, span_rejected


def _strict_event(
    raw: dict[str, Any],
    *,
    source_document_id: str,
    source_text: str,
    extractor_version: str,
    notes: list[str],
) -> tuple[ExtractedEventV1 | None, bool, bool]:
    data = dict(raw)
    if "facts" in data:
        if "claims" in data:
            raise _LlmSchemaError("unknown_fields")
        data["claims"] = data.pop("facts")
    if set(data) - LLM_EVENT_KEYS:
        raise _LlmSchemaError("unknown_fields")

    event_type = str(data.get("event_type", "")).strip().upper()
    if event_type not in EVENT_TYPES:
        raise _LlmSchemaError("invalid_event_type")
    materiality = str(data.get("materiality", "")).strip().upper()
    if materiality not in MATERIALITY_VALUES:
        raise _LlmSchemaError("invalid_materiality")
    direction = str(data.get("direction", "")).strip().upper()
    if direction in FORBIDDEN_ACTION_TOKENS:
        notes.append("rejected_trading_action_direction")
        return None, True, False
    if direction not in DIRECTION_VALUES:
        raise _LlmSchemaError("invalid_direction")

    entities, entity_span = _strict_entities(data.get("entities", []), source_text, notes)
    claims, action_rejected, span_rejected = _strict_claims(
        data.get("claims", []),
        source_document_id=source_document_id,
        source_text=source_text,
        extractor_version=extractor_version,
        notes=notes,
    )
    span_rejected = span_rejected or entity_span
    if not claims:
        return None, action_rejected, span_rejected

    rationale = str(data.get("rationale") or "").strip()
    if claim_looks_like_action(rationale) or _has_invented_url(rationale, source_text):
        rationale = "Evidence-based extraction only; trading instructions ignored."
        notes.append("rationale_sanitized")
    confidence = _optional_unit_interval(data.get("confidence"))
    limitations = data.get("limitations") or []
    if not isinstance(limitations, list) or any(not isinstance(item, str) for item in limitations):
        raise _LlmSchemaError("malformed_json")
    safe_limits = tuple(
        item
        for item in limitations
        if item not in FORBIDDEN_PERSISTENCE_KEYS and not _has_invented_url(item, source_text)
    )
    return (
        ExtractedEventV1(
            event_type=event_type,  # type: ignore[arg-type]
            materiality=materiality,  # type: ignore[arg-type]
            direction=direction,  # type: ignore[arg-type]
            affected_horizon=str(data.get("affected_horizon") or "unspecified"),
            claims=tuple(claims),
            rationale=rationale,
            confidence=confidence,
            limitations=safe_limits,
            entities=tuple(entities),
        ),
        action_rejected,
        span_rejected,
    )


def _strict_entities(
    raw: Any, source_text: str, notes: list[str]
) -> tuple[list[str], bool]:
    if raw is None:
        return [], False
    if not isinstance(raw, list):
        raise _LlmSchemaError("malformed_json")
    kept: list[str] = []
    span_rejected = False
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise _LlmSchemaError("malformed_json")
        if item.strip().upper() in FORBIDDEN_ACTION_TOKENS:
            notes.append("rejected_trading_action_direction")
            continue
        if item not in source_text or _has_invented_url(item, source_text):
            span_rejected = True
            notes.append("evidence_span_not_in_source")
            continue
        kept.append(item)
    return kept, span_rejected


def _strict_claims(
    raw: Any,
    *,
    source_document_id: str,
    source_text: str,
    extractor_version: str,
    notes: list[str],
) -> tuple[list[ExtractedClaimV1], bool, bool]:
    if raw is None:
        return [], False, False
    if not isinstance(raw, list):
        raise _LlmSchemaError("malformed_json")
    claims: list[ExtractedClaimV1] = []
    action_rejected = False
    span_rejected = False
    for idx, claim_raw in enumerate(raw):
        if not isinstance(claim_raw, dict):
            raise _LlmSchemaError("malformed_json")
        claim_raw = strip_forbidden_tree(claim_raw)
        if set(claim_raw) - LLM_CLAIM_KEYS:
            raise _LlmSchemaError("unknown_fields")
        text = str(claim_raw.get("text") or "").strip()
        evidence = str(claim_raw.get("evidence_fragment") or "")
        if not text or not evidence.strip():
            notes.append("claim_missing_evidence")
            span_rejected = True
            continue
        if evidence not in source_text or _has_invented_url(evidence, source_text):
            notes.append("evidence_span_not_in_source")
            span_rejected = True
            continue
        if _has_invented_url(text, source_text):
            notes.append("model_created_url")
            span_rejected = True
            continue
        if claim_looks_like_action(text):
            notes.append("rejected_action_claim")
            action_rejected = True
            continue
        doc_id = str(claim_raw.get("source_document_id") or source_document_id).strip()
        if doc_id != source_document_id:
            notes.append("claim_document_id_mismatch_corrected")
            doc_id = source_document_id
        confidence = claim_raw.get("confidence")
        if not isinstance(confidence, int | float) or isinstance(confidence, bool):
            raise _LlmSchemaError("invalid_confidence")
        if not 0.0 <= float(confidence) <= 1.0:
            raise _LlmSchemaError("invalid_confidence")
        claim_type = str(claim_raw.get("claim_type") or "FACTUAL")
        if claim_type != "FACTUAL":
            notes.append("rejected_action_claim")
            action_rejected = True
            continue
        numerical = _strict_numerical(claim_raw.get("numerical"), source_text, notes)
        if numerical is _NUMERICAL_REJECTED:
            span_rejected = True
            continue
        try:
            claims.append(
                ExtractedClaimV1(
                    claim_id=str(claim_raw.get("claim_id") or f"c{idx + 1}"),
                    text=text,
                    source_document_id=doc_id,
                    evidence_fragment=evidence,
                    extractor_version=extractor_version,
                    confidence=float(confidence),
                    numerical=numerical,
                    claim_type="FACTUAL",
                )
            )
        except ValueError as exc:
            notes.append(f"claim_rejected:{exc}")
            span_rejected = True
    return claims, action_rejected, span_rejected


_NUMERICAL_REJECTED = object()


def _strict_numerical(
    num_raw: Any, source_text: str, notes: list[str]
) -> NumericalFactV1 | None | object:
    if num_raw is None:
        return None
    if not isinstance(num_raw, dict):
        raise _LlmSchemaError("malformed_json")
    if set(num_raw) - LLM_NUMERICAL_KEYS:
        raise _LlmSchemaError("unknown_fields")
    status = str(num_raw.get("status") or "OK").upper()
    if status not in {"OK", "UNKNOWN", "REJECTED"}:
        raise _LlmSchemaError("malformed_json")
    evidence = str(num_raw.get("evidence_fragment") or "")
    if status == "OK":
        if not evidence or evidence not in source_text or _has_invented_url(evidence, source_text):
            notes.append("evidence_span_not_in_source")
            return _NUMERICAL_REJECTED
        value = num_raw.get("value")
        if not isinstance(value, int | float) or isinstance(value, bool):
            notes.append("numerical_unsupported")
            return _NUMERICAL_REJECTED
        if not _number_in_fragment(float(value), evidence):
            notes.append("numerical_not_in_evidence")
            return _NUMERICAL_REJECTED
        parsed_value: float | None = float(value)
    else:
        parsed_value = None
        evidence_or_none = evidence or None
        if evidence and evidence not in source_text:
            notes.append("evidence_span_not_in_source")
            return _NUMERICAL_REJECTED
        evidence = evidence_or_none or ""
    effective = num_raw.get("effective_date")
    effective_date: date | None = None
    if effective is not None:
        if not isinstance(effective, str):
            raise _LlmSchemaError("malformed_json")
        try:
            effective_date = date.fromisoformat(effective)
        except ValueError as exc:
            raise _LlmSchemaError("malformed_json") from exc
    try:
        return NumericalFactV1(
            value=parsed_value,
            unit=None if num_raw.get("unit") is None else str(num_raw.get("unit")),
            currency=None if num_raw.get("currency") is None else str(num_raw.get("currency")),
            period=None if num_raw.get("period") is None else str(num_raw.get("period")),
            effective_date=effective_date,
            evidence_fragment=evidence or None,
            status=status,
        )
    except ValueError:
        notes.append("numerical_parse_failed")
        return _NUMERICAL_REJECTED


def _optional_unit_interval(raw: Any) -> float | None:
    if raw is None:
        return None
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        raise _LlmSchemaError("invalid_confidence")
    value = float(raw)
    if not 0.0 <= value <= 1.0:
        raise _LlmSchemaError("invalid_confidence")
    return value


def _number_in_fragment(value: float, fragment: str) -> bool:
    token = str(value)
    if token.endswith(".0"):
        token = token[:-2]
    folded = fragment.replace(",", ".")
    return token in folded


def _has_invented_url(text: str, source: str) -> bool:
    return any(match not in source for match in _URL_RE.findall(text or ""))


def _llm_rejected(
    *,
    source_document_id: str,
    provider_name: str,
    extractor_version: str,
    limitations: list[str],
    source_text: str,
) -> ExtractionResultV1:
    meta: dict[str, Any] = {"fabricated": False}
    if document_contains_injection(source_text) or "rejected_trading_action_direction" in limitations:
        meta["prompt_injection_obeyed"] = False
    if "prompt_injection_not_obeyed" not in limitations and meta.get("prompt_injection_obeyed") is False:
        limitations.append("prompt_injection_not_obeyed")
    return ExtractionResultV1(
        status="REJECTED",
        source_document_id=source_document_id,
        extractor_version=extractor_version,
        provider_name=provider_name,
        events=(),
        limitations=tuple(dict.fromkeys(limitations)),
        summary="Provider payload rejected",
        metadata=meta,
    )
