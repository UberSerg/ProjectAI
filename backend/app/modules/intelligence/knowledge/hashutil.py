"""Deterministic content hashing for knowledge-rule dedup / provenance."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.intelligence.contracts.knowledge import KnowledgeRule


def canonical_rule_payload(rule: KnowledgeRule, *, extra_body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Stable payload used for content_hash (excludes runtime status)."""
    payload = {
        "rule_id": rule.rule_id,
        "version": rule.version,
        "domain": rule.domain,
        "title": rule.title,
        "principle": rule.principle,
        "applicability": list(rule.applicability),
        "required_evidence": list(rule.required_evidence),
        "contraindications": list(rule.contraindications),
        "severity": rule.severity,
        "source_reference": rule.source_reference,
        "source_location": rule.source_location,
        "created_from": rule.created_from,
        "extra_body": extra_body or {},
    }
    return payload


def content_hash(rule: KnowledgeRule, *, extra_body: dict[str, Any] | None = None) -> str:
    raw = json.dumps(
        canonical_rule_payload(rule, extra_body=extra_body),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
