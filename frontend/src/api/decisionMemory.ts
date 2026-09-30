import { apiRequest, queryString } from "./client";

export type DecisionOutcomeStatus =
  | "PENDING"
  | "READY"
  | "DATA_UNAVAILABLE"
  | "BASELINE_UNAVAILABLE"
  | string;

export interface DecisionMemoryBaseline {
  status: "AVAILABLE" | "UNAVAILABLE" | string;
  price: string | null;
  market_date: string | null;
  price_source: string | null;
  observed_at: string | null;
}

export interface DecisionMemoryOutcome {
  id: number;
  decision_action_id: number;
  horizon_sessions: number;
  status: DecisionOutcomeStatus;
  target_session_date: string | null;
  observed_session_date: string | null;
  baseline_price: string | null;
  observed_price: string | null;
  /** Always PRICE_RETURN: raw close-to-close, dividends not included. */
  return_type: string;
  /** Decimal fraction (0.05 = +5%). */
  forward_return: string | null;
  directional_alignment: "ALIGNED" | "NOT_ALIGNED" | null | string;
  provenance: Record<string, unknown>;
  refreshed_at: string | null;
}

export interface DecisionMemoryLink {
  id: number;
  decision_action_id: number;
  portfolio_id: number;
  personal_operation_id: number;
  link_source: string;
  linked_at: string | null;
  unlinked_at: string | null;
  active: boolean;
  already_linked?: boolean;
}

export interface DecisionMemoryAction {
  id: number;
  decision_record_id: number;
  original_action_id: string;
  action: string;
  priority: string | null;
  symbol: string | null;
  instrument_id: number | null;
  reason_codes: string[];
  target_weight: string | null;
  current_weight: string | null;
  lots_delta: string | null;
  units_delta: string | null;
  estimated_notional: string | null;
  limitations: string[];
  /** Original Daily Decision action (title, rationale, facts...). */
  action_payload: Record<string, unknown> | null;
  baseline: DecisionMemoryBaseline;
  links: DecisionMemoryLink[];
  outcomes: DecisionMemoryOutcome[];
}

export interface DecisionMemoryRecordSummary {
  id: number;
  portfolio_id: number;
  portfolio_name_snapshot: string | null;
  captured_at: string | null;
  decision_as_of: string | null;
  engine_version: string;
  new_cash_rub: string | null;
  status: string | null;
  headline: string | null;
  canonical_hash: string;
  hash_verified: boolean;
  idempotency_key: string;
  candidate_provenance: Record<string, unknown>;
  broker_fee_provenance: Record<string, unknown>;
  created_at: string | null;
  disclaimer: string;
  actions_count?: number;
}

export interface DecisionMemoryRecord extends DecisionMemoryRecordSummary {
  decision_payload?: Record<string, unknown>;
  actions?: DecisionMemoryAction[];
  idempotent_replay?: boolean;
}

export interface DecisionMemoryList {
  portfolio_id: number;
  items: DecisionMemoryRecordSummary[];
  count: number;
}

export interface PossibleOperationMatch {
  label: "POSSIBLE_MATCH" | string;
  personal_operation_id: number;
  operation_type: string;
  occurred_at: string | null;
  instrument_id: number | null;
  lots: string | null;
  units: string | null;
  price: string | null;
  amount: string | null;
  commission: string | null;
  already_linked: boolean;
}

export interface PossibleMatchesResponse {
  decision_action_id: number;
  action: string;
  window: { from: string | null; to: string | null; upper_bound: string };
  matches: PossibleOperationMatch[];
  reason: string | null;
  disclaimer: string;
}

export interface RefreshOutcomesResult {
  portfolio_id: number | null;
  refreshed_at: string | null;
  evaluated: number;
  ready: number;
  data_unavailable: number;
  still_pending: number;
}

export interface DecisionMemoryHorizonSummary {
  horizon_sessions: number;
  status_counts: Record<string, number>;
  ready_count: number;
  directional_ready_count: number;
  aligned_count: number;
  not_aligned_count: number;
  alignment_rate: string | null;
  mean_price_return: string | null;
  sample_warning: boolean;
}

export interface DecisionMemorySummary {
  portfolio_id: number;
  engine_version: string;
  decisions_count: number;
  actions_count: number;
  linked_actions_count: number;
  return_type: string;
  horizons: DecisionMemoryHorizonSummary[];
  limitations: string[];
  disclaimer: string;
}

interface CommonOptions {
  test?: boolean;
  signal?: AbortSignal;
}

function base(portfolioId: number): string {
  return `/personal-portfolios/${portfolioId}/decision-memory`;
}

function testQuery(test?: boolean): string {
  return queryString({ test: test ? true : undefined });
}

export function newIdempotencyKey(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  return `dm-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export function captureDecisionMemory(
  portfolioId: number,
  options: CommonOptions & { newCashRub?: number | string | null; idempotencyKey?: string } = {},
): Promise<DecisionMemoryRecord> {
  const cash = options.newCashRub;
  const hasCash = cash != null && cash !== "" && Number(cash) > 0;
  return apiRequest<DecisionMemoryRecord>(`${base(portfolioId)}/capture${testQuery(options.test)}`, {
    method: "POST",
    headers: { "Idempotency-Key": options.idempotencyKey ?? newIdempotencyKey() },
    body: hasCash ? { new_cash_rub: Number(cash) } : undefined,
    signal: options.signal,
  });
}

export function listDecisionMemory(
  portfolioId: number,
  options: CommonOptions & { limit?: number } = {},
): Promise<DecisionMemoryList> {
  return apiRequest<DecisionMemoryList>(
    `${base(portfolioId)}${queryString({ test: options.test ? true : undefined, limit: options.limit })}`,
    { signal: options.signal },
  );
}

export function getDecisionMemory(
  portfolioId: number,
  decisionId: number,
  options: CommonOptions = {},
): Promise<DecisionMemoryRecord> {
  return apiRequest<DecisionMemoryRecord>(`${base(portfolioId)}/${decisionId}${testQuery(options.test)}`, {
    signal: options.signal,
  });
}

export function getPossibleMatches(
  portfolioId: number,
  actionId: number,
  options: CommonOptions = {},
): Promise<PossibleMatchesResponse> {
  return apiRequest<PossibleMatchesResponse>(
    `${base(portfolioId)}/actions/${actionId}/possible-matches${testQuery(options.test)}`,
    { signal: options.signal },
  );
}

export function linkOperation(
  portfolioId: number,
  actionId: number,
  personalOperationId: number,
  options: CommonOptions = {},
): Promise<DecisionMemoryLink> {
  return apiRequest<DecisionMemoryLink>(`${base(portfolioId)}/actions/${actionId}/links${testQuery(options.test)}`, {
    method: "POST",
    body: { personal_operation_id: personalOperationId },
    signal: options.signal,
  });
}

export function unlinkOperation(
  portfolioId: number,
  linkId: number,
  options: CommonOptions = {},
): Promise<DecisionMemoryLink> {
  return apiRequest<DecisionMemoryLink>(`${base(portfolioId)}/links/${linkId}${testQuery(options.test)}`, {
    method: "DELETE",
    signal: options.signal,
  });
}

export function refreshDecisionOutcomes(
  portfolioId: number,
  options: CommonOptions = {},
): Promise<RefreshOutcomesResult> {
  return apiRequest<RefreshOutcomesResult>(`${base(portfolioId)}/outcomes/refresh${testQuery(options.test)}`, {
    method: "POST",
    signal: options.signal,
  });
}

export function getDecisionMemorySummary(
  portfolioId: number,
  options: CommonOptions = {},
): Promise<DecisionMemorySummary> {
  return apiRequest<DecisionMemorySummary>(`${base(portfolioId)}/summary${testQuery(options.test)}`, {
    signal: options.signal,
  });
}
