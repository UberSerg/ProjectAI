import { getSystemHealth } from "./system";

export type { HealthResponse, ServiceStatus } from "./system";

/** Compatibility alias for callers from the foundation UI. */
export const fetchHealth = getSystemHealth;
