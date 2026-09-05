"""`fundamental_daily` v1 feature contract.

Materialisation is conditional: with no reports in the store the result is NOT_READY and
carries zero rows. Missing metrics are omitted, never encoded as 0.0 — a fabricated zero
is indistinguishable from a real zero downstream.

Nothing is written to a shared feature table: V1 defines the contract and returns rows
in memory. Dataset V2 and the operational cycle are untouched.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.fundamentals.application import pit
from app.modules.fundamentals.domain.types import (
    FUNDAMENTAL_FEATURE_SET_CODE,
    FUNDAMENTAL_FEATURE_SET_VERSION,
    RECENT_REPORT_MAX_AGE_DAYS,
    FundamentalsState,
    NormalizationStatus,
    ReadinessStatus,
)
from app.modules.fundamentals.infrastructure.models import (
    FinancialReport,
    SecurityIssuerMapping,
    fundamentals_schema_ready,
)

METRIC_FEATURE_PREFIX = "metric_"


class LookaheadError(AssertionError):
    """Raised when a feature row would carry information dated after its sample date."""


@dataclass(frozen=True, slots=True)
class FundamentalFeatureRow:
    as_of: date
    issuer_id: int
    feature_known_at: date
    features: Mapping[str, float]
    instrument_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "issuer_id": self.issuer_id,
            "instrument_id": self.instrument_id,
            "feature_known_at": self.feature_known_at.isoformat(),
            "features": dict(self.features),
        }


@dataclass
class FundamentalFeatureResult:
    as_of: date
    status: str = ReadinessStatus.NOT_READY.value
    feature_set_code: str = FUNDAMENTAL_FEATURE_SET_CODE
    feature_set_version: int = FUNDAMENTAL_FEATURE_SET_VERSION
    rows: list[FundamentalFeatureRow] = field(default_factory=list)
    issuers_considered: int = 0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "feature_set_code": self.feature_set_code,
            "feature_set_version": self.feature_set_version,
            "as_of": self.as_of.isoformat(),
            "issuers_considered": self.issuers_considered,
            "row_count": len(self.rows),
            "rows": [row.to_dict() for row in self.rows],
            "reasons": self.reasons,
        }


def build_fundamental_features(
    state: FundamentalsState, *, instrument_id: int | None = None
) -> FundamentalFeatureRow | None:
    """Pure row builder. Returns None when the issuer has no disclosed report at as_of."""
    report = state.latest_report
    if report is None:
        return None
    if report.known_at > state.as_of:
        raise LookaheadError(
            f"report known_at {report.known_at} is after sample date {state.as_of}"
        )

    report_age_days = (state.as_of - report.period_end).days
    features: dict[str, float] = {
        "days_since_latest_report": float((state.as_of - report.known_at).days),
        "report_age_days": float(report_age_days),
        "has_recent_report": 1.0 if report_age_days <= RECENT_REPORT_MAX_AGE_DAYS else 0.0,
    }
    for fact in state.facts:
        if fact.normalization_status is not NormalizationStatus.NORMALIZED:
            continue
        if fact.value is None:
            continue
        features[f"{METRIC_FEATURE_PREFIX}{fact.metric_code}"] = float(fact.value)

    return FundamentalFeatureRow(
        as_of=state.as_of,
        issuer_id=state.issuer_id or 0,
        instrument_id=instrument_id,
        feature_known_at=report.known_at,
        features=features,
    )


def _mapped_pairs(session: Session) -> list[tuple[int, int]]:
    """(instrument_id, issuer_id) for MAPPED mappings only."""
    rows = session.execute(
        select(SecurityIssuerMapping.instrument_id, SecurityIssuerMapping.issuer_id).where(
            SecurityIssuerMapping.mapping_status == "MAPPED",
            SecurityIssuerMapping.issuer_id.is_not(None),
        )
    ).all()
    return [(int(instrument_id), int(issuer_id)) for instrument_id, issuer_id in rows]


def materialize_fundamental_daily(
    session: Session,
    as_of: date,
    *,
    instrument_ids: Sequence[int] | None = None,
) -> FundamentalFeatureResult:
    """Build `fundamental_daily` rows for one sample date. Never fabricates values."""
    result = FundamentalFeatureResult(as_of=as_of)
    if not fundamentals_schema_ready(session):
        result.reasons.append("fundamentals schema missing; apply alembic 20260905_0018")
        return result

    reports_total = int(
        session.execute(select(func.count()).select_from(FinancialReport)).scalar_one()
    )
    if reports_total == 0:
        result.reasons.append(
            "fundamentals.financial_reports is empty (no accepted report provider)"
        )
        return result

    pairs = _mapped_pairs(session)
    if instrument_ids is not None:
        wanted = set(instrument_ids)
        pairs = [pair for pair in pairs if pair[0] in wanted]
    result.issuers_considered = len({issuer_id for _, issuer_id in pairs})

    for instrument_id, issuer_id in pairs:
        state = pit.get_fundamentals_as_of(session, issuer_id, as_of)
        row = build_fundamental_features(state, instrument_id=instrument_id)
        if row is not None:
            result.rows.append(row)

    if not result.rows:
        result.reasons.append("no issuer had a disclosed report at as_of")
        return result
    result.status = (
        ReadinessStatus.READY.value
        if len(result.rows) == len(pairs)
        else ReadinessStatus.PARTIAL.value
    )
    return result
