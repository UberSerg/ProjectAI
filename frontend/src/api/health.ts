export type ServiceStatus = "ok" | "error" | "unknown";

export type HealthResponse = {
  status: ServiceStatus;
  services: {
    backend?: ServiceStatus;
    core_database?: ServiceStatus;
    memory_database?: ServiceStatus;
    redis?: ServiceStatus;
    worker?: ServiceStatus;
  };
};

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/api/v1/system/health`, { signal });
  if (!response.ok) {
    throw new Error(`Health request failed: ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}
