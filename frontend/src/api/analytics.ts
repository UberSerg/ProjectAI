import { apiRequest } from "./client";

export interface FeatureSet {
  id: string;
  code: string;
  version: number;
  description?: string | null;
  parameters: Record<string, unknown>;
  is_active: boolean;
}

export interface FeatureRun {
  id: string;
  feature_set_id: string;
  feature_set_code?: string | null;
  feature_set_version?: number | null;
  run_type: string;
  date_from?: string | null;
  date_to?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  status: string;
  instruments_total: number;
  instrument_rows_calculated: number;
  series_rows_calculated: number;
  rows_valid: number;
  rows_invalid: number;
  rows_skipped: number;
  source_watermark?: string | null;
  error_message?: string | null;
  workflow_id?: string | null;
}

export interface InstrumentFeatures {
  id: string;
  instrument_id: string;
  date: string;
  timeframe: string;
  feature_set_id: string;
  feature_set_code?: string;
  feature_version: number;
  close?: number | null;
  volume?: number | null;
  return_1d?: number | null;
  return_2d?: number | null;
  return_3d?: number | null;
  return_5d?: number | null;
  return_10d?: number | null;
  return_20d?: number | null;
  log_return_1d?: number | null;
  volatility_5d?: number | null;
  volatility_20d?: number | null;
  drawdown_20d?: number | null;
  volume_change_1d?: number | null;
  volume_zscore_20d?: number | null;
  has_sufficient_history: boolean;
  is_valid: boolean;
  quality_flags: Record<string, unknown>;
  calculated_at?: string | null;
}

export interface AnalyticsOverview {
  active_feature_set: FeatureSet | null;
  instruments_active: number;
  instruments_with_features: number;
  instrument_feature_rows: number;
  latest_calculated_date?: string | null;
  last_feature_run: FeatureRun | null;
  quality: { valid: number; invalid: number; warnings: number };
}

export function getAnalyticsOverview(signal?: AbortSignal): Promise<AnalyticsOverview> {
  return apiRequest("/analytics/overview", { signal });
}

export function getFeatureSets(signal?: AbortSignal): Promise<{ items: FeatureSet[]; total: number }> {
  return apiRequest("/analytics/features/sets", { signal });
}

export function getFeatureRuns(limit = 20, signal?: AbortSignal): Promise<{ items: FeatureRun[]; total: number }> {
  return apiRequest(`/analytics/features/runs?limit=${limit}`, { signal });
}

export function getInstrumentFeaturesLatest(
  instrumentId: string,
  signal?: AbortSignal,
): Promise<InstrumentFeatures> {
  return apiRequest(`/analytics/instruments/${instrumentId}/features/latest`, { signal });
}

export function startFeatureUpdate(signal?: AbortSignal): Promise<{ workflow_id: number; status: string }> {
  return apiRequest("/analytics/features/update", { method: "POST", signal });
}

export function startFeatureBackfill(
  payload: { date_from: string; date_to?: string; feature_set_code?: string; feature_set_version?: number },
  signal?: AbortSignal,
): Promise<{ workflow_id: number; status: string }> {
  return apiRequest("/analytics/features/backfill", { method: "POST", body: payload, signal });
}

export function hasFeatureQualityWarning(flags: Record<string, unknown>): boolean {
  return Boolean(flags.price_discontinuity || flags.invalid_close);
}

export function hasInsufficientHistory(flags: Record<string, unknown>, field: string): boolean {
  const list = flags.insufficient_history;
  return Array.isArray(list) && list.includes(field);
}
