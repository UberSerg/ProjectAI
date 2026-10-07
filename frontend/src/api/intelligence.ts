import { apiRequest, queryString } from "./client";

export type SignalState = "POSITIVE" | "NEUTRAL" | "NEGATIVE" | "ABSTAIN" | "UNKNOWN";
export type AdvisoryState = "CONSIDER_INCREASE" | "HOLD" | "CONSIDER_REDUCE" | "ABSTAIN";
export type RiskState = "LOW" | "MODERATE" | "ELEVATED" | "HIGH" | "UNKNOWN";
export type CoverageStatus = "READY" | "PARTIAL" | "NOT_READY" | "UNKNOWN";

export interface CoverageItem {
  domain: string;
  status: CoverageStatus | string;
  detail?: string | null;
  last_known_at?: string | null;
}

export interface SignalOutput {
  model_id: string;
  model_version: string;
  semantic: string;
  instrument_id: number;
  as_of: string;
  known_at?: string | null;
  horizon: string;
  state: SignalState | string;
  score?: number | null;
  confidence?: number | null;
  confidence_semantic?: string;
  evidence_refs?: unknown[];
  limitations?: string[];
  abstain_reason?: string | null;
  data_freshness?: string | null;
}

export interface ModelVote {
  model_id: string;
  state: string;
  score?: number | null;
  confidence?: number | null;
  weight_applied?: number | null;
  note?: string | null;
}

export interface CommitteeDecision {
  as_of: string;
  instrument_id: number;
  advisory_state: AdvisoryState | string;
  confidence?: number | null;
  consensus_strength?: number | null;
  disagreement_score?: number | null;
  independent_model_votes: ModelVote[];
  primary_drivers?: string[];
  counterarguments?: string[];
  blockers?: string[];
  data_gaps?: string[];
  triggered_knowledge_rules?: string[];
  risk_overrides?: string[];
  what_would_change_decision?: string[];
  committee_policy_version?: string;
  limitations?: string[];
}

export interface RiskAssessment {
  as_of: string;
  instrument_id: number;
  risk_state: RiskState | string;
  risk_score?: number | null;
  risk_flags?: string[];
  liquidity_state?: string | null;
  volatility_state?: string | null;
  event_risk?: string | null;
  data_risk?: string | null;
  concentration_risk?: string | null;
  limitations?: string[];
}

export interface IntelligenceSnapshot {
  schema: string;
  instrument_id: number;
  symbol?: string | null;
  name?: string | null;
  as_of?: string | null;
  generated_at?: string | null;
  freshness?: string | null;
  coverage: CoverageItem[];
  signals: SignalOutput[];
  committee?: CommitteeDecision | null;
  risk?: RiskAssessment | null;
  fundamentals_summary: Record<string, unknown>;
  macro_summary: Record<string, unknown>;
  recent_events: Record<string, unknown>[];
  knowledge_evaluations: Record<string, unknown>[];
  intraday_summary: Record<string, unknown>;
  limitations: string[];
  production_isolation: Record<string, unknown>;
}

export interface IntelligenceRefreshResult {
  status: string;
  accepted: boolean;
  instrument_id: number;
  symbol?: string | null;
  as_of?: string | null;
  message?: string;
  production_isolation?: Record<string, unknown>;
}

export function getIntelligenceSnapshot(
  instrumentId: number,
  asOf?: string,
  signal?: AbortSignal,
): Promise<IntelligenceSnapshot> {
  return apiRequest<IntelligenceSnapshot>(
    `/intelligence/instruments/${instrumentId}${queryString({ as_of: asOf })}`,
    { signal },
  );
}

export function getIntelligenceSignals(
  instrumentId: number,
  asOf?: string,
  signal?: AbortSignal,
): Promise<{ instrument_id: number; signals: SignalOutput[] }> {
  return apiRequest(`/intelligence/instruments/${instrumentId}/signals${queryString({ as_of: asOf })}`, {
    signal,
  });
}

export function getIntelligenceCommittee(
  instrumentId: number,
  asOf?: string,
  signal?: AbortSignal,
): Promise<{
  instrument_id: number;
  committee: CommitteeDecision | null;
  what_would_change_decision: string[];
}> {
  return apiRequest(
    `/intelligence/instruments/${instrumentId}/committee${queryString({ as_of: asOf })}`,
    { signal },
  );
}

export function refreshIntelligence(
  instrumentId: number,
  body?: { as_of?: string; force?: boolean },
  signal?: AbortSignal,
): Promise<IntelligenceRefreshResult> {
  return apiRequest<IntelligenceRefreshResult>(`/intelligence/instruments/${instrumentId}/refresh`, {
    method: "POST",
    body: body ?? {},
    signal,
  });
}
