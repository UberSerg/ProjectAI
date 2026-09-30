"""Deterministic identity for a displayed Daily Personal Decision (no I/O)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def decision_fingerprint(payload: Any) -> str:
    """Identity of the exact recommendation the UI displayed.

    Excludes ``decision_fingerprint`` itself. Stable under JSON key reordering.
    """
    if isinstance(payload, dict):
        body = {key: value for key, value in payload.items() if key != "decision_fingerprint"}
    else:
        body = payload
    return canonical_hash(json.loads(canonical_json(body)))
