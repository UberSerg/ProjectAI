import type { HealthResponse, ServiceStatus } from "../api/system";

/** Ключи сервисов как в API `/system/health`. */
export const MANDATORY_SERVICES = [
  "backend",
  "core_database",
  "memory_database",
  "redis",
  "worker",
] as const;

export const DASHBOARD_SERVICES = [
  "core_database",
  "memory_database",
  "redis",
  "worker",
] as const;

export const SYSTEM_SERVICES = [
  "backend",
  "core_database",
  "memory_database",
  "redis",
  "worker",
  "scheduler",
] as const;

const ALIASES: Record<string, string[]> = {
  backend: ["backend"],
  core_database: ["core_database", "core_db"],
  memory_database: ["memory_database", "memory_db"],
  redis: ["redis"],
  worker: ["worker"],
  scheduler: ["scheduler"],
};

/** Статус сервиса из API; для Scheduler без поля — «не контролируется». */
export function resolveServiceStatus(
  services: Record<string, string | ServiceStatus> | undefined,
  key: string,
): string {
  const map = services ?? {};
  const candidates = ALIASES[key] ?? [key];
  for (const candidate of candidates) {
    const value = map[candidate];
    if (value != null && value !== "") return String(value);
  }
  if (key === "scheduler") return "not_monitored";
  return "unknown";
}

export type OverviewHealthKind = "ok" | "warning" | "error" | "unknown";

/** Presentation-логика общего статуса с учётом обязательных сервисов. */
export function overviewHealthKind(health: HealthResponse): OverviewHealthKind {
  const mandatory = MANDATORY_SERVICES.map((key) => resolveServiceStatus(health.services, key));
  if (mandatory.some((status) => status === "error" || status === "failed")) return "error";
  if (mandatory.some((status) => status === "unknown" || status === "")) return "warning";
  if (mandatory.every((status) => status === "ok" || status === "healthy")) {
    // Scheduler без healthcheck не ломает общий «нормально».
    return "ok";
  }
  if (mandatory.some((status) => status === "degraded" || status === "warning")) return "warning";
  return health.status === "ok" ? "ok" : "unknown";
}

export function overviewHealthTitle(health: HealthResponse): string {
  const kind = overviewHealthKind(health);
  if (kind === "ok") return "Система работает нормально";
  if (kind === "warning") return "Система работает с ограничениями";
  if (kind === "error") return "Обнаружены проблемы";
  return "Состояние системы неизвестно";
}

export function overviewHealthBadgeStatus(health: HealthResponse): string {
  const kind = overviewHealthKind(health);
  if (kind === "ok") return "ok";
  if (kind === "warning") return "warning";
  if (kind === "error") return "error";
  return "unknown";
}
