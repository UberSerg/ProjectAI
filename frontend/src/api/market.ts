import { apiRequest, queryString } from "./client";

export interface Instrument {
  id: string;
  symbol: string;
  name: string;
  asset_class: string;
  exchange: string | null;
  currency: string;
  sources: string[];
  first_timestamp: string | null;
  last_timestamp: string | null;
  records_count: number;
  is_active: boolean;
  mappings?: InstrumentMapping[];
}

export interface InstrumentMapping {
  source: string;
  source_symbol: string;
}

export interface Candle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  source?: string;
}

export interface Batch {
  id: string;
  source: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  records_received?: number;
  records_written?: number;
  error?: string | null;
}

export interface DataQualityIssue {
  id: string;
  instrument_id?: string;
  symbol?: string;
  severity: "warning" | "error" | "info";
  issue_type: string;
  message: string;
  detected_at: string;
  resolved_at?: string | null;
}

export interface MarketSummary {
  instruments_count: number;
  active_instruments_count: number;
  records_count: number;
  batches_count: number;
  dq_warnings: number;
  dq_errors: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface InstrumentFilters {
  search?: string;
  asset_class?: string;
  source?: string;
  active?: boolean;
  page?: number;
  page_size?: number;
}

function asPage<T>(value: Page<T> | T[], page = 1, pageSize = 25): Page<T> {
  if (Array.isArray(value)) return { items: value, total: value.length, page, page_size: pageSize };
  return value;
}

export async function getInstruments(filters: InstrumentFilters = {}, signal?: AbortSignal): Promise<Page<Instrument>> {
  const page = filters.page ?? 1;
  const pageSize = filters.page_size ?? 25;
  const response = await apiRequest<Page<Instrument> | Instrument[]>(
    `/market/instruments${queryString({ ...filters, page, page_size: pageSize })}`,
    { signal },
  );
  return asPage(response, page, pageSize);
}

export function getInstrument(id: string, signal?: AbortSignal): Promise<Instrument> {
  return apiRequest(`/market/instruments/${encodeURIComponent(id)}`, { signal });
}

export async function getCandles(id: string, limit = 30, signal?: AbortSignal): Promise<Candle[]> {
  const response = await apiRequest<Candle[] | { items: Candle[] }>(
    `/market/instruments/${encodeURIComponent(id)}/candles${queryString({ timeframe: "1d", limit })}`,
    { signal },
  );
  return Array.isArray(response) ? response : response.items;
}

export async function getBatches(instrumentId?: string, signal?: AbortSignal): Promise<Batch[]> {
  const response = await apiRequest<Batch[] | { items: Batch[] }>(
    `/market/batches${queryString({ instrument_id: instrumentId, limit: 10 })}`,
    { signal },
  );
  return Array.isArray(response) ? response : response.items;
}

export async function getDataQualityIssues(instrumentId?: string, signal?: AbortSignal): Promise<DataQualityIssue[]> {
  const response = await apiRequest<DataQualityIssue[] | { items: DataQualityIssue[] }>(
    `/market/data-quality${queryString({ instrument_id: instrumentId, page_size: 50 })}`,
    { signal },
  );
  return Array.isArray(response) ? response : response.items;
}

export function getMarketSummary(signal?: AbortSignal): Promise<MarketSummary> {
  return apiRequest("/market/summary", { signal });
}

export interface BackfillRequest {
  symbols?: string[];
  instruments?: string[];
  date_from?: string;
  date_to?: string;
  default_universe?: boolean;
}

export interface WorkflowAccepted {
  workflow_id: string | number;
  status: string;
}

export function runMarketUpdate(): Promise<WorkflowAccepted> {
  return apiRequest("/market/update", { method: "POST" });
}

export function runBackfill(request: BackfillRequest): Promise<WorkflowAccepted> {
  const body = {
    symbols: request.symbols ?? request.instruments,
    date_from: request.date_from,
    date_to: request.date_to,
    default_universe: request.default_universe ?? !(request.symbols ?? request.instruments)?.length,
  };
  return apiRequest("/market/backfill", { method: "POST", body });
}

export function runDataQuality(): Promise<WorkflowAccepted> {
  return apiRequest("/market/data-quality/run", { method: "POST" });
}
