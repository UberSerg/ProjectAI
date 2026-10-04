import type {
  AblationTable,
  CampaignDataQuality,
  CampaignIdentity,
  CampaignOosRow,
  CampaignOosTable,
  CampaignStability,
  DataQualityField,
  EconomicsRobustness,
  EvidenceCampaignList,
  EvidenceCampaignSummary,
  EvidenceDossierV1,
  EvidenceStability,
  RobustnessMatrixCell,
  StabilitySliceRow,
} from "../../api/researchEvidence";
import {
  NO_DATA_LABEL,
  OOS_VARIANT_LABELS,
  OOS_VARIANT_ORDER,
  PRIMARY_COST_BPS,
  PRIMARY_REBALANCE_SESSIONS,
  PRIMARY_SELECTION_TOP_PCT,
  ROBUSTNESS_COST_BPS,
  ROBUSTNESS_REBALANCE,
  ROBUSTNESS_SELECTION,
} from "./constants";
import { formatCount, formatIc, formatShare } from "./format";

export function fingerprintShort(fingerprint?: string | null, explicit?: string | null): string {
  if (explicit) return explicit;
  if (!fingerprint) return NO_DATA_LABEL;
  return fingerprint.slice(0, 12);
}

export function campaignWindow(from?: string | null, to?: string | null): string {
  if (!from && !to) return NO_DATA_LABEL;
  return `${from ?? NO_DATA_LABEL} — ${to ?? NO_DATA_LABEL}`;
}

export function isDossierEmpty(dossier?: EvidenceDossierV1 | null): boolean {
  if (!dossier) return true;
  if (dossier.empty === true) return true;
  const hasIdentity = Boolean(dossier.identity?.fingerprint || dossier.identity?.campaign_version);
  const hasOos = Boolean(dossier.historical_oos?.rows?.length || dossier.ablation?.rows?.length);
  const hasQuality = Boolean(dossier.data_quality);
  const hasEconomics = Boolean(dossier.economics_primary);
  const hasCompleteness = Boolean(dossier.evidence_completeness);
  return !hasIdentity && !hasOos && !hasQuality && !hasEconomics && !hasCompleteness;
}

function isMissingField(field: unknown): boolean {
  if (field == null) return true;
  if (typeof field === "object") {
    const row = field as DataQualityField;
    if (row.missing === true) return true;
    if ("counts" in row || "value" in row || "status" in row || "missing" in row) {
      const hasValue =
        row.value != null || row.status != null || (row.counts != null && Object.keys(row.counts).length > 0);
      return !hasValue;
    }
    return Object.keys(row as object).length === 0;
  }
  if (typeof field === "string" && field.trim() === "") return true;
  return false;
}

export function formatQualityValue(
  field: DataQualityField | number | string | Record<string, number | null> | null | undefined,
  kind: "share" | "count" | "status" | "text" = "text",
): string {
  if (isMissingField(field)) return NO_DATA_LABEL;
  if (typeof field === "number") {
    if (kind === "share") return formatShare(field);
    if (kind === "count") return formatCount(field);
    return String(field);
  }
  if (typeof field === "string") return field;
  const row = field as DataQualityField;
  if (row.value != null) {
    if (typeof row.value === "number") {
      if (kind === "share") return formatShare(row.value);
      if (kind === "count") return formatCount(row.value);
      return String(row.value);
    }
    return String(row.value);
  }
  if (row.status) return row.status;
  return NO_DATA_LABEL;
}

export function formatIssuerBasis(
  field: CampaignDataQuality["issuer_identity_basis"],
): string {
  if (isMissingField(field)) return NO_DATA_LABEL;
  const counts =
    field && typeof field === "object" && "counts" in field
      ? (field as DataQualityField).counts
      : (field as Record<string, number | null> | null);
  if (!counts) return NO_DATA_LABEL;
  const keys = ["DATED_WINDOW", "CURRENT_ONLY", "UNMAPPED", "AMBIGUOUS"];
  const parts = keys
    .filter((key) => counts[key] != null)
    .map((key) => `${key}: ${formatCount(counts[key])}`);
  return parts.length ? parts.join(" · ") : NO_DATA_LABEL;
}

export function oosRows(
  table?: CampaignOosTable | null,
  ablation?: AblationTable | null,
): CampaignOosRow[] {
  const source = table?.rows?.length ? table.rows : (ablation?.rows ?? []);
  const byVariant = new Map<string, CampaignOosRow | (typeof source)[number]>();
  for (const row of source) {
    byVariant.set(normalizeVariant(String(row.variant)), row);
  }
  return OOS_VARIANT_ORDER.map((variant) => {
    const found = byVariant.get(variant) as CampaignOosRow | undefined;
    const ablationFound = found as
      | (CampaignOosRow & { mean_oos_ic?: number | null; bootstrap_ci_low?: number | null; bootstrap_ci_high?: number | null })
      | undefined;
    return {
      variant,
      label: found?.label ?? OOS_VARIANT_LABELS[variant],
      rank_ic: found?.rank_ic ?? found?.mean_rank_ic ?? ablationFound?.mean_oos_ic ?? null,
      spread: found?.spread ?? null,
      n: found?.n ?? null,
      ci_low: found?.ci_low ?? found?.delta_ci_low ?? ablationFound?.bootstrap_ci_low ?? null,
      ci_high: found?.ci_high ?? found?.delta_ci_high ?? ablationFound?.bootstrap_ci_high ?? null,
    };
  });
}

function normalizeVariant(raw: string): string {
  const key = raw.toLowerCase().replace(/\s+/g, "_");
  if (key === "base" || key === "v3" || key === "base_v3") return "base";
  if (key.includes("fund")) return "fund";
  if (key.includes("event")) return "events";
  if (key.includes("full") || key === "v4" || key === "v4_full") return "full_v4";
  return key;
}

export function stabilityRows(
  block?: CampaignStability | EvidenceStability | null,
  key: "years" | "folds" | "identity_basis" | "activity" | "fold_year" = "years",
): StabilitySliceRow[] {
  if (!block) return [];
  if (key === "fold_year" && "fold_year" in block) {
    return (block.fold_year ?? []).map((row) => ({
      key: String(row.fold ?? row.year ?? ""),
      label: String(row.fold ?? row.year ?? ""),
      rank_ic: row.rank_ic ?? null,
      spread: row.spread ?? null,
      n: row.n ?? null,
    }));
  }
  const campaign = block as CampaignStability;
  const rows = campaign[key as keyof CampaignStability];
  if (!Array.isArray(rows)) return [];
  return rows as StabilitySliceRow[];
}

export function sliceLabel(row: StabilitySliceRow): string {
  return row.label ?? row.key ?? (row.fold != null ? String(row.fold) : null) ?? (row.year != null ? String(row.year) : null) ?? NO_DATA_LABEL;
}

export function isPrimaryRobustnessCell(cell: {
  rebalance_sessions?: number | null;
  selection_top_pct?: number | null;
  cost_bps?: number | null;
}): boolean {
  return (
    Number(cell.rebalance_sessions) === PRIMARY_REBALANCE_SESSIONS &&
    Number(cell.selection_top_pct) === PRIMARY_SELECTION_TOP_PCT &&
    Number(cell.cost_bps) === PRIMARY_COST_BPS
  );
}

export function robustnessAxes(matrix?: EconomicsRobustness | null) {
  return {
    rebalance: matrix?.rebalance_sessions?.length ? matrix.rebalance_sessions : [...ROBUSTNESS_REBALANCE],
    selection: matrix?.selection_top_pct?.length ? matrix.selection_top_pct : [...ROBUSTNESS_SELECTION],
    costs: matrix?.cost_bps?.length ? matrix.cost_bps : [...ROBUSTNESS_COST_BPS],
  };
}

export function robustnessCellAt(
  matrix: EconomicsRobustness | null | undefined,
  rebalance: number,
  selection: number,
  cost: number,
): RobustnessMatrixCell | null {
  for (const cell of matrix?.cells ?? []) {
    if (
      Number(cell.rebalance_sessions) === rebalance &&
      Number(cell.selection_top_pct) === selection &&
      Number(cell.cost_bps) === cost
    ) {
      return cell;
    }
  }
  return null;
}

export function sortCampaignsNewestFirst(list?: EvidenceCampaignList | EvidenceCampaignSummary[] | null): EvidenceCampaignSummary[] {
  const items = Array.isArray(list)
    ? list
    : [...(list?.items ?? []), ...(list?.campaigns ?? [])];
  const seen = new Set<string>();
  const unique: EvidenceCampaignSummary[] = [];
  for (const item of items) {
    if (!item?.fingerprint || seen.has(item.fingerprint)) continue;
    seen.add(item.fingerprint);
    unique.push(item);
  }
  return unique.sort((a, b) => {
    const ta = Date.parse(a.finalized_at ?? a.created_at ?? "") || 0;
    const tb = Date.parse(b.finalized_at ?? b.created_at ?? "") || 0;
    return tb - ta;
  });
}

export function identityFromDossier(dossier?: EvidenceDossierV1 | null): CampaignIdentity | null {
  if (!dossier) return null;
  const identity: CampaignIdentity = { ...(dossier.identity ?? {}) };
  if (!identity.data_snapshot_hash && dossier.data_snapshot?.hash) {
    identity.data_snapshot_hash = dossier.data_snapshot.hash;
  }
  if (!identity.data_snapshot_at && (dossier.data_snapshot?.observed_at || dossier.data_snapshot?.created_at)) {
    identity.data_snapshot_at = dossier.data_snapshot?.observed_at ?? dossier.data_snapshot?.created_at ?? null;
  }
  return identity;
}

export function formatMetricOrNoData(value?: number | null, formatter: (v: number) => string = String): string {
  if (value == null || Number.isNaN(value)) return NO_DATA_LABEL;
  return formatter(value);
}

export function formatIcOrNoData(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return NO_DATA_LABEL;
  return formatIc(value);
}
