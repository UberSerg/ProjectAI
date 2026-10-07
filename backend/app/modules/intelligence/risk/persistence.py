"""Optional persistence for RiskAssessmentV1 → intelligence.risk_assessments.

Schema owned by orchestrator migration. This module only upserts when the table
exists; it never creates/alters schema and never touches ``modules/risk``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.intelligence.contracts.risk import RiskAssessmentV1


class SupportsExecute(Protocol):
    def execute(self, statement: Any, params: Any | None = None) -> Any: ...


@dataclass(frozen=True, slots=True)
class PersistResult:
    persisted: bool
    reason: str
    instrument_id: int
    as_of: str


def risk_assessments_schema_ready(session: SupportsExecute) -> bool:
    return bool(
        session.execute(
            text("SELECT to_regclass('intelligence.risk_assessments') IS NOT NULL")
        ).scalar_one()
    )


def persist_risk_assessment(
    session: Session,
    assessment: RiskAssessmentV1,
    *,
    require_schema: bool = False,
) -> PersistResult:
    """Upsert assessment payload. No-op when schema missing (unless require_schema)."""
    as_of_s = assessment.as_of.isoformat()
    if not risk_assessments_schema_ready(session):
        if require_schema:
            raise RuntimeError("intelligence.risk_assessments table is not available")
        return PersistResult(
            persisted=False,
            reason="schema_not_ready",
            instrument_id=int(assessment.instrument_id),
            as_of=as_of_s,
        )

    payload = assessment.to_dict()
    session.execute(
        text(
            """
            INSERT INTO intelligence.risk_assessments (
                instrument_id, as_of, risk_state, risk_score, payload
            ) VALUES (
                :instrument_id, CAST(:as_of AS DATE), :risk_state, :risk_score,
                CAST(:payload AS JSONB)
            )
            ON CONFLICT (instrument_id, as_of) DO UPDATE SET
                risk_state = EXCLUDED.risk_state,
                risk_score = EXCLUDED.risk_score,
                payload = EXCLUDED.payload
            """
        ),
        {
            "instrument_id": int(assessment.instrument_id),
            "as_of": as_of_s,
            "risk_state": assessment.risk_state,
            "risk_score": assessment.risk_score,
            "payload": _json_dumps(payload),
        },
    )
    return PersistResult(
        persisted=True,
        reason="upserted",
        instrument_id=int(assessment.instrument_id),
        as_of=as_of_s,
    )


def _json_dumps(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, default=str)
