import { useState, type ReactNode, type SyntheticEvent } from "react";
import { MetricHelp, PageHelp } from "../help";
import { labels } from "../utils/labels";

export type DsStatusTone =
  | "success"
  | "warning"
  | "risk"
  | "unknown"
  | "research"
  | "blocked"
  | "info";

export type DecisionActionTone = "buy" | "sell" | "hold" | "review" | "unknown";
export type FreshnessTone = "fresh" | "stale" | "partial" | "unavailable";
export type ProvenanceTone = "live" | "counterfactual" | "unknown";
export type NoticeTone = "info" | "success" | "warning" | "danger";

const STATUS_ALIASES: Record<string, DsStatusTone> = {
  ok: "success",
  success: "success",
  succeeded: "success",
  completed: "success",
  active: "success",
  enabled: "success",
  healthy: "success",
  pass: "success",
  good: "success",
  approved: "success",
  ready: "success",
  supported: "success",
  warning: "warning",
  degraded: "warning",
  partial: "warning",
  deferred: "warning",
  stale: "warning",
  approved_with_warnings: "warning",
  error: "risk",
  failed: "risk",
  not_ready: "risk",
  low: "risk",
  risk: "risk",
  blocked: "blocked",
  running: "info",
  pending: "info",
  info: "info",
  unknown: "unknown",
  insufficient_data: "unknown",
  research_only: "research",
  research: "research",
};

const ACTION_ALIASES: Record<string, DecisionActionTone> = {
  buy: "buy",
  enter: "buy",
  consider_increase: "buy",
  increase: "buy",
  sell: "sell",
  exit: "sell",
  reduce: "sell",
  consider_reduce: "sell",
  hold: "hold",
  review_hold: "hold",
  data_hold: "hold",
  abstain: "hold",
  review: "review",
  rotate: "review",
};

const FRESHNESS_ALIASES: Record<string, FreshnessTone> = {
  fresh: "fresh",
  stale: "stale",
  mixed: "partial",
  partial: "partial",
  unavailable: "unavailable",
  unknown: "unavailable",
  session_not_started: "unavailable",
};

const ACTION_LABELS: Record<DecisionActionTone, string> = {
  buy: "BUY",
  sell: "SELL",
  hold: "HOLD",
  review: "REVIEW",
  unknown: "UNKNOWN",
};

const FRESHNESS_LABELS: Record<FreshnessTone, string> = {
  fresh: "FRESH",
  stale: "STALE",
  partial: "PARTIAL",
  unavailable: "UNAVAILABLE",
};

export function resolveStatusTone(status?: string | null): DsStatusTone {
  const raw = (status ?? "unknown").toLowerCase();
  return STATUS_ALIASES[raw] ?? (raw.includes("research") ? "research" : "unknown");
}

export function resolveDecisionAction(action?: string | null): DecisionActionTone {
  const raw = (action ?? "").toLowerCase().replace(/[\s-]+/g, "_").trim();
  if (!raw) return "unknown";
  if (ACTION_ALIASES[raw]) return ACTION_ALIASES[raw];
  // ENTER/EXIT are directional — never collapse them to HOLD.
  if (raw.includes("enter") || raw.includes("buy") || raw.includes("increase")) return "buy";
  if (raw.includes("exit") || raw.includes("sell") || raw.includes("reduce")) return "sell";
  if (raw.includes("review") || raw.includes("rotate")) return "review";
  if (raw.includes("hold") || raw.includes("abstain")) return "hold";
  return "unknown";
}

export function resolveFreshnessTone(value?: string | null): FreshnessTone {
  const raw = (value ?? "unavailable").toLowerCase().replace(/[\s-]+/g, "_");
  if (FRESHNESS_ALIASES[raw]) return FRESHNESS_ALIASES[raw];
  if (raw.includes("fresh")) return "fresh";
  if (raw.includes("stale")) return "stale";
  if (raw.includes("partial") || raw.includes("mixed")) return "partial";
  return "unavailable";
}

export function resolveProvenanceTone(value?: string | null): ProvenanceTone {
  const raw = (value ?? "").trim().toUpperCase();
  if (!raw || raw === "UNKNOWN" || raw === "UNAVAILABLE" || raw === "NONE" || raw === "N/A") {
    return "unknown";
  }
  if (raw.includes("COUNTERFACTUAL") || raw.includes("REPLAY")) return "counterfactual";
  if (raw === "LIVE" || raw === "RECORDED_LIVE" || raw.includes("RECORDED_LIVE")) return "live";
  // Explicit LIVE token only — do not treat arbitrary/unknown strings as LIVE.
  if (/(^|_)LIVE($|_)/.test(raw) && !raw.includes("COUNTER")) return "live";
  return "unknown";
}

export function StatusBadge({ status, label }: { status?: string | null; label?: string }) {
  const raw = (status ?? "unknown").toLowerCase();
  const tone = resolveStatusTone(raw);
  const badgeClass =
    tone === "research"
      ? "ds-status-research"
      : tone === "blocked" || tone === "risk"
        ? tone === "blocked"
          ? "ds-status-blocked"
          : "ds-status-risk"
        : tone === "success"
          ? "badge-success"
          : tone === "warning"
            ? "badge-warning"
            : tone === "info"
              ? "badge-running"
              : "badge-neutral";
  const text =
    label ??
    (tone === "research"
      ? "Только исследование"
      : tone === "blocked"
        ? "Заблокировано"
        : tone === "risk"
          ? "Риск"
          : tone === "unknown"
            ? "Неизвестно"
            : labels.status(raw));
  return <span className={`badge ${badgeClass}`}>{text}</span>;
}

export function DecisionActionChip({
  action,
  label,
}: {
  action?: string | null;
  label?: string;
}) {
  const tone = resolveDecisionAction(action);
  const fallback =
    tone === "unknown" && action && String(action).trim()
      ? String(action).trim().toUpperCase()
      : ACTION_LABELS[tone];
  return (
    <span className={`ds-action-chip ds-action-${tone}`} data-action={tone}>
      {label ?? fallback}
    </span>
  );
}

export function FreshnessBadge({
  value,
  label,
}: {
  value?: string | null;
  label?: string;
}) {
  const tone = resolveFreshnessTone(value);
  return (
    <span className={`ds-freshness-badge ds-freshness-${tone}`} data-freshness={tone}>
      {label ?? FRESHNESS_LABELS[tone]}
    </span>
  );
}

export function ProvenanceBadge({
  value,
  label,
}: {
  value?: string | null;
  label?: string;
}) {
  const tone = resolveProvenanceTone(value);
  const fallback =
    tone === "counterfactual" ? "COUNTERFACTUAL" : tone === "live" ? "LIVE" : "UNKNOWN";
  return (
    <span className={`ds-provenance-badge ds-provenance-${tone}`} data-provenance={tone}>
      {label ?? fallback}
    </span>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  helpPageId,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  helpPageId?: string;
}) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {description ? <p className="subtitle">{description}</p> : null}
      </div>
      <div className="page-actions">
        {helpPageId ? <PageHelp pageId={helpPageId} /> : null}
        {actions}
      </div>
    </div>
  );
}

export function MetricCard({
  label,
  value,
  hint,
  helpId,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  helpId?: string;
}) {
  return (
    <article className="metric-card">
      <span className="metric-label">
        {label}
        {helpId ? <MetricHelp metricId={helpId} /> : null}
      </span>
      <strong className="metric-value ds-number">{value}</strong>
      {hint ? <small className="metric-hint">{hint}</small> : null}
    </article>
  );
}

export function HeroCard({
  eyebrow,
  headline,
  children,
  actions,
}: {
  eyebrow?: string;
  headline: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="ds-card ds-card-hero">
      {eyebrow ? <div className="ds-card-title">{eyebrow}</div> : null}
      <div className="ds-card-headline">{headline}</div>
      {children ? <div className="ds-card-body">{children}</div> : null}
      {actions ? <div className="page-actions" style={{ marginTop: "1rem" }}>{actions}</div> : null}
    </section>
  );
}

export function ExplanationCard({
  title,
  level = 1,
  children,
}: {
  title: string;
  level?: 1 | 2 | 3;
  children: ReactNode;
}) {
  return (
    <article className="ds-card ds-card-explanation">
      <div className="level-chip">Уровень {level}</div>
      <h3>{title}</h3>
      <div className="ds-card-body">{children}</div>
    </article>
  );
}

export function WarningCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <article className="ds-card ds-card-warning">
      <h3>{title}</h3>
      <div className="ds-card-body">{children}</div>
    </article>
  );
}

export function RiskCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <article className="ds-card ds-card-risk">
      <h3>{title}</h3>
      <div className="ds-card-body">{children}</div>
    </article>
  );
}

export function DataQualityCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <article className="ds-card ds-card-quality">
      <h3>{title}</h3>
      <div className="ds-card-body">{children}</div>
    </article>
  );
}

export function DataQualityNote({
  title,
  children,
  tone = "info",
}: {
  title?: string;
  children: ReactNode;
  tone?: NoticeTone;
}) {
  return (
    <aside className="ds-data-quality-note" data-tone={tone} role="note">
      {title ? <strong>{title}</strong> : null}
      <div>{children}</div>
    </aside>
  );
}

export function InlineNotice({
  tone = "info",
  title,
  children,
}: {
  tone?: NoticeTone;
  title?: string;
  children: ReactNode;
}) {
  return (
    <div className={`ds-inline-notice ds-inline-notice-${tone}`} role="status" data-tone={tone}>
      <div>
        {title ? <strong>{title}</strong> : null}
        {typeof children === "string" ? <p>{children}</p> : children}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  reason,
  action,
}: {
  title: string;
  reason: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-rich" role="status">
      <strong>{title}</strong>
      <p>{reason}</p>
      {action}
    </div>
  );
}

export function ErrorState({
  title = "Не удалось получить данные",
  children,
  action,
}: {
  title?: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="ds-error-state" role="alert">
      <strong>{title}</strong>
      {children ? (typeof children === "string" ? <p>{children}</p> : children) : null}
      {action}
    </div>
  );
}

export function SkeletonBlock({ tall }: { tall?: boolean }) {
  return <div className={`skeleton${tall ? " tall" : ""}`} aria-hidden />;
}

/** Stable-height loading placeholder — prefer over spinner to avoid layout jump. */
export function LoadingSkeleton({
  rows = 3,
  tallLast = true,
  label = "Загрузка…",
}: {
  rows?: number;
  tallLast?: boolean;
  label?: string;
}) {
  const count = Math.max(1, rows);
  return (
    <div className="ds-loading-skeleton page-state loading" role="status" aria-busy="true">
      <strong>{label}</strong>
      <div className="skeleton-grid">
        {Array.from({ length: count }, (_, i) => (
          <SkeletonBlock key={i} tall={tallLast && i === count - 1} />
        ))}
      </div>
    </div>
  );
}

export function Accordion({
  title,
  children,
  defaultOpen = false,
  summaryExtra,
}: {
  title: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  summaryExtra?: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const onToggle = (event: SyntheticEvent<HTMLDetailsElement>) => {
    setOpen(event.currentTarget.open);
  };
  return (
    <details className="ds-accordion" open={open} onToggle={onToggle}>
      <summary>
        <span>{title}</span>
        {summaryExtra}
      </summary>
      <div className="ds-accordion-body">{children}</div>
    </details>
  );
}

export function PageState({
  kind,
  title,
  children,
  action,
}: {
  kind: "loading" | "error" | "empty";
  title?: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  if (kind === "loading") {
    return <LoadingSkeleton label={title ?? "Загрузка…"} rows={4} />;
  }
  if (kind === "error") {
    return (
      <ErrorState title={title} action={action}>
        {children}
      </ErrorState>
    );
  }
  return (
    <EmptyState title={title ?? "Пока нечего показать"} reason={children ?? "Данных пока нет."} action={action} />
  );
}

export function ServiceDot({ status }: { status?: string | null }) {
  const raw = (status ?? "unknown").toLowerCase();
  const tone =
    raw === "ok" || raw === "healthy"
      ? "success"
      : raw === "error" || raw === "failed"
        ? "error"
        : raw === "warning" || raw === "degraded"
          ? "warning"
          : "neutral";
  return (
    <span className="service-row">
      <span className={`dot dot-${tone}`} aria-hidden />
      <span>{labels.status(raw)}</span>
    </span>
  );
}

export function AllocationBars({
  equity,
  fixedIncome,
  cash,
}: {
  equity: number;
  fixedIncome: number;
  cash: number;
}) {
  const rows = [
    { label: "Акции", value: equity, className: "" },
    { label: "Облигации", value: fixedIncome, className: "fi" },
    { label: "Деньги", value: cash, className: "cash" },
  ];
  return (
    <div className="allocation-bars">
      {rows.map((row) => (
        <div className="allocation-row" key={row.label}>
          <span>{row.label}</span>
          <div className="allocation-track" aria-hidden>
            <div
              className={`allocation-fill ${row.className}`.trim()}
              style={{ width: `${Math.max(0, Math.min(100, row.value * 100))}%` }}
            />
          </div>
          <strong>{(row.value * 100).toFixed(0)}%</strong>
        </div>
      ))}
    </div>
  );
}
