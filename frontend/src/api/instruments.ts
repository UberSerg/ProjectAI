import { apiRequest, queryString } from "./client";

export type SupportLevel = "FULL" | "PARTIAL" | "CATALOG_ONLY" | "INACTIVE" | string;

export interface CatalogInstrument {
  id: number;
  symbol: string;
  name: string;
  asset_class: string;
  instrument_subtype: string | null;
  support_level: SupportLevel;
  primary_board: string | null;
  exchange: string;
  currency: string;
  isin: string | null;
  is_active: boolean;
  sources: string[];
}

export interface CatalogInstrumentPage {
  items: CatalogInstrument[];
  total: number;
  page: number;
  page_size: number;
}

export interface InstrumentCapabilities {
  can_live_quote: boolean;
  can_portfolio_value: boolean;
  can_predict: boolean;
  can_fundamental: boolean;
  can_fixed_income_analyze: boolean;
  can_rebalance: boolean;
  can_cashflow_project: boolean;
  can_issuer_credit?: boolean;
  can_issue_credit?: boolean;
  reasons: Record<string, string>;
}

export interface InstrumentCoverage {
  live_quote: boolean;
  portfolio_value: boolean;
  predict: boolean;
  fundamental: boolean;
  fixed_income: boolean;
  rebalance: boolean;
  cashflow: boolean;
  issuer_credit?: boolean;
  issue_credit?: boolean;
}

export interface CatalogInstrumentSource {
  source: string;
  external_id: string | null;
  board: string | null;
  valid_from: string | null;
  valid_to: string | null;
}

export interface CatalogInstrumentDetail extends Omit<CatalogInstrument, "sources"> {
  first_seen_at: string | null;
  last_seen_at: string | null;
  research_member: boolean;
  capabilities: InstrumentCapabilities;
  coverage: InstrumentCoverage;
  sources: CatalogInstrumentSource[];
}

export interface InstrumentMasterSyncStatus {
  id?: number;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  report?: Record<string, unknown> | null;
}

export interface InstrumentMasterSyncTrigger {
  status: string;
  task_id?: string | null;
  report?: Record<string, unknown> | null;
}

export interface CatalogSearchParams {
  search?: string;
  q?: string;
  type?: string;
  asset_class?: string;
  active?: boolean;
  support?: string;
  page?: number;
  page_size?: number;
}

export function searchCatalogInstruments(
  params: CatalogSearchParams = {},
  signal?: AbortSignal,
): Promise<CatalogInstrumentPage> {
  return apiRequest(
    `/instruments${queryString({
      search: params.search,
      q: params.q,
      type: params.type,
      asset_class: params.asset_class,
      active: params.active,
      support: params.support,
      page: params.page,
      page_size: params.page_size,
    })}`,
    { signal },
  );
}

export function getCatalogInstrument(
  idOrSecid: string,
  signal?: AbortSignal,
): Promise<CatalogInstrumentDetail> {
  return apiRequest(`/instruments/${encodeURIComponent(idOrSecid)}`, { signal });
}

export function getInstrumentMasterSyncStatus(
  signal?: AbortSignal,
): Promise<InstrumentMasterSyncStatus> {
  return apiRequest("/instruments/master/sync/status", { signal });
}

export function triggerInstrumentMasterSync(
  asyncMode = true,
  signal?: AbortSignal,
): Promise<InstrumentMasterSyncTrigger> {
  return apiRequest(`/instruments/master/sync${queryString({ async_mode: asyncMode })}`, {
    method: "POST",
    signal,
  });
}
