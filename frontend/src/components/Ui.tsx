import type { ReactNode } from "react";
import { labels } from "../utils/labels";

export function StatusBadge({ status }: { status?: string | null }) {
  const raw = (status ?? "unknown").toLowerCase();
  const tone =
    ["ok", "success", "succeeded", "completed", "active", "enabled", "healthy"].includes(raw)
      ? "success"
      : ["warning", "degraded"].includes(raw)
        ? "warning"
        : ["error", "failed"].includes(raw)
          ? "error"
          : ["running", "pending"].includes(raw)
            ? "running"
            : raw === "info"
              ? "info"
              : "neutral";
  return <span className={`badge badge-${tone}`}>{labels.status(raw)}</span>;
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {description ? <p className="subtitle">{description}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </div>
  );
}

export function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <article className="metric-card">
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
      {hint ? <small className="metric-hint">{hint}</small> : null}
    </article>
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
  const defaults = {
    loading: "Загрузка…",
    error: "Не удалось получить данные",
    empty: "Нет данных",
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
