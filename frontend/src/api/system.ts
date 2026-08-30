import { apiRequest } from "./client";

export type ServiceStatus = "ok" | "error" | "unknown" | "degraded";

export interface HealthResponse {
  status: ServiceStatus;
  services: Record<string, ServiceStatus>;
}

export interface SystemInfo {
  name: string;
  version: string;
  environment: string;
  api_version: string;
  market_update_enabled?: boolean;
  raw_storage_path?: string;
  market_raw_path?: string;
}

export function getSystemHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiRequest("/system/health", { signal });
}

export function getSystemInfo(signal?: AbortSignal): Promise<SystemInfo> {
  return apiRequest("/system/info", { signal });
}

export interface TechEvent {
  id: string;
  timestamp: string | null;
  level: "INFO" | "WARNING" | "ERROR" | string;
  component: string;
  event_type: string;
  message: string;
  details?: Record<string, unknown> | null;
  workflow_id?: string | null;
  batch_id?: string | null;
  instrument_id?: string | null;
  trace_id?: string | null;
}

export async function getTechEvents(
  filters: { level?: string; component?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<TechEvent[]> {
  const params = new URLSearchParams();
  if (filters.level) params.set("level", filters.level);
  if (filters.component) params.set("component", filters.component);
  params.set("limit", String(filters.limit ?? 200));
  const response = await apiRequest<{ items: TechEvent[] }>(`/system/events?${params}`, { signal });
  return response.items;
}

export async function getDiagnosticsText(signal?: AbortSignal): Promise<string> {
  const base = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");
  const response = await fetch(`${base}/api/v1/system/diagnostics/text`, { signal });
  if (!response.ok) throw new Error(`Diagnostics failed (${response.status})`);
  return response.text();
}

let clientErrorGate = false;

export async function reportClientError(payload: {
  level?: "INFO" | "WARNING" | "ERROR";
  component?: string;
  event_type?: string;
  message: string;
  route?: string;
  stack?: string;
  details?: Record<string, unknown>;
}): Promise<void> {
  if (clientErrorGate) return;
  clientErrorGate = true;
  try {
    await apiRequest("/system/events/client", {
      method: "POST",
      body: {
        level: payload.level ?? "ERROR",
        component: payload.component ?? "frontend",
        event_type: payload.event_type ?? "frontend_runtime_error",
        message: payload.message.slice(0, 2000),
        route: payload.route,
        stack: payload.stack?.slice(0, 4000),
        details: payload.details,
      },
    });
  } catch {
    // never recurse
  } finally {
    window.setTimeout(() => {
      clientErrorGate = false;
    }, 2000);
  }
}
