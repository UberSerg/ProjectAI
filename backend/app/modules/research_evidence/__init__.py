"""Research Evidence Engine V1 — experiment contract, OOS/ablation, prospective read-model."""

from app.modules.research_evidence.ablation import apply_ablation_mask, run_v4_ablation
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
from app.modules.research_evidence.oos import (
    ResearchOosError,
    ranking_metrics,
    regression_metrics_payload,
    run_chronological_oos,
)
from app.modules.research_evidence.paired_delta import paired_v4_vs_base
from app.modules.research_evidence.pairing import prove_paired_v3_v4, resolve_or_build_paired_runs
from app.modules.research_evidence.prospective import (
    PROSPECTIVE_EVIDENCE_VERSION,
    build_prospective_evidence_v1,
    summarize_forward_predictions,
    summarize_personal_decision_memory,
)
from app.modules.research_evidence.stability import slice_stability

__all__ = [
    "BUNDLE_PART_NAMES",
    "EVALUATION_WORDING",
    "EXPERIMENT_VERSION",
    "PENDING_PART",
    "PROSPECTIVE_EVIDENCE_VERSION",
    "ResearchEvidenceExperimentV1",
    "ResearchOosError",
    "apply_ablation_mask",
    "build_prospective_evidence_v1",
    "default_feature_group_definitions",
    "fingerprint_identity",
    "paired_v4_vs_base",
    "prove_paired_v3_v4",
    "ranking_metrics",
    "regression_metrics_payload",
    "resolve_or_build_paired_runs",
    "run_chronological_oos",
    "run_v4_ablation",
    "slice_stability",
    "summarize_forward_predictions",
    "summarize_personal_decision_memory",
    "write_evidence_bundle",
]
