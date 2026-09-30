"""Personal Decision Memory V1 — pure domain helpers (no DB, no HTTP)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# Stable id of the recommendation engine whose output is frozen in Decision Memory.
ENGINE_VERSION = "PERSONAL_DAILY_DECISION_V2"
HORIZONS: tuple[int, ...] = (5, 20, 60)

RETURN_TYPE_PRICE = "PRICE_RETURN"

BASELINE_AVAILABLE = "AVAILABLE"
BASELINE_UNAVAILABLE = "UNAVAILABLE"

OUTCOME_PENDING = "PENDING"
OUTCOME_READY = "READY"
OUTCOME_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
OUTCOME_BASELINE_UNAVAILABLE = "BASELINE_UNAVAILABLE"

ALIGNED = "ALIGNED"
NOT_ALIGNED = "NOT_ALIGNED"

ACTION_INCREASE = "CONSIDER_INCREASE"
ACTION_REDUCE = "CONSIDER_REDUCE"
DIRECTIONAL_ACTIONS = frozenset({ACTION_INCREASE, ACTION_REDUCE})

LABEL_POSSIBLE_MATCH = "POSSIBLE_MATCH"
LINK_SOURCE_USER_CONFIRMED = "USER_CONFIRMED"

_MONEY_QUANT = Decimal("0.0001")


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def canonical_json(payload: Any) -> str:
    """Deterministic JSON: sorted keys, compact separators, Decimal/date via default."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def normalize_new_cash(new_cash_rub: Decimal | None) -> Decimal:
    """None and 0 are the same hypothetical request ("no new cash")."""
    if new_cash_rub is None:
        return Decimal("0.0000")
    value = new_cash_rub if isinstance(new_cash_rub, Decimal) else Decimal(str(new_cash_rub))
    if not value.is_finite():
        raise ValueError("new_cash_rub must be finite")
    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


def decision_fingerprint(payload: Any) -> str:
    """Deterministic identity of a Daily Decision as shown to the user.

    Excludes ``decision_fingerprint`` itself (no recursive self-hash). Uses the
    same canonical JSON rules as snapshot integrity hashing. Does not include
    pure runtime timestamps invented only for hashing.
    """
    if isinstance(payload, dict):
        body = {key: value for key, value in payload.items() if key != "decision_fingerprint"}
    else:
        body = payload
    # Round-trip through canonical JSON so Decimal/date and key order match capture.
    return canonical_hash(json.loads(canonical_json(body)))


def request_fingerprint(
    portfolio_id: int,
    new_cash_rub: Decimal | None,
    expected_decision_fingerprint: str | None = None,
) -> str:
    return canonical_hash(
        {
            "portfolio_id": int(portfolio_id),
            "new_cash_rub": format(normalize_new_cash(new_cash_rub), "f"),
            "expected_decision_fingerprint": str(expected_decision_fingerprint or "").strip(),
        }
    )


def directional_alignment(action: str, forward_return: Decimal) -> str | None:
    """ALIGNED / NOT_ALIGNED for INCREASE/REDUCE only; ``None`` for everything else."""
    if action == ACTION_INCREASE:
        return ALIGNED if forward_return > 0 else NOT_ALIGNED
    if action == ACTION_REDUCE:
        return ALIGNED if forward_return < 0 else NOT_ALIGNED
    return None


def price_return(baseline: Decimal, observed: Decimal) -> Decimal:
    if baseline <= 0:
        raise ValueError("baseline must be positive")
    return (observed - baseline) / baseline


def operation_side_for_action(action: str) -> str | None:
    """Journal side an action may be confused with (advisory only)."""
    if action == ACTION_INCREASE:
        return "BUY"
    if action == ACTION_REDUCE:
        return "SELL"
    return None
