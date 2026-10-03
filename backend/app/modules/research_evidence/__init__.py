"""Research Evidence Engine V1 — experiment contract, pairing proof, artifact bundle."""

from app.modules.research_evidence.bundle import (
    BUNDLE_PART_NAMES,
    PENDING_PART,
    write_evidence_bundle,
)
from app.modules.research_evidence.experiment import (
    EVALUATION_WORDING,
    EXPERIMENT_VERSION,
    ResearchEvidenceExperimentV1,
    default_feature_group_definitions,
    fingerprint_identity,
)
from app.modules.research_evidence.pairing import prove_paired_v3_v4, resolve_or_build_paired_runs

__all__ = [
    "BUNDLE_PART_NAMES",
    "EVALUATION_WORDING",
    "EXPERIMENT_VERSION",
    "PENDING_PART",
    "ResearchEvidenceExperimentV1",
    "default_feature_group_definitions",
    "fingerprint_identity",
    "prove_paired_v3_v4",
    "resolve_or_build_paired_runs",
    "write_evidence_bundle",
]
