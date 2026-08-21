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
