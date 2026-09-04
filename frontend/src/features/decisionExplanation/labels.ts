/** Human labels for policy/risk/model codes (technical codes stay in Level 3). */

const POLICY_LABELS: Record<string, string> = {
  RANK_HYSTERESIS_LONG_ONLY_V1: "Рейтинговая стратегия с удержанием",
  RANK_LONG_ONLY_V0: "Рейтинговая стратегия Long-Only V0",
};

const RISK_LABELS: Record<string, string> = {
  DRAWDOWN_GUARD_V1: "Защита от глубокой просадки",
  RISK_GUARDRAILS_V0: "Базовые ограничения риска",
};

const MODEL_LABELS: Record<string, string> = {
  prediction_ml_candidate: "Модель прогнозирования V0",
  "prediction_ml_candidate/v0": "Модель прогнозирования V0",
};

export function policyDisplayName(code?: string | null): string | null {
  if (!code) return null;
  return POLICY_LABELS[code] ?? null;
}

export function riskDisplayName(code?: string | null): string | null {
  if (!code) return null;
  return RISK_LABELS[code] ?? null;
}

export function modelDisplayName(code?: string | null): string | null {
  if (!code) return null;
  return MODEL_LABELS[code] ?? MODEL_LABELS[code.toLowerCase()] ?? null;
}

export function humanPolicyOrCode(code?: string | null): string {
  return policyDisplayName(code) ?? code ?? "портфельная политика";
}
