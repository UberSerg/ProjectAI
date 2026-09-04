"""Typed Research Lab domain errors (API maps to 4xx, not 500)."""

from __future__ import annotations


class ResearchLabError(Exception):
    """Base Lab error with stable machine code + human message."""

    code: str = "RESEARCH_LAB_ERROR"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class HoldoutLaunchForbidden(ResearchLabError):
    code = "HOLDOUT_LAUNCH_FORBIDDEN"


class UnknownCandidate(ResearchLabError):
    code = "UNKNOWN_CANDIDATE"


class UnknownPolicy(ResearchLabError):
    code = "UNKNOWN_POLICY"


class UnknownRisk(ResearchLabError):
    code = "UNKNOWN_RISK"


class UnsupportedPolicyRisk(ResearchLabError):
    code = "UNSUPPORTED_POLICY_RISK"


class PeriodOutsideDev(ResearchLabError):
    code = "PERIOD_OUTSIDE_DEV"


class InvalidCapital(ResearchLabError):
    code = "INVALID_CAPITAL"


class InvalidCost(ResearchLabError):
    code = "INVALID_COST"


class MissingPredictions(ResearchLabError):
    code = "MISSING_PREDICTIONS"


class CandidateMismatch(ResearchLabError):
    code = "CANDIDATE_MISMATCH"


class InvalidSegment(ResearchLabError):
    code = "INVALID_SEGMENT"


class CompareTooFew(ResearchLabError):
    code = "COMPARE_TOO_FEW"


class CompareTooMany(ResearchLabError):
    code = "COMPARE_TOO_MANY"


class RunNotFound(ResearchLabError):
    code = "RUN_NOT_FOUND"
