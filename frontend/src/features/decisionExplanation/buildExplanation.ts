import { formatRuDate, formatSignedPercent, formatWeightPercent } from "./format";
import { modelDisplayName, policyDisplayName, riskDisplayName } from "./labels";
import { getReasonDefinition } from "./registry";
import type {
  DecisionExplanation,
  DecisionExplanationContext,
  TechnicalField,
  TimelineItem,
} from "./types";

function pushField(fields: TechnicalField[], label: string, value: unknown): void {
  if (value == null || value === "") return;
  fields.push({ label, value: String(value) });
}

function buildTechnical(ctx: DecisionExplanationContext, reasonCode: string): TechnicalField[] {
  const fields: TechnicalField[] = [];
  pushField(fields, "Reason code", reasonCode);
  if (ctx.reasonCode && ctx.reasonCode !== reasonCode) {
    pushField(fields, "Reason code (raw)", ctx.reasonCode);
  }
  pushField(fields, "Policy", ctx.policyName);
  pushField(fields, "Policy (human)", policyDisplayName(ctx.policyName));
  pushField(fields, "Policy version", ctx.policyVersion);
  pushField(fields, "Risk policy", ctx.riskPolicyName);
  pushField(fields, "Risk policy (human)", riskDisplayName(ctx.riskPolicyName));
  pushField(fields, "Risk state", ctx.riskState);
  pushField(fields, "Prediction candidate", ctx.predictionCandidate);
  pushField(
    fields,
    "Prediction candidate (human)",
    modelDisplayName(ctx.predictionCandidate),
  );
  pushField(fields, "Prediction batch", ctx.predictionBatchId);
  pushField(fields, "Prediction as_of", ctx.predictionDate);
  pushField(fields, "Prediction generated_at", ctx.predictionGeneratedAt);
  pushField(
    fields,
    "Predicted return 20d (raw)",
    ctx.predictedReturn20d != null ? String(ctx.predictedReturn20d) : null,
  );
  pushField(
    fields,
    "Predicted return 20d",
    formatSignedPercent(ctx.predictedReturn20d),
  );
  if (ctx.rank != null) {
    pushField(
      fields,
      "Rank / eligible",
      ctx.eligibleCount != null ? `${ctx.rank} / ${ctx.eligibleCount}` : String(ctx.rank),
    );
  }
  pushField(fields, "Target weight", formatWeightPercent(ctx.targetWeight));
  pushField(fields, "Current weight", formatWeightPercent(ctx.currentWeight));
  pushField(fields, "Entry quantile", ctx.entryQuantile);
  pushField(fields, "Exit quantile", ctx.exitQuantile);
  pushField(fields, "Entry cutoff", ctx.entryCutoff);
  pushField(fields, "Exit cutoff", ctx.exitCutoff);
  pushField(fields, "Min trade weight delta", ctx.minTradeWeightDelta);
  pushField(fields, "Decision date", ctx.decisionDate);
  pushField(fields, "Decision timestamp", ctx.decisionAt);
  pushField(fields, "Order ID", ctx.orderId);
  pushField(fields, "Order status", ctx.orderStatus);
  pushField(fields, "Fill ID", ctx.fillId);
  pushField(fields, "Execution rule", ctx.executionRule ?? (ctx.executionDate ? "NEXT_OPEN" : null));
  pushField(fields, "Execution date", ctx.executionDate);
  pushField(fields, "Min execution date", ctx.minExecutionDate);
  pushField(fields, "Raw open", ctx.rawOpen);
  pushField(fields, "Fill price", ctx.fillPrice);
  pushField(fields, "Prediction hash", ctx.predictionHash);
  pushField(fields, "Candidate config hash", ctx.candidateConfigHash);
  pushField(fields, "Policy config hash", ctx.policyConfigHash);
  pushField(fields, "Fold ID", ctx.foldId);
  pushField(fields, "Kind", ctx.kind);
  pushField(fields, "Drawdown", formatSignedPercent(ctx.drawdown, 1));
  pushField(fields, "Previous exposure cap", formatWeightPercent(ctx.previousExposureCap, 0));
  pushField(fields, "New exposure cap", formatWeightPercent(ctx.newExposureCap, 0));
  return fields;
}

function buildTimeline(ctx: DecisionExplanationContext): TimelineItem[] {
  const items: TimelineItem[] = [];
  const pred = formatRuDate(ctx.predictionDate);
  const gen = formatRuDate(ctx.predictionGeneratedAt);
  const decision = formatRuDate(ctx.decisionDate ?? ctx.decisionAt);
  const exec = formatRuDate(ctx.executionDate);
  const pending = (ctx.orderStatus ?? "").toUpperCase() === "PENDING";

  if (pred && ctx.kind === "FORWARD_SHADOW") {
    items.push({ dateLabel: pred, label: "дата рыночных данных (as_of)" });
  } else if (pred) {
    items.push({ dateLabel: pred, label: "прогноз" });
  }
  if (gen) items.push({ dateLabel: gen, label: "прогноз сформирован" });
  if (decision) items.push({ dateLabel: decision, label: "решение" });
  if (exec) items.push({ dateLabel: exec, label: "исполнение" });
  else if (pending) items.push({ dateLabel: "—", label: "ожидает исполнения" });
  return items;
}

const FORBIDDEN = [/гарантированно/i, /точно вырастет/i, /модель решила купить/i];

export function assertSafeWording(text: string): void {
  for (const re of FORBIDDEN) {
    if (re.test(text)) {
      throw new Error(`Unsafe explanation wording matched ${re}: ${text}`);
    }
  }
}

export function buildDecisionExplanation(ctx: DecisionExplanationContext): DecisionExplanation {
  const { definition, usedFallback, normalized } = getReasonDefinition(ctx.reasonCode);
  const summary = definition.summary(ctx).trim();
  const detailed = definition.detailed(ctx).trim();
  assertSafeWording(summary);
  assertSafeWording(detailed);
  return {
    reasonCode: normalized,
    shortTitle: definition.shortTitle,
    summary,
    detailed,
    technical: buildTechnical(ctx, ctx.reasonCode?.trim() || normalized),
    timeline: buildTimeline(ctx),
    usedFallback,
  };
}
