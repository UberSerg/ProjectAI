import { apiRequest } from "./client";

export interface RelationSet {
  id: string;
  code: string;
  version: number;
  description?: string | null;
  parameters: Record<string, unknown>;
  is_active: boolean;
}

export interface RelationInput {
  id: string;
  code: string;
  input_family: string;
  subject_type: string;
  subject_id: string;
  feature_key: string;
  transform: string;
  alignment_policy: string;
  display_name?: string | null;
  is_active: boolean;
  metadata: Record<string, unknown>;
}

export interface RelationRun {
  id: string;
  relation_set_id: string;
  relation_set_code?: string | null;
  relation_set_version?: number | null;
  run_type: string;
  as_of_from?: string | null;
  as_of_to?: string | null;
  cadence?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  status: string;
  inputs_total: number;
  pairs_calculated: number;
  snapshots_written: number;
  snapshots_valid: number;
  snapshots_invalid: number;
  snapshots_skipped: number;
  source_watermark?: string | null;
  error_message?: string | null;
  workflow_id?: string | null;
}

export interface RelationSnapshot {
  id: string;
  relation_run_id: string;
  relation_set_id: string;
  relation_set_version: number;
  as_of_date: string;
  window_observations: number;
  input_a_id: string;
  input_b_id: string;
  input_a_code?: string | null;
  input_b_code?: string | null;
  input_a_display_name?: string | null;
  input_b_display_name?: string | null;
  sample_count: number;
  coverage_ratio?: number | null;
  pearson?: number | null;
  spearman?: number | null;
  rolling_corr_mean?: number | null;
  rolling_corr_std?: number | null;
  sign_consistency?: number | null;
  best_leader_input_id?: string | null;
  best_follower_input_id?: string | null;
  best_leader_code?: string | null;
  best_follower_code?: string | null;
  best_lag?: number | null;
  best_lag_pearson?: number | null;
  best_lag_spearman?: number | null;
  is_valid: boolean;
  quality_flags: Record<string, unknown>;
  calculated_at?: string | null;
}

export interface RelationLagMetric {
  id: string;
  snapshot_id: string;
  leader_input_id: string;
  follower_input_id: string;
  leader_code?: string | null;
  follower_code?: string | null;
  lag: number;
  pearson?: number | null;
  spearman?: number | null;
  sample_count: number;
  coverage_ratio?: number | null;
}

export interface RelationsOverview {
  active_relation_set: RelationSet | null;
  inputs_active: number;
  snapshots_total: number;
  latest_as_of_date?: string | null;
  last_relation_run: RelationRun | null;
  quality: { valid: number; invalid: number };
}

export interface PairDetail {
  snapshot: RelationSnapshot;
  lags: RelationLagMetric[];
  disclaimer: string;
}

export function getRelationsOverview(signal?: AbortSignal): Promise<RelationsOverview> {
  return apiRequest("/relations/overview", { signal });
}

export function getRelationRuns(limit = 15, signal?: AbortSignal): Promise<{ items: RelationRun[]; total: number }> {
  return apiRequest(`/relations/runs?limit=${limit}`, { signal });
}

export function getRelationSnapshots(
  params: {
    window?: number;
    min_abs_corr?: number;
    sign?: string;
    valid_only?: boolean;
    search?: string;
    limit?: number;
  } = {},
  signal?: AbortSignal,
): Promise<{ items: RelationSnapshot[]; total: number }> {
  const q = new URLSearchParams();
  if (params.window != null) q.set("window", String(params.window));
  if (params.min_abs_corr != null) q.set("min_abs_corr", String(params.min_abs_corr));
  if (params.sign) q.set("sign", params.sign);
  if (params.valid_only != null) q.set("valid_only", String(params.valid_only));
  if (params.search) q.set("search", params.search);
  if (params.limit != null) q.set("limit", String(params.limit));
  const qs = q.toString();
  return apiRequest(`/relations/snapshots${qs ? `?${qs}` : ""}`, { signal });
}

export function getPairDetail(
  inputAId: string,
  inputBId: string,
  window = 60,
  signal?: AbortSignal,
): Promise<PairDetail> {
  const q = new URLSearchParams({
    input_a_id: inputAId,
    input_b_id: inputBId,
    window: String(window),
  });
  return apiRequest(`/relations/pairs/detail?${q}`, { signal });
}

export function startRelationsComputeLatest(signal?: AbortSignal): Promise<{ workflow_id: number; status: string }> {
  return apiRequest("/relations/compute-latest", { method: "POST", signal });
}

export function startRelationsBackfill(body: {
  as_of_from: string;
  as_of_to?: string;
  cadence?: string;
}): Promise<{ workflow_id: number; status: string }> {
  return apiRequest("/relations/backfill", { method: "POST", body: JSON.stringify(body) });
}
