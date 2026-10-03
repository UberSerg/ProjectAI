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

export interface ProspectiveObservation {
  as_of?: string | null;
  n?: number | null;
  rank_ic?: number | null;
  notes?: string | null;
}

export interface ProspectiveSummary {
  status?: string | null;
  n_observations?: number | null;
  date_from?: string | null;
  date_to?: string | null;
  rank_ic?: number | null;
  notes?: string | null;
  observations?: ProspectiveObservation[] | null;
  empty?: boolean | null;
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
