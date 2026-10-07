"""Intelligence Research V1 — coverage-first, research-only experiment identity."""

from app.modules.intelligence.research.constants import (
    EVALUATION_WORDING,
    EXPERIMENT_NAME,
    EXPERIMENT_VERSION,
    FEATURE_PACKS,
)
from app.modules.intelligence.research.service import (
    build_research_plan,
    evaluate_intelligence_research,
    pack_eligibility,
)

__all__ = [
    "EVALUATION_WORDING",
    "EXPERIMENT_NAME",
    "EXPERIMENT_VERSION",
    "FEATURE_PACKS",
    "build_research_plan",
    "evaluate_intelligence_research",
    "pack_eligibility",
]
