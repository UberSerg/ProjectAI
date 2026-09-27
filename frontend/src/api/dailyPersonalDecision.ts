import { apiRequest } from "./client";

export type DailyDecisionStatus =
  | "NEEDS_SETUP"
  | "LEGACY_PENDING"
  | "READY"
  | "PARTIAL"
  | "NO_ACTION"
  | "UNAVAILABLE"
  | string;

export type DailyDecisionActionType =
  | "SETUP"
  | "ACTIVATE_JOURNAL"
  | "DATA_QUALITY"
  | "REVIEW"
  | "CONSIDER_INCREASE"
  | "CONSIDER_REDUCE"
  | "KEEP_CASH"
  | "HOLD"
  | string;

export type DailyDecisionPriority = "HIGH" | "MEDIUM" | "LOW" | string;

export interface DailyDecisionAction {
  id: string;
  priority: DailyDecisionPriority;
  action: DailyDecisionActionType;
  symbol?: string | null;
  title: string;
  rationale: string;
  reason_codes: string[];
  facts: string[];
  current_weight?: number | null;
  target_weight?: number | null;
  lots_delta?: number | null;
  units_delta?: number | null;
  estimated_notional?: number | null;
  href?: string | null;
  limitations?: string[];
}

export interface DailyDecisionRisk {
  code?: string | null;
  severity?: string | null;
  message?: string | null;
  symbol?: string | null;
}

export interface DailyPersonalDecision {
  as_of: string;
  status: DailyDecisionStatus;
  headline: string;
  summary: string;
  portfolio: {
    id: number;
    journal_state: string;
    cash_rub: string;
    securities_value_rub: string;
    nav_rub: string;
    contributed_rub: string;
    withdrawn_rub: string;
    investment_pnl_rub: string | null;
    symbols: string[];
  };
  actions: DailyDecisionAction[];
  risks: DailyDecisionRisk[];
  data_quality: {
    valuation_complete: boolean;
    valuation_partial: boolean;
    valuation_as_of: string | null;
    valuation_from: string | null;
    valuation_to: string | null;
    valuation_label: string | null;
    missing_price_count: number;
    coverage_pct?: number | null;
    quality?: string | null;
    degradations: string[];
  };
  context: {
    candidate_source?: string | null;
    candidate_id?: string | null;
    rebalance_available?: boolean;
    research_decision_status?: string | null;
    research_equity_weight?: number | null;
    research_cash_weight?: number | null;
    research_used_personal_nav?: boolean;
    what_can_change_decision?: string[];
  };
  disclaimer: string;
}

export function getDailyPersonalDecision(options?: {
  signal?: AbortSignal;
  test?: boolean;
}): Promise<DailyPersonalDecision> {
  const qs = options?.test ? "?test=true" : "";
  return apiRequest<DailyPersonalDecision>(`/personal-portfolios/primary/daily-decision${qs}`, {
    signal: options?.signal,
  });
}
