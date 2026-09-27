import { apiRequest } from "./client";

export type PersonalOperationType =
  | "DEPOSIT"
  | "WITHDRAWAL"
  | "BUY"
  | "SELL"
  | "COMMISSION"
  | "OPENING_CASH"
  | "OPENING_POSITION";

export interface PersonalSummary {
  portfolio: {
    id: number;
    name: string;
    base_currency: string;
    status: string;
    is_test: boolean;
    note?: string | null;
    version: number;
    has_operations: boolean;
  };
  summary: {
    cash_rub: string;
    securities_value_rub: string;
    nav_rub: string;
    contributed_rub: string;
    withdrawn_rub: string;
    investment_pnl_rub: string | null;
    realized_pnl_rub: string;
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
    instrument_id: number;
    secid: string | null;
    name: string | null;
    units: string;
    lots: string | null;
    lot_size?: number | null;
    average_price: string | null;
    current_price: string | null;
    price_date: string | null;
    market_value: string | null;
    unrealized_pnl: string | null;
    price_available: boolean;
    price_label?: string | null;
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

export function getPersonalPrimary(opts?: { owner?: boolean; test?: boolean; signal?: AbortSignal }) {
  return apiRequest<PersonalSummary>(`/personal-portfolios/primary${qs(!!opts?.owner, !!opts?.test)}`, {
    signal: opts?.signal,
  });
}

export function createPersonalOperation(
  body: CreatePersonalOperationBody,
  opts?: { test?: boolean; idempotencyKey?: string; signal?: AbortSignal },
) {
  const headers: Record<string, string> = {};
  if (opts?.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
  return apiRequest<{ operation_id: number; portfolio: PersonalSummary }>(
    `/personal-portfolios/primary/operations${qs(false, !!opts?.test)}`,
    {
      method: "POST",
      body: JSON.stringify(body),
      headers,
      signal: opts?.signal,
    },
  );
}

export function getPersonalReconciliation(opts?: { test?: boolean; signal?: AbortSignal }) {
  return apiRequest(`/personal-portfolios/primary/reconciliation${qs(false, !!opts?.test)}`, {
    signal: opts?.signal,
  });
}
