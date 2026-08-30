import { apiRequest, queryString } from "./client";

export interface WorkflowStep {
  id?: string;
  name: string;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
}

export interface Workflow {
  id: string;
  name: string;
  workflow_type: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds?: number | null;
  error: string | null;
  steps: WorkflowStep[];
}

export async function getWorkflows(signal?: AbortSignal): Promise<Workflow[]> {
  const response = await apiRequest<Workflow[] | { items: Workflow[] }>(
    `/workflows${queryString({ limit: 100 })}`,
    { signal },
  );
  return Array.isArray(response) ? response : response.items;
}

export function getWorkflow(id: string, signal?: AbortSignal): Promise<Workflow> {
  return apiRequest(`/workflows/${encodeURIComponent(id)}`, { signal });
}
