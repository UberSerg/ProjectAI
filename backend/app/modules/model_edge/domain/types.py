"""Framework-free Model Edge domain types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

PredictionSemantic = Literal["EXPECTED_RETURN", "RANKING_SCORE"]
ComparabilityStatus = Literal[
    "FULLY_COMPARABLE", "PARTIALLY_COMPARABLE", "NOT_COMPARABLE"
]
ViabilityLabel = Literal[
    "ABOVE_CASH_HURDLE",
    "INCONCLUSIVE_VS_CASH_HURDLE",
    "BELOW_CASH_HURDLE",
    "INSUFFICIENT_DATA",
]


class ProspectiveExperimentError(ValueError):
    """Prospective experiment invariant violated."""


class BackfillForbidden(ProspectiveExperimentError):
    """Attempted to create a paired comparison at/before the activation watermark."""


@dataclass(frozen=True, slots=True)
class CandidateRef:
    """Identity of one side of the A/B experiment."""

    name: str
    version: str
    config_hash: str
    prediction_semantic: PredictionSemantic

    @property
    def is_return_like(self) -> bool:
        return self.prediction_semantic == "EXPECTED_RETURN"

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_name": self.name,
            "candidate_version": self.version,
            "candidate_config_hash": self.config_hash,
            "prediction_semantic": self.prediction_semantic,
        }


@dataclass(frozen=True, slots=True)
class ActivationWatermark:
    """Frozen boundary between "already known" and "genuinely prospective"."""

    activated_at: datetime
    market_watermark: date | None

    def allows(self, as_of: date) -> bool:
        """A paired batch is allowed only strictly after the activation watermark."""
        if self.market_watermark is None:
            return True
        return as_of > self.market_watermark


@dataclass(frozen=True, slots=True)
class SideRunSummary:
    """Outcome of running one candidate for one as_of date."""

    candidate: CandidateRef
    status: str
    batch_id: int | None
    eligible_count: int
    prediction_count: int
    feature_schema_hash: str | None
    error: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {"SUCCESS", "NO_CHANGES"} and self.batch_id is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.candidate.to_dict(),
            "status": self.status,
            "batch_id": self.batch_id,
            "eligible_count": self.eligible_count,
            "prediction_count": self.prediction_count,
            "feature_schema_hash": self.feature_schema_hash,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class PairedComparison:
    """Cross-model agreement diagnostics for one as_of date."""

    as_of: date
    eligible_a: int
    eligible_b: int
    common_eligible: int
    comparability_status: ComparabilityStatus
    rank_correlation: float | None
    top20_overlap: float | None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of.isoformat(),
            "eligible_a": self.eligible_a,
            "eligible_b": self.eligible_b,
            "common_eligible": self.common_eligible,
            "comparability_status": self.comparability_status,
            "rank_correlation": self.rank_correlation,
            "top20_overlap": self.top20_overlap,
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class CashHurdle:
    """Deterministic fixed-rate benchmark for a closed calendar period.

    Post-processing only: this value is compared against realised portfolio return and
    never added to any portfolio's cash balance or NAV.
    """

    label: str
    annual_rate: float
    period_from: date
    period_to: date
    calendar_days: int
    day_count: float
    growth_factor: float

    @property
    def hurdle_return(self) -> float:
        return self.growth_factor - 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "annual_rate": self.annual_rate,
            "period_from": self.period_from.isoformat(),
            "period_to": self.period_to.isoformat(),
            "calendar_days": self.calendar_days,
            "day_count_basis": self.day_count,
            "growth_factor": self.growth_factor,
            "hurdle_return": self.hurdle_return,
            "mutates_portfolio_cash": False,
        }
