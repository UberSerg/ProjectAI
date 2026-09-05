import { apiRequest, queryString } from "./client";

export interface ExternalStatus {
  registered: boolean;
  status?: string;
  source_code?: string;
  file_name?: string;
  file_sha256?: string;
  price_semantic?: string;
  staged_rows?: number;
  imported_at?: string | null;
}

export interface ExternalSummary extends ExternalStatus {
  rows?: number;
  valid_rows?: number;
  rejected_rows?: number;
  symbols?: number;
  min_date?: string | null;
  max_date?: string | null;
  match_counts?: Record<string, number>;
  quality_counts?: Record<string, number>;
  eligibility_counts?: Record<string, number>;
  canonical_candles_untouched?: boolean;
}

export interface ExternalInstrument {
  source_symbol: string;
  first_date: string | null;
  last_date: string | null;
  observations: number;
  active_years: number[];
  match_status: string;
  mapping_confidence: number;
  project_symbol: string | null;
  quality_status: string;
  research_eligible: boolean;
}

export interface CoverageYear {
  year: number;
  rows: number;
  valid_rows: number;
  symbols: number;
  eligible_rows: number;
}

export interface ReconciliationItem {
  source_symbol: string;
  project_symbol: string | null;
  overlap_rows: number;
  exact_ohlc_rows: number;
  exact_ohlc_share: number | null;
  close_rel_med: number | null;
  status: string;
}

export interface MlYear {
  year: number;
  symbols: number;
  eligible_symbols: number;
  feature_stack_status: string;
  blocking_reasons: string[];
}

export interface CaProbe {
  symbol: string;
  event_date: string;
  label: string;
  verdict: string;
  observed_ratio: number | null;
}

export function getExternalStatus(signal?: AbortSignal) {
  return apiRequest<ExternalStatus>("/market-history/external/status", { signal });
}

export function getExternalSummary(signal?: AbortSignal) {
  return apiRequest<ExternalSummary>("/market-history/external/summary", { signal });
}

export function getExternalInstruments(
  params: { match_status?: string; research_eligible?: boolean; limit?: number; offset?: number },
  signal?: AbortSignal,
) {
  return apiRequest<{ items: ExternalInstrument[]; total: number }>(
    `/market-history/external/instruments${queryString(params)}`,
    { signal },
  );
}

export function getExternalCoverage(signal?: AbortSignal) {
  return apiRequest<{ items: CoverageYear[] }>("/market-history/external/coverage", { signal });
}

export function getExternalReconciliation(signal?: AbortSignal) {
  return apiRequest<{
    price_semantic: string;
    status_counts: Record<string, number>;
    items: ReconciliationItem[];
  }>("/market-history/external/reconciliation", { signal });
}

export function getExternalMlReadiness(signal?: AbortSignal) {
  return apiRequest<{
    years_ready: number;
    first_ready_year: number | null;
    items: MlYear[];
  }>("/market-history/external/ml-readiness", { signal });
}

export function getExternalCaProbes(signal?: AbortSignal) {
  return apiRequest<{ price_semantic: string; items: CaProbe[] }>(
    "/market-history/external/ca-probes",
    { signal },
  );
}
