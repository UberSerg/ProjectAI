import type { SimulationFill, SimulationOrder } from "../../api/simulator";
import { computeCutoff } from "./format";
import type { DecisionActionKind, DecisionExplanationContext } from "./types";

function num(value: unknown): number | null {
  if (typeof value === "number" && !Number.isNaN(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && !Number.isNaN(Number(value))) {
    return Number(value);
  }
  return null;
}

function metaNumber(meta: Record<string, unknown> | null | undefined, key: string): number | null {
  return num(meta?.[key]);
}

function inferActionKind(side?: string | null, reason?: string | null): DecisionActionKind {
  const r = (reason ?? "").toUpperCase();
  if (r.includes("BELOW_MIN_WEIGHT_DELTA") || r.includes("HOLD_WITHIN")) return "HOLD";
  if (r.startsWith("DD_GUARD")) return "RISK";
  const s = (side ?? "").toUpperCase();
  if (s === "BUY") return "BUY";
  if (s === "SELL") return "SELL";
  return "UNKNOWN";
}

function policyDefaults(policyName?: string | null): {
  entryQuantile: number | null;
  exitQuantile: number | null;
  minTradeWeightDelta: number | null;
} {
  if (policyName === "RANK_HYSTERESIS_LONG_ONLY_V1") {
    return { entryQuantile: 0.2, exitQuantile: 0.35, minTradeWeightDelta: 0.02 };
  }
  if (policyName === "RANK_LONG_ONLY_V0") {
    return { entryQuantile: 0.2, exitQuantile: null, minTradeWeightDelta: null };
  }
  return { entryQuantile: null, exitQuantile: null, minTradeWeightDelta: null };
}

function resolvePredictionCandidate(
  meta: Record<string, unknown> | null | undefined,
  extras?: Partial<DecisionExplanationContext>,
): string | null {
  if (typeof meta?.prediction_candidate === "string" && meta.prediction_candidate) {
    return meta.prediction_candidate;
  }
  const name = typeof meta?.candidate_name === "string" ? meta.candidate_name : null;
  const version = typeof meta?.candidate_version === "string" ? meta.candidate_version : null;
  if (name && version) return `${name}/${version}`;
  if (name) return name;
  return extras?.predictionCandidate ?? null;
}

export function contextFromSimulatorFill(
  fill: SimulationFill,
  extras?: Partial<DecisionExplanationContext>,
): DecisionExplanationContext {
  const meta = (fill as SimulationFill & { metadata?: Record<string, unknown> | null }).metadata ?? null;
  const policyName = fill.policy_name ?? null;
  const defaults = policyDefaults(policyName);
  const eligible =
    num((fill as { eligible_count?: number | null }).eligible_count) ??
    metaNumber(meta, "eligible_n") ??
    metaNumber(meta, "eligible_count");
  const entryQuantile = defaults.entryQuantile;
  const exitQuantile = defaults.exitQuantile;
  const semantic =
    (typeof meta?.prediction_semantic === "string" ? meta.prediction_semantic : null) ??
    (extras?.predictionSemantic ?? null);
  const score =
    metaNumber(meta, "prediction_score") ??
    (semantic === "RANKING_SCORE" ? null : fill.predicted_return_20d ?? null);
  return {
    reasonCode: fill.reason,
    ticker: fill.ticker,
    displayName: (fill as { display_name?: string | null }).display_name ?? null,
    side: fill.side,
    actionKind: inferActionKind(fill.side, fill.reason),
    predictedReturn20d: semantic === "RANKING_SCORE" ? null : fill.predicted_return_20d,
    predictionSemantic: semantic ?? "EXPECTED_RETURN",
    predictionScore: score,
    rank: fill.rank,
    eligibleCount: eligible,
    targetWeight: fill.target_weight,
    entryQuantile,
    exitQuantile,
    entryCutoff: computeCutoff(eligible, entryQuantile),
    exitCutoff: computeCutoff(eligible, exitQuantile),
    minTradeWeightDelta: defaults.minTradeWeightDelta,
    policyName,
    predictionDate: fill.prediction_date,
    decisionDate: fill.decision_date ?? fill.prediction_date,
    executionDate: fill.execution_date,
    executionRule: "NEXT_OPEN",
    orderStatus: "FILLED",
    rawOpen: fill.raw_open,
    fillPrice: fill.fill_price,
    foldId: fill.fold_id,
    kind: "HISTORICAL_SIMULATOR",
    metadata: meta,
    predictionCandidate: resolvePredictionCandidate(meta, extras),
    ...extras,
  };
}

export function contextFromSimulatorOrder(
  order: SimulationOrder,
  extras?: Partial<DecisionExplanationContext>,
): DecisionExplanationContext {
  const meta = order.metadata ?? null;
  const policyName = order.policy_name ?? null;
  const defaults = policyDefaults(policyName);
  const eligible = metaNumber(meta, "eligible_n") ?? metaNumber(meta, "eligible_count");
  const semantic =
    (typeof meta?.prediction_semantic === "string" ? meta.prediction_semantic : null) ??
    (extras?.predictionSemantic ?? null);
  return {
    reasonCode: order.reason,
    ticker: order.ticker,
    side: order.side,
    actionKind: inferActionKind(order.side, order.reason),
    predictedReturn20d: semantic === "RANKING_SCORE" ? null : order.predicted_return_20d,
    predictionSemantic: semantic ?? "EXPECTED_RETURN",
    predictionScore: metaNumber(meta, "prediction_score"),
    rank: order.rank,
    eligibleCount: eligible,
    targetWeight: order.target_weight,
    entryQuantile: defaults.entryQuantile,
    exitQuantile: defaults.exitQuantile,
    entryCutoff: computeCutoff(eligible, defaults.entryQuantile),
    exitCutoff: computeCutoff(eligible, defaults.exitQuantile),
    minTradeWeightDelta: defaults.minTradeWeightDelta,
    policyName,
    predictionDate: order.prediction_date,
    decisionDate: order.decision_date,
    executionDate: order.execution_date,
    executionRule: "NEXT_OPEN",
    orderStatus: "FILLED",
    foldId: order.fold_id,
    kind: "HISTORICAL_SIMULATOR",
    metadata: meta,
    predictionCandidate: resolvePredictionCandidate(meta, extras),
    ...extras,
  };
}

/** Adapter for Shadow Portfolio order payloads (API / fixtures). */
export function contextFromShadowOrder(
  order: {
    ticker: string;
    side: string;
    reason?: string | null;
    predicted_return_20d?: number | null;
    rank?: number | null;
    eligible_count?: number | null;
    target_weight?: number | null;
    status?: string | null;
    min_execution_date?: string | null;
    decision_at?: string | null;
    metadata?: Record<string, unknown> | null;
    display_name?: string | null;
    policy_name?: string | null;
    risk_name?: string | null;
  },
  extras?: Partial<DecisionExplanationContext>,
): DecisionExplanationContext {
  const meta = order.metadata ?? null;
  const policyName =
    order.policy_name ?? (typeof meta?.policy === "string" ? meta.policy : "RANK_HYSTERESIS_LONG_ONLY_V1");
  const defaults = policyDefaults(policyName);
  const eligible = order.eligible_count ?? metaNumber(meta, "eligible_n");
  const signalAsOf = typeof meta?.signal_as_of === "string" ? meta.signal_as_of : null;
  const generatedAt =
    typeof meta?.signal_generated_at === "string" ? meta.signal_generated_at : null;
  const batchId = meta?.forward_batch_id ?? null;
  const semantic =
    (typeof meta?.prediction_semantic === "string" ? meta.prediction_semantic : null) ??
    (extras?.predictionSemantic ?? null);
  return {
    reasonCode: order.reason,
    ticker: order.ticker,
    displayName: order.display_name ?? null,
    side: order.side,
    actionKind: inferActionKind(order.side, order.reason),
    predictedReturn20d: semantic === "RANKING_SCORE" ? null : order.predicted_return_20d,
    predictionSemantic: semantic ?? "EXPECTED_RETURN",
    predictionScore: metaNumber(meta, "prediction_score"),
    rank: order.rank,
    eligibleCount: eligible,
    targetWeight: order.target_weight,
    entryQuantile: defaults.entryQuantile,
    exitQuantile: defaults.exitQuantile,
    entryCutoff: computeCutoff(eligible, defaults.entryQuantile),
    exitCutoff: computeCutoff(eligible, defaults.exitQuantile),
    minTradeWeightDelta: defaults.minTradeWeightDelta,
    policyName,
    riskPolicyName: order.risk_name ?? null,
    riskState: typeof meta?.risk_mode === "string" ? meta.risk_mode : null,
    predictionDate: signalAsOf,
    decisionAt: order.decision_at,
    decisionDate: order.decision_at?.slice(0, 10) ?? null,
    orderStatus: order.status ?? "PENDING",
    minExecutionDate: order.min_execution_date,
    executionRule: "FORWARD_NEXT_OPEN",
    predictionBatchId: batchId as string | number | null,
    predictionGeneratedAt: generatedAt,
    kind: "FORWARD_SHADOW",
    metadata: meta,
    predictionCandidate: resolvePredictionCandidate(meta, extras),
    ...extras,
  };
}
