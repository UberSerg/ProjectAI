import type { ReactNode } from "react";
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

export function resolveStatusTone(status?: string | null): DsStatusTone {
  const raw = (status ?? "unknown").toLowerCase();
  return STATUS_ALIASES[raw] ?? (raw.includes("research") ? "research" : "unknown");
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
      <strong className="metric-value">{value}</strong>
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

export function SkeletonBlock({ tall }: { tall?: boolean }) {
  return <div className={`skeleton${tall ? " tall" : ""}`} aria-hidden />;
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
    return (
      <div className="page-state loading" role="status">
        <strong>{title ?? "Загрузка…"}</strong>
        <div className="skeleton-grid" style={{ marginTop: "1rem" }}>
          <SkeletonBlock />
          <SkeletonBlock />
          <SkeletonBlock />
          <SkeletonBlock tall />
        </div>
      </div>
    );
  }
  const defaults = {
    error: "Не удалось получить данные",
    empty: "Пока нечего показать",
  };
  return (
    <div className={`page-state ${kind}`} role={kind === "error" ? "alert" : "status"}>
      <strong>{title ?? defaults[kind]}</strong>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
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
