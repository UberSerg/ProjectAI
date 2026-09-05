import { apiRequest } from "./client";

export interface HurdleQuote {
  status: string;
  as_of?: string;
  annual_rate?: number;
  hurdle_return?: number;
  hurdle_20d?: number;
  hurdle_1y?: number;
  known_at_quality?: string;
  source?: string;
  disclaimer?: string;
}

export interface ReadinessCheck {
  code: string;
  status: string;
}

export interface BondInstrument {
  instrument_id: number;
  symbol: string;
  name: string;
  bond_type: string;
  currency?: string | null;
  currency_display?: string | null;
  currency_raw?: string | null;
  nominal?: number | null;
  lot_size?: number | null;
  maturity_date?: string | null;
  support_status: string;
  credit_quality_status: string;
  real_portfolio_eligible: boolean;
  support_reasons?: string[];
  support_reasons_ru?: string[];
  why_not_supported?: string | null;
  credit_safety_note?: string;
  clean_price_percent?: number | null;
  nkd?: number | null;
  dirty_estimate?: number | null;
  ytm?: number | null;
  ytm_note?: string | null;
  duration?: number | null;
  next_coupon_date?: string | null;
  next_coupon_amount?: number | null;
  data_quality?: {
    known_at_quality?: string;
    source?: string;
  };
}

export interface AllocationPosition {
  symbol: string;
  lots: number;
  units: number;
  notional: string | number;
  fees: string | number;
  cash_used: string | number;
}

export interface AccountingPreview {
  status: string;
  symbol?: string;
  lots?: number;
  quantity?: number;
  clean_total?: string | number;
  nkd_total?: string | number;
  dirty_purchase?: string | number;
  fees?: string | number;
  cash_required?: string | number;
  coupon_total?: string | number;
  redemption_total?: string | number;
  total_return_before_tax?: string | number;
  ytm_value?: string | number | null;
  ytm_note?: string;
  disclaimer?: string;
  support_status?: string;
  reasons?: string[];
  note?: string;
}

export const getHurdle = (signal?: AbortSignal) =>
  apiRequest<HurdleQuote>("/investment/hurdle?horizon=1y", { signal });

export const getInvestmentReadiness = (signal?: AbortSignal) =>
  apiRequest<{ status: string; checks: ReadinessCheck[] }>("/investment/readiness", { signal });

export const getBonds = (signal?: AbortSignal) =>
  apiRequest<{ items: BondInstrument[] }>("/fixed-income/instruments", { signal });

export const getBondAccountingPreview = (symbol: string, lots = 1, signal?: AbortSignal) =>
  apiRequest<AccountingPreview>(
    `/fixed-income/instruments/${encodeURIComponent(symbol)}/accounting-preview?lots=${lots}`,
    { signal },
  );

export const previewAllocation = (body: {
  capital: number;
  cost_bps: number;
  candidates: Array<{
    symbol: string;
    sleeve: string;
    price: number;
    lot_size: number;
    target_weight: number;
  }>;
}) =>
  apiRequest<{
    positions: AllocationPosition[];
    fees: string | number;
    cash_remainder: string | number;
    diagnostics: string[];
    mode: string;
  }>("/portfolio/allocation/preview", { method: "POST", body });
