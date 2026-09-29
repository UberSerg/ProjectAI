import { apiRequest } from "./client";

export type LifecycleState = "DRAFT" | "ACTIVE" | "EMPTY";

export type PersonalOperationType =
  | "DEPOSIT"
  | "WITHDRAWAL"
  | "BUY"
  | "SELL"
  | "COMMISSION"
  | "OPENING_CASH"
  | "OPENING_POSITION";

export interface PortfolioCard {
  id: number;
  name: string;
  description?: string | null;
  lifecycle_state: LifecycleState | string;
  cash_rub: string;
  positions_count: number;
  // Collection view is unpriced — NAV and valuation labels come from the
  // single-portfolio summary, never from the list.
  known_nav_rub?: string | null;
  valuation_partial?: boolean;
  valuation_label?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
  is_test?: boolean;
}

export interface PersonalSummary {
  portfolio: {
    id: number;
    name: string;
    description?: string | null;
    base_currency: string;
    lifecycle_state?: LifecycleState | string;
    status: string;
    is_test: boolean;
    note?: string | null;
    version: number;
    has_operations: boolean;
    journal_state?: LifecycleState | "EMPTY" | "LEGACY_PENDING" | "ACTIVE" | "DRAFT";
    journal_cutover_at?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
  };
  summary: {
    cash_rub: string;
    securities_value_rub: string;
    nav_rub: string;
    contributed_rub: string;
    withdrawn_rub: string;
    investment_pnl_rub: string | null;
    realized_pnl_rub: string;
    cost_basis_complete?: boolean;
    cost_basis_incomplete_reason?: string | null;
    cost_basis_incomplete_history?: boolean;
    investment_pnl_unavailable_reason?: "MISSING_PRICE" | "COST_BASIS_INCOMPLETE" | null;
    investment_pnl_message?: string | null;
    valuation_complete: boolean;
    valuation_partial: boolean;
    valuation_as_of: string | null;
    valuation_from?: string | null;
    valuation_to?: string | null;
    valuation_label: string;
    missing_price_count: number;
    known_nav_rub?: string;
  };
  positions: Array<{
    id?: number;
    instrument_id: number;
    secid: string | null;
    name: string | null;
    asset_class?: string | null;
    units: string;
    lots: string | null;
    lot_size?: number | null;
    average_price: string | null;
    cost_basis_total_rub?: string | null;
    cost_basis_status?: "KNOWN" | "UNKNOWN" | string;
    current_price: string | null;
    price_date: string | null;
    market_value: string | null;
    unrealized_pnl: string | null;
    price_available: boolean;
    price_label?: string | null;
    pnl_unavailable_reason?: string | null;
  }>;
  operations: Array<{
    id: number;
    operation_type: string;
    status: string;
    occurred_at: string | null;
    instrument_id: number | null;
    lots: string | null;
    units: string | null;
    price: string | null;
    amount: string | null;
    commission: string;
    currency: string;
    note: string | null;
    source?: string;
    idempotency_key?: string;
    supersedes_operation_id?: number | null;
    correction_reason?: string | null;
  }>;
  recommendation_disclaimer: string;
  reconciliation?: {
    status: string;
    cash_ok: boolean;
    positions_ok: boolean;
  };
}

export interface CreatePersonalOperationBody {
  operation_type: PersonalOperationType;
  occurred_at: string;
  instrument_id?: number;
  lots?: string;
  units?: string;
  price?: string;
  amount?: string;
  commission?: string;
  note?: string;
  non_standard_lot?: boolean;
  idempotency_key?: string;
  supersedes_operation_id?: number;
  correction_reason?: string;
}

function qs(owner: boolean, test: boolean): string {
  const p = new URLSearchParams();
  if (owner) p.set("owner", "true");
  if (test) p.set("test", "true");
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function listPersonalPortfolios(opts?: { test?: boolean; signal?: AbortSignal }) {
  return apiRequest<{ items: PortfolioCard[]; count: number }>(
    `/personal-portfolios${qs(false, !!opts?.test)}`,
    { signal: opts?.signal },
  );
}

export function createPersonalPortfolio(
  body: { name: string; description?: string },
  opts?: { test?: boolean; signal?: AbortSignal },
) {
  return apiRequest<PersonalSummary>(`/personal-portfolios${qs(false, !!opts?.test)}`, {
    method: "POST",
    body,
    signal: opts?.signal,
  });
}

export function getPersonalPortfolio(
  portfolioId: number,
  opts?: { owner?: boolean; test?: boolean; signal?: AbortSignal },
) {
  return apiRequest<PersonalSummary>(
    `/personal-portfolios/${portfolioId}${qs(!!opts?.owner, !!opts?.test)}`,
    { signal: opts?.signal },
  );
}

export function patchPersonalPortfolio(
  portfolioId: number,
  body: { name?: string; description?: string | null },
  opts?: { test?: boolean; signal?: AbortSignal },
) {
  return apiRequest<PersonalSummary>(`/personal-portfolios/${portfolioId}${qs(false, !!opts?.test)}`, {
    method: "PATCH",
    body,
    signal: opts?.signal,
  });
}

export function deletePersonalPortfolio(portfolioId: number, opts?: { test?: boolean; signal?: AbortSignal }) {
  return apiRequest<{ status: string; id: number; name: string }>(
    `/personal-portfolios/${portfolioId}${qs(false, !!opts?.test)}`,
    { method: "DELETE", signal: opts?.signal },
  );
}

export function setDraftCash(
  portfolioId: number,
  cashRub: string | number,
  opts?: { test?: boolean; signal?: AbortSignal },
) {
  return apiRequest<PersonalSummary>(
    `/personal-portfolios/${portfolioId}/draft/cash${qs(false, !!opts?.test)}`,
    {
      method: "PUT",
      body: { cash_rub: cashRub },
      signal: opts?.signal,
    },
  );
}

export function addDraftPosition(
  portfolioId: number,
  body: {
    instrument_id: number;
    units?: string | number;
    lots?: string | number;
    average_price?: string | number | null;
    cost_basis_total_rub?: string | number | null;
    note?: string;
    non_standard_lot?: boolean;
  },
  opts?: { test?: boolean; signal?: AbortSignal },
) {
  return apiRequest<{ id: number; portfolio: PersonalSummary }>(
    `/personal-portfolios/${portfolioId}/draft/positions${qs(false, !!opts?.test)}`,
    {
      method: "POST",
      body,
      signal: opts?.signal,
    },
  );
}

export function patchDraftPosition(
  portfolioId: number,
  positionId: number,
  body: Record<string, unknown>,
  opts?: { test?: boolean; signal?: AbortSignal },
) {
  return apiRequest<{ id: number; portfolio: PersonalSummary }>(
    `/personal-portfolios/${portfolioId}/draft/positions/${positionId}${qs(false, !!opts?.test)}`,
    {
      method: "PATCH",
      body,
      signal: opts?.signal,
    },
  );
}

export function deleteDraftPosition(
  portfolioId: number,
  positionId: number,
  opts?: { test?: boolean; signal?: AbortSignal },
) {
  return apiRequest<{ status: string; id: number; portfolio: PersonalSummary }>(
    `/personal-portfolios/${portfolioId}/draft/positions/${positionId}${qs(false, !!opts?.test)}`,
    { method: "DELETE", signal: opts?.signal },
  );
}

export function clearDraftPortfolio(portfolioId: number, opts?: { test?: boolean; signal?: AbortSignal }) {
  return apiRequest<PersonalSummary>(
    `/personal-portfolios/${portfolioId}/draft/clear${qs(false, !!opts?.test)}`,
    { method: "POST", signal: opts?.signal },
  );
}

export function activatePersonalPortfolio(
  portfolioId: number,
  opts?: { test?: boolean; signal?: AbortSignal },
) {
  return apiRequest<PersonalSummary>(
    `/personal-portfolios/${portfolioId}/activate${qs(false, !!opts?.test)}`,
    { method: "POST", signal: opts?.signal },
  );
}

export function resetPersonalPortfolio(
  portfolioId: number,
  opts?: { test?: boolean; signal?: AbortSignal },
) {
  return apiRequest<PersonalSummary>(
    `/personal-portfolios/${portfolioId}/reset${qs(false, !!opts?.test)}`,
    { method: "POST", signal: opts?.signal },
  );
}

export function createPersonalOperation(
  portfolioId: number,
  body: CreatePersonalOperationBody,
  opts?: { test?: boolean; idempotencyKey?: string; signal?: AbortSignal },
) {
  const headers: Record<string, string> = {};
  if (opts?.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
  return apiRequest<{ operation_id: number; portfolio: PersonalSummary }>(
    `/personal-portfolios/${portfolioId}/operations${qs(false, !!opts?.test)}`,
    {
      method: "POST",
      body,
      headers,
      signal: opts?.signal,
    },
  );
}

export function getPersonalReconciliation(
  portfolioId: number,
  opts?: { test?: boolean; signal?: AbortSignal },
) {
  return apiRequest(`/personal-portfolios/${portfolioId}/reconciliation${qs(false, !!opts?.test)}`, {
    signal: opts?.signal,
  });
}

export function getPortfolioAnalysis(portfolioId: number, opts?: { signal?: AbortSignal }) {
  return apiRequest(`/personal-portfolios/${portfolioId}/analysis`, { signal: opts?.signal });
}

export function getPortfolioCompareCandidate(portfolioId: number, opts?: { signal?: AbortSignal }) {
  return apiRequest(`/personal-portfolios/${portfolioId}/compare-candidate`, { signal: opts?.signal });
}

export function getPortfolioRebalance(portfolioId: number, opts?: { signal?: AbortSignal }) {
  return apiRequest(`/personal-portfolios/${portfolioId}/rebalance`, { signal: opts?.signal });
}

export function getPortfolioCashflows(portfolioId: number, opts?: { signal?: AbortSignal }) {
  return apiRequest(`/personal-portfolios/${portfolioId}/cashflows`, { signal: opts?.signal });
}
