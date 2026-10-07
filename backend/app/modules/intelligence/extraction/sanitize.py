"""Post-validation for extractor output — reject prompt-injection / action obedience."""

from __future__ import annotations

import re
from typing import Any

from app.modules.intelligence.extraction.schema import (
    DIRECTION_VALUES,
    EVENT_TYPES,
    EXTRACTOR_VERSION,
    FORBIDDEN_ACTION_TOKENS,
    FORBIDDEN_PERSISTENCE_KEYS,
    MATERIALITY_VALUES,
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


def document_contains_injection(text: str | None) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _INJECTION_PATTERNS)


def strip_forbidden_keys(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop hidden chain-of-thought keys from a provider payload."""
    return {k: v for k, v in payload.items() if k not in FORBIDDEN_PERSISTENCE_KEYS}


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
