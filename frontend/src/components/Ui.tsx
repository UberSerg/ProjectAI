import type { ReactNode } from "react";

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function formatNumber(value?: number | null): string {
  return value == null ? "—" : new Intl.NumberFormat().format(value);
}

export function StatusBadge({ status }: { status?: string | null }) {
  const normalized = (status ?? "unknown").toLowerCase();
  return <span className={`badge badge-${normalized.replace(/[^a-z0-9-]/g, "-")}`}>{normalized}</span>;
}

export function PageState({
  kind,
  children,
}: {
  kind: "loading" | "error" | "empty";
  children: ReactNode;
}) {
  return (
    <div className={`page-state ${kind}`} role={kind === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}
