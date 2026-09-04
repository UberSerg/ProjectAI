/** Factual context for deterministic decision explanations (no LLM). */

export type DecisionActionKind = "BUY" | "SELL" | "HOLD" | "NO_TRADE" | "RISK" | "UNKNOWN";

export type OrderLifecycleStatus = "PENDING" | "FILLED" | "CANCELLED" | "BLOCKED" | string;

export interface DecisionExplanationContext {
  reasonCode?: string | null;
  ticker?: string | null;
  displayName?: string | null;
  side?: string | null;
  /** BUY/SELL/HOLD/NO_TRADE semantics for wording. */
  actionKind?: DecisionActionKind | null;
  predictedReturn20d?: number | null;
  rank?: number | null;
  eligibleCount?: number | null;
  targetWeight?: number | null;
  currentWeight?: number | null;
  entryQuantile?: number | null;
  exitQuantile?: number | null;
  entryCutoff?: number | null;
  exitCutoff?: number | null;
  minTradeWeightDelta?: number | null;
  policyName?: string | null;
  policyVersion?: string | null;
  riskPolicyName?: string | null;
  riskState?: string | null;
  drawdown?: number | null;
  previousExposureCap?: number | null;
  newExposureCap?: number | null;
  predictionDate?: string | null;
  decisionDate?: string | null;
  decisionAt?: string | null;
  executionDate?: string | null;
  executionRule?: string | null;
  orderStatus?: OrderLifecycleStatus | null;
  minExecutionDate?: string | null;
  rawOpen?: number | null;
  fillPrice?: number | null;
  orderId?: string | number | null;
  fillId?: string | number | null;
  predictionCandidate?: string | null;
  predictionBatchId?: string | number | null;
  predictionGeneratedAt?: string | null;
  predictionHash?: string | null;
  candidateConfigHash?: string | null;
  policyConfigHash?: string | null;
  foldId?: string | null;
  kind?: "HISTORICAL_SIMULATOR" | "FORWARD_SHADOW" | string | null;
  metadata?: Record<string, unknown> | null;
}

export interface TechnicalField {
  label: string;
  value: string;
}

export interface TimelineItem {
  dateLabel: string;
  label: string;
}

export interface DecisionExplanation {
  reasonCode: string;
  shortTitle: string;
  summary: string;
  detailed: string;
  technical: TechnicalField[];
  timeline: TimelineItem[];
  usedFallback: boolean;
}
