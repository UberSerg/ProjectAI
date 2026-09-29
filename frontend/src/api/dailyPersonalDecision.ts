import { apiRequest } from "./client";

export type DailyDecisionStatus =
  | "NEEDS_SETUP"
  | "LEGACY_PENDING"
  | "DRAFT_ANALYSIS"
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

export type DecisionConfidenceStatus = "SUFFICIENT" | "PARTIAL" | "LOW" | string;

export type DecisionScenarioId =
  | "DO_NOTHING"
  | "HOLD_CASH"
  | "TARGET_UNDERWEIGHTS"
  | "KRAKEN_ALLOCATION"
  | "FIXED_INCOME_ALTERNATIVE"
  | string;

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

export interface DecisionScenarioPurchase {
  symbol?: string | null;
  sleeve?: string | null;
  target_rub?: string | null;
  lots?: number | null;
  units?: number | null;
  estimated_notional?: string | null;
  executable_estimated_notional_rub?: string | null;
  residual_cash_rub?: string | null;
  residual_unexecuted_rub?: string | null;
  lot_rounding_residual_rub?: string | null;
  lot_size?: number | null;
  execution_status?: string | null;
  limitations?: string[];
  note?: string | null;
}

export interface DecisionScenario {
  id: DecisionScenarioId;
  title: string;
  status: string;
  reason?: string | null;
  deployed_rub?: string | null;
  target_allocation_rub?: string | null;
  executable_notional_rub?: string | null;
  advisory_only_rub?: string | null;
  residual_cash_rub?: string | null;
  residual_unexecuted_rub?: string | null;
  external_unallocated_rub?: string | null;
  portfolio_nav_after_rub?: string | null;
  execution_status?: string | null;
  cash_share?: number | null;
  equity_share?: number | null;
  fixed_income_share?: number | null;
  purchases?: DecisionScenarioPurchase[];
  facts?: string[];
  limitations?: string[];
  cbr_context?: {
    cbr_hurdle_annual?: number | string | null;
    wording?: string | null;
  } | null;
}

export interface DailyPersonalDecision {
  engine_version?: string;
  as_of: string;
  status: DailyDecisionStatus;
  headline: string;
  summary: string;
  portfolio: {
    id: number;
    portfolio_id?: number;
    name?: string;
    portfolio_name?: string;
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
    candidate_as_of?: string | null;
    candidate_stale?: boolean | null;
    candidate_freshness_known?: boolean | null;
    candidate_freshness_reason?: string | null;
    candidate_age_days?: number | null;
    rebalance_available?: boolean;
    research_decision_status?: string | null;
    research_equity_weight?: number | null;
    research_cash_weight?: number | null;
    research_used_personal_nav?: boolean;
    what_can_change_decision?: string[];
    dataset_v3_drives_decision?: boolean;
  };
  new_cash_rub?: string;
  new_cash_plan?: {
    requested_new_cash_rub?: string;
    current_nav_rub?: string;
    current_cash_rub?: string;
    hypothetical_total_capital_rub?: string;
    selected_scenario_hint?: string | null;
    note?: string;
  } | null;
  scenario_comparison?: DecisionScenario[];
  data_confidence?: {
    status: DecisionConfidenceStatus;
    reasons?: string[];
    note?: string;
  } | null;
  limitations?: string[];
  degradations?: string[];
  disclaimer: string;
}

export function getDailyPersonalDecision(
  portfolioId: number,
  options?: {
    signal?: AbortSignal;
    test?: boolean;
    newCashRub?: number | string | null;
  },
): Promise<DailyPersonalDecision> {
  const params = new URLSearchParams();
  if (options?.test) params.set("test", "true");
  if (options?.newCashRub != null && options.newCashRub !== "" && Number(options.newCashRub) > 0) {
    params.set("new_cash_rub", String(options.newCashRub));
  }
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiRequest<DailyPersonalDecision>(`/personal-portfolios/${portfolioId}/daily-decision${qs}`, {
    signal: options?.signal,
  });
}
