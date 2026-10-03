import type {
  AblationTable,
  AblationVariantRow,
  EconomicsScenario,
  EconomicsSummary,
  EvidenceLimitation,
  ProspectiveSummary,
  ResearchEvidenceOverview,
} from "../../api/researchEvidence";
import {
  ABLATION_VARIANT_LABELS,
  ABLATION_VARIANT_ORDER,
  ECONOMICS_SCENARIO_BPS,
  ECONOMICS_SCENARIO_LABELS,
  ECONOMICS_SCENARIO_ORDER,
  REQUIRED_LIMITATIONS,
} from "./constants";

export function formatIc(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  }).format(value);
}

export function formatCi(low?: number | null, high?: number | null): string {
  if (low == null && high == null) return "—";
  return `${formatIc(low)} … ${formatIc(high)}`;
}

export function formatShare(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  const fraction = Math.abs(value) <= 1 ? value : value / 100;
  return `${new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  }).format(fraction * 100)} %`;
}

export function formatCount(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("ru-RU").format(value);
}

export function formatBoolRu(value?: boolean | null, yes = "да", no = "нет"): string {
  if (value == null) return "—";
  return value ? yes : no;
}

export function formatTurnover(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value)}×`;
}

export function totalReturnStatusLabel(status?: string | null): string {
  if (!status) return "—";
  const key = status.toLowerCase().replace(/\s+/g, "_");
  const map: Record<string, string> = {
    incomplete: "неполный",
    tr_incomplete: "неполный",
    excluded: "исключён",
    unavailable: "недоступен",
    partial: "частичный",
    complete: "полный",
    ok: "полный",
  };
  return map[key] ?? status;
}

export function mergeLimitations(
  raw?: Array<EvidenceLimitation | string> | null,
): EvidenceLimitation[] {
  const extra: EvidenceLimitation[] = [];
  for (const item of raw ?? []) {
    if (typeof item === "string") {
      extra.push({ code: item, title: item, detail: null });
      continue;
    }
    extra.push({
      code: item.code ?? item.title ?? "custom",
      title: item.title ?? item.code ?? "Ограничение",
      detail: item.detail ?? null,
    });
  }
  const seen = new Set(REQUIRED_LIMITATIONS.map((row) => (row.code ?? "").toUpperCase()));
  const merged = [...REQUIRED_LIMITATIONS];
  for (const row of extra) {
    const code = (row.code ?? "").toUpperCase();
    if (code && seen.has(code)) continue;
    if (code) seen.add(code);
    merged.push(row);
  }
  return merged;
}

export function ablationRows(table?: AblationTable | null): AblationVariantRow[] {
  const byVariant = new Map<string, AblationVariantRow>();
  for (const row of table?.rows ?? []) {
    byVariant.set(String(row.variant).toLowerCase(), row);
  }
  return ABLATION_VARIANT_ORDER.map((variant) => {
    const found = byVariant.get(variant);
    return {
      variant,
      label: found?.label ?? ABLATION_VARIANT_LABELS[variant],
      mean_oos_ic: found?.mean_oos_ic ?? null,
      spread: found?.spread ?? null,
      bootstrap_ci_low: found?.bootstrap_ci_low ?? null,
      bootstrap_ci_high: found?.bootstrap_ci_high ?? null,
      n: found?.n ?? null,
    };
  });
}

export function economicsScenarios(summary?: EconomicsSummary | null): EconomicsScenario[] {
  const byId = new Map<string, EconomicsScenario>();
  for (const row of summary?.scenarios ?? []) {
    const key = String(row.id ?? row.label ?? "")
      .toLowerCase()
      .replace(/\s+/g, "_");
    byId.set(key, row);
    if (row.commission_bps === 0) byId.set("gross", row);
    if (row.commission_bps === 10) byId.set("net_10bps", row);
    if (row.commission_bps === 30) byId.set("net_30bps", row);
    if (row.commission_bps === 50) byId.set("net_50bps", row);
  }
  return ECONOMICS_SCENARIO_ORDER.map((id) => {
    const found = byId.get(id);
    return {
      id,
      label: found?.label ?? ECONOMICS_SCENARIO_LABELS[id],
      commission_bps: found?.commission_bps ?? ECONOMICS_SCENARIO_BPS[id],
      total_return: found?.total_return ?? null,
      cagr: found?.cagr ?? null,
      max_drawdown: found?.max_drawdown ?? summary?.max_drawdown ?? null,
      turnover_ratio: found?.turnover_ratio ?? summary?.turnover_ratio ?? null,
      excess_vs_benchmark: found?.excess_vs_benchmark ?? null,
      benchmark_return: found?.benchmark_return ?? null,
    };
  });
}

export function isOverviewEmpty(overview?: ResearchEvidenceOverview | null): boolean {
  if (!overview) return true;
  const hasExperiment = Boolean(overview.experiment?.id || overview.experiment?.name);
  const hasDataset = Boolean(overview.dataset && Object.values(overview.dataset).some((v) => v != null));
  const models = overview.historical_models;
  const hasModels = Boolean(
    models?.regression?.rank_ic != null ||
      models?.ranker?.rank_ic != null ||
      models?.regression?.n != null ||
      models?.ranker?.n != null,
  );
  const hasAblation = Boolean(overview.ablation?.rows?.length);
  const hasEconomics = Boolean(overview.economics?.scenarios?.length);
  return !hasExperiment && !hasDataset && !hasModels && !hasAblation && !hasEconomics;
}

export function isOverviewPartial(overview?: ResearchEvidenceOverview | null): boolean {
  if (!overview || isOverviewEmpty(overview)) return false;
  const models = overview.historical_models;
  const missingModel =
    models?.regression?.rank_ic == null && models?.ranker?.rank_ic == null;
  const missingAblation = !overview.ablation?.rows?.length;
  const missingEconomics = !overview.economics?.scenarios?.length;
  const missingDataset = overview.dataset == null;
  return (
    missingDataset ||
    missingModel ||
    missingAblation ||
    missingEconomics ||
    overview.dataset?.partial === true ||
    overview.ablation?.partial === true ||
    overview.economics?.partial === true
  );
}

export function isProspectiveEmpty(prospective?: ProspectiveSummary | null): boolean {
  if (!prospective) return true;
  if (prospective.empty === true) return true;
  const pdm = prospective.personal_decision_memory;
  const fwd = prospective.forward_predictions;
  const captures = pdm?.captures_total ?? 0;
  const maturedPdm = (pdm?.horizons ?? []).reduce((sum, row) => sum + (row.matured_count ?? 0), 0);
  const fwdMatured = fwd?.freshness?.matured_count ?? 0;
  const hasForward = fwd?.latest_batch?.batch_id != null || fwdMatured > 0;
  if (captures > 0 || maturedPdm > 0 || hasForward) return false;
  return prospective.rank_ic == null;
}
