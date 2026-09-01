import { apiRequest, queryString } from "./client";

export interface FactorContributions {
  trend?: number | null;
  momentum?: number | null;
  rsi?: number | null;
  volume?: number | null;
}

export interface TechnicalRun {
  id: string;
  run_type: string;
  model_code: string;
  model_version: number;
  model_config_hash: string;
  date_from?: string | null;
  date_to?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  status: string;
  instruments_total: number;
  technical_feature_rows: number;
  signal_rows: number;
  valid_signals: number;
  invalid_signals: number;
  source_watermark?: Record<string, unknown> | null;
  error_message?: string | null;
  workflow_id?: string | null;
}

export interface TechnicalSignal {
  id: string;
  instrument_id: string;
  ticker?: string | null;
  as_of_date: string;
  score: number;
  confidence: number;
  direction: string;
  model_code: string;
  model_version: number;
  model_config_hash: string;
  factor_contributions: FactorContributions;
  is_valid: boolean;
  quality_flags: Record<string, unknown>;
  rsi14?: number | null;
  sma20_distance?: number | null;
  ema20_distance?: number | null;
  atr14_pct?: number | null;
  volume_zscore_20d?: number | null;
  return_5d?: number | null;
  return_20d?: number | null;
  calculated_at?: string | null;
}

export interface TechnicalOverview {
  active_model: string;
  technical_feature_set: string;
  as_of?: string | null;
  instruments_analyzed: number;
  bullish: number;
  neutral: number;
  bearish: number;
  invalid: number;
  warnings: number;
  last_run: TechnicalRun | null;
}

export interface TechnicalModelInfo {
  model_code: string;
  model_version: number;
  config: Record<string, unknown>;
  config_hash: string;
  is_active: boolean;
}

export interface WorkflowStart {
  workflow_id: string;
  status: string;
}

export function getTechnicalOverview(signal?: AbortSignal): Promise<TechnicalOverview> {
  return apiRequest("/technical/overview", { signal });
}

export function getTechnicalModels(signal?: AbortSignal): Promise<TechnicalModelInfo[]> {
  return apiRequest("/technical/models", { signal });
}

export function getTechnicalRuns(limit = 15, signal?: AbortSignal): Promise<TechnicalRun[]> {
  return apiRequest(`/technical/runs${queryString({ limit })}`, { signal });
}

export function getTechnicalSignals(
  params: {
    date?: string;
    date_from?: string;
    date_to?: string;
    direction?: string;
    min_confidence?: number;
    valid_only?: boolean;
    instrument?: string;
    limit?: number;
    offset?: number;
  } = {},
  signal?: AbortSignal,
): Promise<TechnicalSignal[]> {
  return apiRequest(
    `/technical/signals${queryString({
      date: params.date,
      date_from: params.date_from,
      date_to: params.date_to,
      direction: params.direction,
      min_confidence: params.min_confidence,
      valid_only: params.valid_only,
      instrument: params.instrument,
      limit: params.limit,
      offset: params.offset,
    })}`,
    { signal },
  );
}

export function getInstrumentTechnicalLatest(
  instrumentId: string,
  signal?: AbortSignal,
): Promise<TechnicalSignal> {
  return apiRequest(`/technical/instruments/${encodeURIComponent(instrumentId)}/latest`, { signal });
}

export function getInstrumentTechnicalHistory(
  instrumentId: string,
  params: { date_from?: string; date_to?: string; limit?: number; offset?: number } = {},
  signal?: AbortSignal,
): Promise<TechnicalSignal[]> {
  return apiRequest(
    `/technical/instruments/${encodeURIComponent(instrumentId)}/history${queryString({
      date_from: params.date_from,
      date_to: params.date_to,
      limit: params.limit,
      offset: params.offset,
    })}`,
    { signal },
  );
}

export function startTechnicalBackfill(body: {
  date_from: string;
  date_to?: string;
  instrument_ids?: number[];
  model_code?: string;
  model_version?: number;
}): Promise<WorkflowStart> {
  return apiRequest("/technical/backfill", { method: "POST", body });
}

export function startTechnicalUpdate(body?: {
  model_code?: string;
  model_version?: number;
}): Promise<WorkflowStart> {
  return apiRequest("/technical/update", { method: "POST", body: body ?? {} });
}
