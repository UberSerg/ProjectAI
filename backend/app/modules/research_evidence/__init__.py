"""Research Evidence Engine V1 — experiment, OOS/ablation, economics, prospective."""

from app.modules.research_evidence.ablation import apply_ablation_mask, run_v4_ablation
from app.modules.research_evidence.bundle import (
    BUNDLE_PART_NAMES,
    PENDING_PART,
    write_evidence_bundle,
)
from app.modules.research_evidence.campaign_refresh import inspect_campaign_coverage, refresh_campaign_data
from app.modules.research_evidence.campaign_snapshot import (
    SNAPSHOT_VERSION,
    build_research_data_snapshot,
    data_snapshot_hash,
    write_research_data_snapshot,
)
from app.modules.research_evidence.campaign_window import (
    PRIMARY_DATE_FROM,
    STATUS_INSUFFICIENT,
    latest_mature_20d_as_of,
    resolve_campaign_window,
)
from app.modules.research_evidence.economics import (
    run_all_model_variants,
    run_research_economics,
    run_research_economics_cost_grid,
    validate_oos_prediction_frame,
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
from app.modules.research_evidence.service import get_latest_evidence, run_historical_evidence
from app.modules.research_evidence.stability import slice_stability

__all__ = [
    "BUNDLE_PART_NAMES",
    "PRIMARY_DATE_FROM",
    "SNAPSHOT_VERSION",
    "STATUS_INSUFFICIENT",
    "build_research_data_snapshot",
    "data_snapshot_hash",
    "inspect_campaign_coverage",
    "latest_mature_20d_as_of",
    "refresh_campaign_data",
    "resolve_campaign_window",
    "write_research_data_snapshot",
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
    "get_latest_evidence",
    "paired_v4_vs_base",
    "prove_paired_v3_v4",
    "ranking_metrics",
    "regression_metrics_payload",
    "resolve_or_build_paired_runs",
    "run_all_model_variants",
    "run_chronological_oos",
    "run_historical_evidence",
    "run_research_economics",
    "run_research_economics_cost_grid",
    "run_v4_ablation",
    "slice_stability",
    "summarize_forward_predictions",
    "summarize_personal_decision_memory",
    "validate_oos_prediction_frame",
    "write_evidence_bundle",
]
