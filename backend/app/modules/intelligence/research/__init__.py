"""Intelligence Research V1 — research experiment contract for Intelligence Stack packs.

Not Dataset V5. Not a Candidate promotion path. Not a V4/Canonical retune.
"""

from app.modules.intelligence.research.constants import (
    EXPERIMENT_NAME,
    EXPERIMENT_VERSION,
    FEATURE_PACKS,
    MODE_HISTORICAL_EVALUABLE,
    MODE_INSUFFICIENT_HISTORY,
    MODE_PROSPECTIVE_ONLY,
)
from app.modules.intelligence.research.coverage import (
    DomainEvidence,
    PackCoverageRow,
    build_coverage_matrix,
)
from app.modules.intelligence.research.experiment import IntelligenceResearchExperimentV1
from app.modules.intelligence.research.service import (
    build_research_plan,
    evaluate_intelligence_research,
)

__all__ = [
    "DomainEvidence",
    "EXPERIMENT_NAME",
    "EXPERIMENT_VERSION",
    "FEATURE_PACKS",
    "IntelligenceResearchExperimentV1",
    "MODE_HISTORICAL_EVALUABLE",
    "MODE_INSUFFICIENT_HISTORY",
    "MODE_PROSPECTIVE_ONLY",
    "PackCoverageRow",
    "build_coverage_matrix",
    "build_research_plan",
    "evaluate_intelligence_research",
]
