/**
 * Research Evidence Engine V1 — frontend API contract.
 *
 * Backend is implemented later; this client is the integration point.
 * Overview returns aggregates only — never dump every prediction row.
 *
 * Forbidden overview fields (do not add to types or UI):
 * overall_accuracy, master_score, kraken_score, production_readiness_score.
 */

import { apiRequest } from "./client";

export type EvidenceReturnKind = "PRICE_RETURN";

export interface EvidenceExperiment {
  id?: string | null;
  name?: string | null;
  version?: string | null;
  purpose?: string | null;
  status?: string | null;
  checking?: string[] | null;
  dataset_from?: string | null;
  dataset_to?: string | null;
  notes?: string | null;
}

export interface EvidenceV4Coverage {
  fundamental_sample_coverage_pct?: number | null;
  event_sample_coverage_pct?: number | null;
  issuer_resolution_basis_counts?: Record<string, number> | null;
  bank_fi_unsupported_samples?: number | null;
  current_only_share?: number | null;
  current_only_share_denominator?: string | null;
}

export interface EvidenceReturnTruth {
  primary_label_family?: string | null;
  total_return?: boolean | null;
  total_return_enrichment_status?: string | null;
  dividend_adjusted?: boolean | null;
}

export interface EvidenceDataset {
  universe_v3?: number | null;
  universe_v4?: number | null;
  universe_label?: string | null;
  labels?: string[] | null;
  feature_count_v3?: number | null;
  feature_count_v4?: number | null;
  sample_identity_match?: boolean | null;
  pit_violations?: number | null;
  fund_coverage?: number | null;
  event_coverage?: number | null;
  current_only_share?: number | null;
  bank_fi_unsupported?: number | null;
  v4_coverage?: EvidenceV4Coverage | null;
  return_truth?: EvidenceReturnTruth | null;
  total_return_status?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  notes?: string | null;
  partial?: boolean | null;
}

export interface FoldYearRow {
  fold?: string | null;
  year?: number | string | null;
  rank_ic?: number | null;
  spread?: number | null;
  n?: number | null;
}

export interface HistoricalModelSignal {
  family?: "regression" | "ranker" | string | null;
  rank_ic?: number | null;
  spread?: number | null;
  n?: number | null;
  fold_year?: FoldYearRow[] | null;
  consistent?: boolean | null;
  notes?: string | null;
  available?: boolean | null;
}

export interface HistoricalModelsBlock {
  regression?: HistoricalModelSignal | null;
  ranker?: HistoricalModelSignal | null;
}

export type AblationVariantId = "base" | "fund" | "events" | "full_v4" | string;

export interface AblationVariantRow {
  variant: AblationVariantId;
  label?: string | null;
  mean_oos_ic?: number | null;
  spread?: number | null;
  bootstrap_ci_low?: number | null;
  bootstrap_ci_high?: number | null;
  n?: number | null;
}

export interface AblationTable {
  rows?: AblationVariantRow[] | null;
  notes?: string | null;
  partial?: boolean | null;
}

export type EconomicsScenarioId = "gross" | "net_10bps" | "net_30bps" | "net_50bps" | string;

export interface EconomicsScenario {
  id?: EconomicsScenarioId | null;
  label?: string | null;
  commission_bps?: number | null;
  total_return?: number | null;
  cagr?: number | null;
  max_drawdown?: number | null;
  turnover_ratio?: number | null;
  excess_vs_benchmark?: number | null;
  benchmark_return?: number | null;
}

export interface EconomicsSummary {
  experiment_id?: string | null;
  simulation_kind?: string | null;
  return_kind?: EvidenceReturnKind | string | null;
  dividends?: "excluded" | string | null;
  benchmark?: string | null;
  scenarios?: EconomicsScenario[] | null;
  max_drawdown?: number | null;
  turnover_ratio?: number | null;
  notes?: string | null;
  partial?: boolean | null;
}

export interface ProspectiveHorizonRow {
  horizon_sessions?: number | null;
  matured_count?: number | null;
  pending_count?: number | null;
  unavailable_count?: number | null;
  status?: string | null;
  price_return?: {
    n?: number | null;
    status?: string | null;
    mean_price_return?: string | number | null;
    median_price_return?: string | number | null;
  } | null;
  direction_alignment?: {
    n?: number | null;
    status?: string | null;
    alignment_rate?: string | number | null;
    aligned_count?: number | null;
    not_aligned_count?: number | null;
    note?: string | null;
  } | null;
}

export interface ProspectivePdm {
  captures_total?: number | null;
  return_type?: string | null;
  horizons?: ProspectiveHorizonRow[] | null;
  confirmed_operation_links?: {
    count?: number | null;
    role?: string | null;
    causality_claim?: boolean | null;
    linked_trade_means_recommendation_caused_trade?: boolean | null;
    note?: string | null;
  } | null;
}

export interface ProspectiveForwardMetrics {
  prediction_semantic?: string | null;
  status?: string | null;
  batch_id?: number | null;
  as_of_date?: string | null;
  evaluated_count?: number | null;
  pending_count?: number | null;
  mae?: number | null;
  rmse?: number | null;
  spearman_rank_ic?: number | null;
  mean_predicted?: number | null;
  mean_realized?: number | null;
}

export interface ProspectiveForward {
  latest_batch?: {
    batch_id?: number | null;
    as_of_date?: string | null;
    prediction_semantic?: string | null;
  } | null;
  latest_evaluated_batch?: {
    batch_id?: number | null;
    status?: string | null;
    evaluated_at?: string | null;
    prediction_semantic?: string | null;
    evaluated_count?: number | null;
    pending_count?: number | null;
  } | null;
  freshness?: {
    matured_count?: number | null;
    pending_count?: number | null;
  } | null;
  expected_return?: ProspectiveForwardMetrics | null;
  ranking_score?: ProspectiveForwardMetrics | null;
}

export interface ProspectiveSummary {
  status?: string | null;
  n_observations?: number | null;
  date_from?: string | null;
  date_to?: string | null;
  rank_ic?: number | null;
  notes?: string | null;
  empty?: boolean | null;
  personal_decision_memory?: ProspectivePdm | null;
  forward_predictions?: ProspectiveForward | null;
}

export interface EvidenceLimitation {
  code?: string | null;
  title?: string | null;
  detail?: string | null;
}

export interface EvidenceStability {
  fold_year?: FoldYearRow[] | null;
  notes?: string | null;
  regression?: HistoricalModelSignal | null;
  ranker?: HistoricalModelSignal | null;
}

export interface ResearchEvidenceOverview {
  experiment?: EvidenceExperiment | null;
  dataset?: EvidenceDataset | null;
  historical_models?: HistoricalModelsBlock | null;
  ablation?: AblationTable | null;
  stability?: EvidenceStability | null;
  economics?: EconomicsSummary | null;
  prospective?: ProspectiveSummary | null;
  limitations?: Array<EvidenceLimitation | string> | null;
}

/** Frozen campaign identity. Orchestrator implements persistence later. */
export const CANONICAL_CAMPAIGN_VERSION = "CanonicalEvidenceCampaignV1";

export interface CampaignIdentity {
  campaign_version?: string | null;
  fingerprint?: string | null;
  fingerprint_short?: string | null;
  v3_run_id?: number | string | null;
  v4_run_id?: number | string | null;
  v3_dataset_hash?: string | null;
  v4_dataset_hash?: string | null;
  v3_values_hash?: string | null;
  v4_values_hash?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  data_snapshot_hash?: string | null;
  data_snapshot_at?: string | null;
  universe_version?: string | null;
}

export interface EvidenceCampaignSummary {
  fingerprint: string;
  fingerprint_short?: string | null;
  campaign_version?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  status?: string | null;
  created_at?: string | null;
  finalized_at?: string | null;
}

export interface EvidenceCampaignList {
  items?: EvidenceCampaignSummary[] | null;
  campaigns?: EvidenceCampaignSummary[] | null;
}

export interface DataQualityField {
  status?: string | null;
  value?: number | string | null;
  missing?: boolean | null;
  notes?: string | null;
  counts?: Record<string, number | null> | null;
}

export interface CampaignDataQuality {
  price_coverage?: DataQualityField | number | string | null;
  pit_status?: DataQualityField | string | null;
  v4_fundamental_coverage?: DataQualityField | number | string | null;
  event_coverage?: DataQualityField | number | string | null;
  issuer_identity_basis?: DataQualityField | Record<string, number | null> | null;
  bank_fi_unsupported?: DataQualityField | number | string | null;
  total_return_status?: DataQualityField | string | null;
}

export interface CampaignOosRow {
  variant: string;
  label?: string | null;
  rank_ic?: number | null;
  mean_rank_ic?: number | null;
  spread?: number | null;
  n?: number | null;
  ci_low?: number | null;
  ci_high?: number | null;
  bootstrap_ci_low?: number | null;
  bootstrap_ci_high?: number | null;
  delta_vs_base?: number | null;
  delta_ci_low?: number | null;
  delta_ci_high?: number | null;
}

export interface CampaignOosTable {
  rows?: CampaignOosRow[] | null;
  notes?: string | null;
  partial?: boolean | null;
}

export interface StabilitySliceRow {
  key?: string | null;
  label?: string | null;
  fold?: string | null;
  year?: number | string | null;
  rank_ic?: number | null;
  spread?: number | null;
  n?: number | null;
}

export interface CampaignStability {
  years?: StabilitySliceRow[] | null;
  folds?: StabilitySliceRow[] | null;
  identity_basis?: StabilitySliceRow[] | null;
  activity?: StabilitySliceRow[] | null;
  notes?: string | null;
}

export interface PrimaryResearchContract {
  rebalance_sessions?: number | null;
  selection_top_pct?: number | null;
  cost_bps_per_side?: number | null;
  model_semantic?: string | null;
  variant?: string | null;
  return_kind?: EvidenceReturnKind | string | null;
  cumulative_price_return?: number | null;
  benchmark_return?: number | null;
  excess_vs_benchmark?: number | null;
  max_drawdown?: number | null;
  turnover?: number | null;
  average_cash_weight?: number | null;
  unresolved_exits?: number | null;
  unavailable_open_executions?: number | null;
  notes?: string | null;
  partial?: boolean | null;
}

export interface RobustnessMatrixCell {
  rebalance_sessions?: number | null;
  selection_top_pct?: number | null;
  cost_bps?: number | null;
  total_return?: number | null;
  max_drawdown?: number | null;
  turnover?: number | null;
  n?: number | null;
}

export interface EconomicsRobustness {
  rebalance_sessions?: number[] | null;
  selection_top_pct?: number[] | null;
  cost_bps?: number[] | null;
  cells?: RobustnessMatrixCell[] | null;
  notes?: string | null;
}

export interface EvidenceCompleteness {
  data_integrity?: string | null;
  historical_oos?: string | null;
  economics?: string | null;
  prospective?: string | null;
  owner_review_state?: string | null;
}

export interface EvidenceDossierV1 {
  identity?: CampaignIdentity | null;
  data_snapshot?: {
    hash?: string | null;
    observed_at?: string | null;
    created_at?: string | null;
  } | null;
  data_quality?: CampaignDataQuality | null;
  historical_oos?: CampaignOosTable | null;
  ablation?: AblationTable | null;
  stability?: CampaignStability | EvidenceStability | null;
  economics_primary?: PrimaryResearchContract | null;
  economics_robustness?: EconomicsRobustness | null;
  prospective?: ProspectiveSummary | null;
  limitations?: Array<EvidenceLimitation | string> | null;
  evidence_completeness?: EvidenceCompleteness | null;
  status?: string | null;
  empty?: boolean | null;
}

export interface CanonicalCampaignLaunchRequest {
  campaign_version: typeof CANONICAL_CAMPAIGN_VERSION;
  exact_rerun?: boolean | null;
}

export interface CanonicalCampaignLaunchResponse {
  status?: string | null;
  message?: string | null;
  fingerprint?: string | null;
  campaign_version?: string | null;
  existing?: boolean | null;
  exact_rerun?: boolean | null;
}

export interface ResearchEvidenceExperimentDetail {
  experiment?: EvidenceExperiment | null;
  dataset?: EvidenceDataset | null;
  historical_models?: HistoricalModelsBlock | null;
  ablation?: AblationTable | null;
  stability?: EvidenceStability | null;
  limitations?: Array<EvidenceLimitation | string> | null;
}

export interface ResearchEvidenceRunRequest {
  experiment_id?: string | null;
  note?: string | null;
  v3_run_id?: number | null;
  v4_run_id?: number | null;
  date_from?: string | null;
  date_to?: string | null;
  instrument_ids?: number[] | null;
  rebuild?: boolean | null;
}

export interface ResearchEvidenceRunResponse {
  status?: string | null;
  message?: string | null;
  experiment_id?: string | null;
}

const BASE = "/research/evidence";

export function getResearchEvidenceOverview(signal?: AbortSignal) {
  return apiRequest<ResearchEvidenceOverview>(`${BASE}/overview`, { signal });
}

export function getResearchEvidenceProspective(signal?: AbortSignal) {
  return apiRequest<ProspectiveSummary>(`${BASE}/prospective`, { signal });
}

export function getResearchEvidenceExperiment(experimentId: string, signal?: AbortSignal) {
  return apiRequest<ResearchEvidenceExperimentDetail>(
    `${BASE}/${encodeURIComponent(experimentId)}`,
    { signal },
  );
}

export function getResearchEvidenceEconomics(experimentId: string, signal?: AbortSignal) {
  return apiRequest<EconomicsSummary>(
    `${BASE}/${encodeURIComponent(experimentId)}/economics`,
    { signal },
  );
}

/** OWNER-only on the backend. UI hides the control unless presentation role is OWNER. */
export function runResearchEvidence(body: ResearchEvidenceRunRequest = {}, signal?: AbortSignal) {
  return apiRequest<ResearchEvidenceRunResponse>(`${BASE}/run`, {
    method: "POST",
    body,
    signal,
  });
}

export function listResearchEvidenceCampaigns(signal?: AbortSignal) {
  return apiRequest<EvidenceCampaignList>(`${BASE}/campaigns`, { signal });
}

export function getResearchEvidenceCampaign(fingerprint: string, signal?: AbortSignal) {
  return apiRequest<EvidenceCampaignSummary>(
    `${BASE}/campaigns/${encodeURIComponent(fingerprint)}`,
    { signal },
  );
}

/** OWNER-only. Body is CanonicalEvidenceCampaignV1 — no free-form universe. */
export function launchCanonicalEvidenceCampaignV1(
  body: CanonicalCampaignLaunchRequest = { campaign_version: CANONICAL_CAMPAIGN_VERSION },
  signal?: AbortSignal,
) {
  return apiRequest<CanonicalCampaignLaunchResponse>(`${BASE}/campaigns/canonical-v1`, {
    method: "POST",
    body: {
      campaign_version: CANONICAL_CAMPAIGN_VERSION,
      ...(body.exact_rerun ? { exact_rerun: true } : {}),
    },
    signal,
  });
}

export function getResearchEvidenceCampaignDossier(fingerprint: string, signal?: AbortSignal) {
  return apiRequest<EvidenceDossierV1>(
    `${BASE}/campaigns/${encodeURIComponent(fingerprint)}/dossier`,
    { signal },
  );
}
