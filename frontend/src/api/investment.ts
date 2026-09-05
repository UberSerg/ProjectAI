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
  credit_status?: string;
  liquidity_status?: string;
  investment_eligibility?: string;
  accounting_quality?: string;
  risk_flags?: string[];
  warnings?: string[];
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

export const getFixedIncomeRisk = (signal?: AbortSignal) =>
  apiRequest<{
    as_of: string;
    total_bonds: number;
    credit_coverage: Record<string, number>;
    liquidity_coverage: Record<string, number>;
    eligibility_coverage: Record<string, number>;
    summary_ru?: string;
    allocation_warnings: string[];
    items: Array<{
      symbol: string;
      bond_type: string;
      credit_status: string;
      liquidity_status: string;
      investment_eligibility: string;
      accounting_quality: string;
      yield_hint: number | null;
      risk_flags: string[];
      warnings: string[];
    }>;
  }>("/fixed-income/risk", { signal });

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

export interface AllocationDecisionView {
  policy_id: string;
  equity_weight: number;
  fixed_income_weight: number;
  cash_weight: number;
  weights_pct: { equity: number; fixed_income: number; cash: number };
  reason_codes: string[];
  reason_codes_ru: string[];
  explanation_ru: string;
  status: string;
  confidence: number | null;
  limitations: string[];
  bond_safety_reminder: string;
}

export interface AllocationDecideResponse {
  context: Record<string, unknown>;
  decision: AllocationDecisionView;
  lots: {
    sleeve_cash_used: Record<string, string>;
    target_weights: { equity: number; fixed_income: number; cash: number };
    lot_result: {
      cash_remainder: string | number;
      fees: string | number;
      positions: AllocationPosition[];
    };
  };
  economic_verdict: {
    question_ru: string;
    answer_ru: string;
    cbr_hurdle_return?: number | null;
  };
  mode: string;
}

export const getAllocationPolicies = (signal?: AbortSignal) =>
  apiRequest<{ policies: Array<{ id: string; title: string; kind: string }> }>(
    "/allocation/policies",
    { signal },
  );

export const decideAllocation = (
  body: {
    policy_id: string;
    capital: number;
    equity_expected_excess_return?: number | null;
    equity_price?: number;
    equity_lot_size?: number;
    bond_price?: number;
    bond_lot_size?: number;
    cost_bps?: number;
  },
  signal?: AbortSignal,
) =>
  apiRequest<AllocationDecideResponse>("/allocation/decide", {
    method: "POST",
    body,
    signal,
  });

export const compareAllocations = (
  params?: { capital?: number; equity_expected_excess_return?: number | null },
  signal?: AbortSignal,
) => {
  const q = new URLSearchParams();
  if (params?.capital != null) q.set("capital", String(params.capital));
  if (params?.equity_expected_excess_return != null) {
    q.set("equity_expected_excess_return", String(params.equity_expected_excess_return));
  }
  const suffix = q.toString() ? `?${q}` : "";
  return apiRequest<{
    comparisons: Array<{
      policy: { id: string; title: string };
      decision: AllocationDecisionView;
    }>;
    note: string;
  }>(`/allocation/compare${suffix}`, { signal });
};

export interface CalibrationBucketView {
  name: string;
  n: number;
  mean_predicted: number | null;
  mean_realized: number | null;
  hit_rate: number | null;
  mean_error: number | null;
}

export interface InvestmentDecisionView {
  profile_id: string;
  equity_weight: number;
  fixed_income_weight: number;
  cash_weight: number;
  weights_pct: { equity: number; fixed_income: number; cash: number };
  reason_codes: string[];
  explanations: string[];
  warnings: string[];
  status: string;
  why_equity_ru: string;
  why_fixed_income_ru: string;
  why_cash_ru: string;
  limitations: string[];
}

export interface InvestmentDecisionResponse {
  as_of: string;
  capital: string;
  cbr_hurdle_annual: number | null;
  hurdle_20d?: number | null;
  hurdle_1y?: number | null;
  profile_id: string;
  equity_opportunity: {
    expected_return: number | null;
    expected_excess_return: number | null;
    confidence: number | null;
    model_source: string | null;
    calibration_status?: string;
    confidence_level?: string;
    confidence_reason?: string;
    sample_size?: number | null;
    prediction_quality?: string;
    limitations?: string[];
  } | null;
  fixed_income_opportunity: {
    expected_yield: number | null;
    duration: number | null;
    credit_quality: string;
    liquidity: string;
    data_quality: string;
    yield_source?: string | null;
    liquidity_status?: string | null;
    support_status?: string | null;
    supported_ratio?: number | null;
    credit_status?: string | null;
    investment_eligibility?: string | null;
    risk_flags?: string[];
  } | null;
  cash_opportunity: {
    annual_rate: number | null;
    horizon_return: number | null;
    source: string;
    quality: string;
  } | null;
  calibration: {
    sample_size: number;
    bias: number | null;
    mae: number | null;
    hit_rate: number | null;
    calibration_status: string;
    uncertainty_note: string;
    buckets: CalibrationBucketView[];
    limitations: string[];
  };
  equity_confidence?: {
    confidence_level: string;
    reason_ru: string;
    sample_size: number | null;
    calibration_status: string;
    reason_codes: string[];
  };
  risk_budget: Record<string, unknown>;
  decision: InvestmentDecisionView;
  lots: AllocationDecideResponse["lots"];
  economic_metrics: {
    return: number | null;
    excess_vs_cbr: number | null;
    max_drawdown: number | null;
    volatility: number | null;
    turnover: number | null;
    question_ru: string;
    answer_ru: string;
  };
  bond_safety_reminder: string;
  mode: string;
  fixed_income_risk_summary?: {
    summary_ru?: string;
    warnings?: string[];
    credit_status?: string | null;
    liquidity_status?: string | null;
    investment_eligibility?: string | null;
    risk_flags?: string[];
  };
}

export const decideInvestment = (
  body: {
    profile_id: string;
    capital: number;
    equity_expected_excess_return?: number | null;
    equity_expected_return?: number | null;
    volatility?: number | null;
    drawdown?: number | null;
  },
  signal?: AbortSignal,
) =>
  apiRequest<InvestmentDecisionResponse>("/investment-decision/decide", {
    method: "POST",
    body,
    signal,
  });

export const compareInvestmentDecisions = (
  params?: { capital?: number; equity_expected_excess_return?: number | null },
  signal?: AbortSignal,
) => {
  const q = new URLSearchParams();
  if (params?.capital != null) q.set("capital", String(params.capital));
  if (params?.equity_expected_excess_return != null) {
    q.set("equity_expected_excess_return", String(params.equity_expected_excess_return));
  }
  const suffix = q.toString() ? `?${q}` : "";
  return apiRequest<{
    profiles: Array<{ profile_id: string; decision: InvestmentDecisionView }>;
    static_benchmarks: Array<{
      policy: { id: string; title: string };
      decision: AllocationDecisionView;
    }>;
    cbr_benchmark: { annual_rate: number | null; note: string };
    note: string;
  }>(`/investment-decision/compare${suffix}`, { signal });
};

export const getEquityCalibration = (signal?: AbortSignal) =>
  apiRequest<{
    sample_size: number;
    bias: number | null;
    mae: number | null;
    hit_rate: number | null;
    calibration_status: string;
    uncertainty_note: string;
    buckets: CalibrationBucketView[];
    limitations: string[];
  }>("/investment-decision/calibration", { signal });

export interface CalibrationReport {
  generated_at: string;
  pipeline: string;
  candidate_v0: {
    id: string;
    title: string;
    semantic: string;
    calibration: {
      sample_count: number;
      pending_count: number;
      coverage: number | null;
      bias: number | null;
      mae: number | null;
      direction_accuracy: number | null;
      calibration_status: string;
      uncertainty_note: string;
      bias_sign?: string;
      buckets: Array<{
        bucket_name: string;
        sample_count: number;
        average_prediction: number | null;
        average_realized_return: number | null;
        median_realized_return: number | null;
        error: number | null;
        bias: number | null;
        win_rate: number | null;
      }>;
    };
    confidence: {
      confidence_level: string;
      reason_ru: string;
      sample_size: number;
      calibration_status: string;
      reason_codes: string[];
    };
  };
  candidate_v1: {
    id: string;
    title: string;
    semantic: string;
    calibration: {
      sample_count: number;
      pending_count: number;
      coverage: number | null;
      mean_spearman_rank_ic: number | null;
      mean_top20_realized: number | null;
      mean_bottom20_realized: number | null;
      mean_top_minus_bottom: number | null;
      calibration_status: string;
      uncertainty_note: string;
      rank_bucket_realized: Array<Record<string, number | string | null>>;
    };
    confidence: {
      confidence_level: string;
      reason_ru: string;
      sample_size: number;
      calibration_status: string;
    };
  };
  chart_data: {
    v0_buckets: Array<{
      bucket: string;
      average_prediction: number | null;
      average_realized_return: number | null;
      sample_count: number;
    }>;
  };
  note: string;
}

export const getCalibrationReport = (signal?: AbortSignal) =>
  apiRequest<CalibrationReport>("/calibration", { signal });

export interface PortfolioRiskPosition {
  symbol: string;
  sleeve: string;
  status: string;
  reason_codes: string[];
  explanations_ru: string[];
  warnings_ru: string[];
  allowed_in_portfolio: boolean;
  target_weight: number;
}

export interface PortfolioRiskResponse {
  capital: string;
  policy_id: string;
  profile_id: string;
  pipeline: string;
  allocation: {
    equity_weight: number;
    fixed_income_weight: number;
    cash_weight: number;
    status: string;
    explanation_ru: string;
  };
  risk_assessment: {
    status: string;
    capital: string;
    positions: PortfolioRiskPosition[];
    approved: string[];
    approved_with_warnings: string[];
    research_only: string[];
    blocked: string[];
    insufficient_data: string[];
    reason_codes: string[];
    explanations_ru: string[];
    warnings_ru: string[];
    limitations: string[];
    summary_ru: string;
  };
  note: string;
  mode: string;
}

export const assessPortfolioRisk = (
  body?: {
    capital?: number;
    equity_expected_excess_return?: number | null;
    profile_id?: string;
    policy_id?: string;
  },
  signal?: AbortSignal,
) =>
  apiRequest<PortfolioRiskResponse>("/portfolio-risk/assess", {
    method: "POST",
    body: {
      capital: body?.capital ?? 100000,
      equity_expected_excess_return: body?.equity_expected_excess_return ?? 0,
      profile_id: body?.profile_id ?? "BALANCED_ALLOCATION_V0",
      policy_id: body?.policy_id ?? "CBR_HURDLE_GATE_V0",
    },
    signal,
  });
