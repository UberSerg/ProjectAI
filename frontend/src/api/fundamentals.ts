import { apiRequest, queryString } from "./client";

/** Defensive shapes — backend is built in parallel; fields may be absent. */

export interface FundamentalsSummary {
  issuers_mapped?: number | null;
  issuers?: number | null;
  reports?: number | null;
  financial_facts?: number | null;
  facts?: number | null;
  dividend_events?: number | null;
  dividends?: number | null;
  corporate_events?: number | null;
  events?: number | null;
  coverage_start?: string | null;
  latest_update?: string | null;
  pit_quality?: string | null;
  status?: string | null;
  human_summary?: string | null;
  providers?: Array<{
    name?: string;
    code?: string;
    status?: string;
    note?: string;
    deferred?: boolean;
  }>;
  [key: string]: unknown;
}

export interface FundamentalsCoverageYear {
  year: number;
  issuers?: number | null;
  issuers_with_fundamentals?: number | null;
  count?: number | null;
  reports?: number | null;
}

export interface FundamentalsQuality {
  status?: string | null;
  pit_quality?: string | null;
  human_message?: string | null;
  message?: string | null;
  issuer_mappings?: number | null;
  unknown_mappings?: number | null;
  reports_without_known_at?: number | null;
  ambiguous_facts?: number | null;
  restatements?: number | null;
  rejected_rows?: number | null;
  coverage?: string | number | null;
  [key: string]: unknown;
}

export interface FundamentalsMlReadiness {
  status?: string | null;
  dataset_v2_features?: number | null;
  current_dataset_v2_features?: number | null;
  fundamental_v1_candidate_features?: number | null;
  event_v1_candidate_features?: number | null;
  potential_v3_total?: number | null;
  coverage?: string | number | null;
  pit_violations?: number | null;
  main_blockers?: string[] | null;
  blockers?: string[] | null;
  research_summary?: string | null;
  human_summary?: string | null;
  target_readiness?: Array<{
    code?: string;
    name?: string;
    label?: string;
    can_calculate?: string | boolean | null;
    pit_concern?: string | null;
    economic_meaning?: string | null;
    portfolio_alignment?: string | null;
    note?: string | null;
  }> | null;
  [key: string]: unknown;
}

export interface FundamentalSecurity {
  instrument_id?: string | number | null;
  ticker?: string | null;
  secid?: string | null;
  isin?: string | null;
  board?: string | null;
  name?: string | null;
}

export interface FundamentalIssuer {
  id: string | number;
  name?: string | null;
  title?: string | null;
  emitent_title?: string | null;
  inn?: string | null;
  emitent_inn?: string | null;
  emitent_id?: string | number | null;
  securities?: FundamentalSecurity[] | null;
  mapped_securities?: FundamentalSecurity[] | null;
  latest_report?: FundamentalReport | null;
  report_age_days?: number | null;
  reporting_standard?: string | null;
  status?: string | null;
  [key: string]: unknown;
}

export interface SourceProvenance {
  provider?: string | null;
  source_id?: string | null;
  external_id?: string | null;
  publication_timestamp?: string | null;
  published_at?: string | null;
  retrieved_timestamp?: string | null;
  retrieved_at?: string | null;
  hash?: string | null;
  content_hash?: string | null;
  version?: string | number | null;
  [key: string]: unknown;
}

export interface FundamentalReport {
  id?: string | number;
  reporting_period?: string | null;
  period_label?: string | null;
  period_end?: string | null;
  standard?: string | null;
  reporting_standard?: string | null;
  publication_date?: string | null;
  published_at?: string | null;
  known_at?: string | null;
  version?: number | string | null;
  revenue?: number | null;
  net_income?: number | null;
  ebitda?: number | null;
  cash_flow?: number | null;
  status?: string | null;
  is_restatement?: boolean | null;
  restatement_of?: string | number | null;
  provenance?: SourceProvenance | null;
  source?: SourceProvenance | null;
  [key: string]: unknown;
}

export interface FundamentalDividend {
  id?: string | number;
  announcement_date?: string | null;
  recommendation_date?: string | null;
  approval_date?: string | null;
  record_date?: string | null;
  payment_date?: string | null;
  amount?: number | null;
  currency?: string | null;
  dividend_yield?: number | null;
  yield?: number | null;
  status?: string | null;
  known_at?: string | null;
  stage?: string | null;
  provenance?: SourceProvenance | null;
  source?: SourceProvenance | null;
  [key: string]: unknown;
}

export interface FundamentalEvent {
  id?: string | number;
  event_type?: string | null;
  type?: string | null;
  event_date?: string | null;
  effective_date?: string | null;
  known_at?: string | null;
  title?: string | null;
  description?: string | null;
  provenance?: SourceProvenance | null;
  source?: SourceProvenance | null;
  [key: string]: unknown;
}

export interface FundamentalAsOf {
  as_of?: string | null;
  date?: string | null;
  latest_report?: FundamentalReport | null;
  report?: FundamentalReport | null;
  dividends?: FundamentalDividend[] | null;
  dividend_state?: FundamentalDividend[] | null;
  events?: FundamentalEvent[] | null;
  known_events?: FundamentalEvent[] | null;
  notes?: string[] | null;
  [key: string]: unknown;
}

function asArray<T>(payload: unknown, keys: string[] = ["items", "rows", "data"]): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === "object") {
    const obj = payload as Record<string, unknown>;
    for (const key of keys) {
      const value = obj[key];
      if (Array.isArray(value)) return value as T[];
    }
  }
  return [];
}

export function getFundamentalsSummary(signal?: AbortSignal): Promise<FundamentalsSummary> {
  return apiRequest("/fundamentals/summary", { signal });
}

export function listFundamentalIssuers(
  params: { limit?: number; offset?: number; q?: string } = {},
  signal?: AbortSignal,
): Promise<{ items: FundamentalIssuer[]; total?: number }> {
  return apiRequest(`/fundamentals/issuers${queryString(params)}`, { signal }).then((payload) => ({
    items: asArray<FundamentalIssuer>(payload, ["issuers", "items", "rows", "data"]),
    total:
      payload && typeof payload === "object" && "total" in payload
        ? Number((payload as { total?: unknown }).total)
        : undefined,
  }));
}

export function getFundamentalIssuer(
  issuerId: string | number,
  signal?: AbortSignal,
): Promise<FundamentalIssuer> {
  return apiRequest(`/fundamentals/issuers/${issuerId}`, { signal });
}

export function getIssuerReports(
  issuerId: string | number,
  signal?: AbortSignal,
): Promise<FundamentalReport[]> {
  return apiRequest(`/fundamentals/issuers/${issuerId}/reports`, { signal }).then((payload) =>
    asArray<FundamentalReport>(payload),
  );
}

export function getIssuerDividends(
  issuerId: string | number,
  signal?: AbortSignal,
): Promise<FundamentalDividend[]> {
  return apiRequest(`/fundamentals/issuers/${issuerId}/dividends`, { signal }).then((payload) =>
    asArray<FundamentalDividend>(payload),
  );
}

export function getIssuerEvents(
  issuerId: string | number,
  signal?: AbortSignal,
): Promise<FundamentalEvent[]> {
  return apiRequest(`/fundamentals/issuers/${issuerId}/events`, { signal }).then((payload) =>
    asArray<FundamentalEvent>(payload),
  );
}

export function getIssuerAsOf(
  issuerId: string | number,
  date: string,
  signal?: AbortSignal,
): Promise<FundamentalAsOf> {
  return apiRequest(`/fundamentals/issuers/${issuerId}/as-of${queryString({ date })}`, { signal });
}

export function getFundamentalsCoverage(signal?: AbortSignal): Promise<FundamentalsCoverageYear[]> {
  return apiRequest("/fundamentals/coverage", { signal }).then((payload) => {
    const items = asArray<FundamentalsCoverageYear>(payload, ["items", "years", "rows", "data"]);
    return items
      .map((row) => ({
        ...row,
        year: Number(row.year),
        issuers: row.issuers_with_fundamentals ?? row.issuers ?? row.count ?? null,
      }))
      .filter((row) => Number.isFinite(row.year));
  });
}

export function getFundamentalsMlReadiness(signal?: AbortSignal): Promise<FundamentalsMlReadiness> {
  return apiRequest("/fundamentals/ml-readiness", { signal });
}

export function getFundamentalsProviders(signal?: AbortSignal): Promise<FundamentalsProvidersResponse> {
  return apiRequest("/fundamentals/providers", { signal });
}

export interface FundamentalsProviderRow {
  code?: string;
  name?: string;
  name_ru?: string;
  provider?: string;
  configured?: boolean;
  enabled?: boolean;
  reachable?: boolean | null;
  authenticated?: boolean | null;
  operational_status?: string;
  status?: string;
  pit_capability?: string;
  timestamp_quality?: string;
  access_model?: string;
  last_successful_request?: string | null;
  human_explanation?: string;
  note?: string;
  deferred?: boolean;
}

export interface FundamentalsProvidersResponse {
  providers?: FundamentalsProviderRow[];
  human_summary?: string;
}

export function providerStatusLabel(status?: string | null): string {
  const raw = (status ?? "").toUpperCase();
  if (raw === "READY") return "Работает";
  if (raw === "READY_REQUIRES_CREDENTIALS") return "Нужен доступ";
  if (raw === "READY_REQUIRES_SUBSCRIPTION") return "Нужна подписка";
  if (raw === "MANUAL_ONLY") return "Только вручную";
  if (raw === "DEGRADED") return "Ограничен";
  if (raw === "UNAVAILABLE") return "Выключен";
  return status?.trim() || "—";
}

export function getFundamentalsQuality(signal?: AbortSignal): Promise<FundamentalsQuality> {
  return apiRequest("/fundamentals/quality", { signal });
}

export function qualityHumanMessage(status?: string | null, fallback?: string | null): string {
  const raw = (status ?? "").toUpperCase();
  if (raw === "GOOD") return "Данные пригодны для PIT-исследований.";
  if (raw === "PARTIAL") return "Часть истории не имеет точной даты публикации.";
  if (raw === "NOT_READY") return "Нельзя безопасно использовать в ML.";
  return fallback?.trim() || "Статус качества пока неизвестен — источники могут быть отложены.";
}

export function issuerDisplayName(issuer?: FundamentalIssuer | null): string {
  return (
    issuer?.name?.trim() ||
    issuer?.title?.trim() ||
    issuer?.emitent_title?.trim() ||
    (issuer?.id != null ? String(issuer.id) : "Эмитент")
  );
}

export function reportPeriodLabel(report?: FundamentalReport | null): string {
  return (
    report?.period_label?.trim() ||
    report?.reporting_period?.trim() ||
    report?.period_end?.trim() ||
    "—"
  );
}

export function reportStandard(report?: FundamentalReport | null): string {
  return report?.standard?.trim() || report?.reporting_standard?.trim() || "—";
}

export function provenanceOf(
  row?: { provenance?: SourceProvenance | null; source?: SourceProvenance | null } | null,
): SourceProvenance | null {
  return row?.provenance ?? row?.source ?? null;
}
