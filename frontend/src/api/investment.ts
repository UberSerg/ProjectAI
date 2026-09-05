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
  maturity_date?: string | null;
  support_status: string;
  credit_quality_status: string;
  real_portfolio_eligible: boolean;
}

export interface AllocationPosition {
  symbol: string;
  lots: number;
  units: number;
  notional: string | number;
  fees: string | number;
  cash_used: string | number;
}

export const getHurdle = (signal?: AbortSignal) =>
  apiRequest<HurdleQuote>("/investment/hurdle?horizon=1y", { signal });

export const getInvestmentReadiness = (signal?: AbortSignal) =>
  apiRequest<{ status: string; checks: ReadinessCheck[] }>("/investment/readiness", { signal });

export const getBonds = (signal?: AbortSignal) =>
  apiRequest<{ items: BondInstrument[] }>("/fixed-income/instruments", { signal });

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
