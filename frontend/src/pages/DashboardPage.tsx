import { useEffect, useState } from "react";
import { fetchHealth, type HealthResponse, type ServiceStatus } from "../api/health";

function statusLabel(status: ServiceStatus): string {
  if (status === "ok") return "OK";
  if (status === "error") return "ERROR";
  return "UNKNOWN";
}

export function DashboardPage() {
  const [backendStatus, setBackendStatus] = useState<ServiceStatus>("unknown");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function load() {
      try {
        const data = await fetchHealth(controller.signal);
        if (cancelled) return;
        setHealth(data);
        setBackendStatus("ok");
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setBackendStatus("error");
        setHealth(null);
        setError(err instanceof Error ? err.message : "Backend unavailable");
      }
    }

    void load();
    const timer = window.setInterval(() => void load(), 10000);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  const displayRows = [
    { label: "Backend", status: backendStatus },
    { label: "Core DB", status: health?.services.core_database ?? "error" },
    { label: "Memory DB", status: health?.services.memory_database ?? "error" },
    { label: "Redis", status: health?.services.redis ?? "error" },
    { label: "Worker", status: health?.services.worker ?? "error" },
  ];

  return (
    <section>
      <h1>ProjectAI Dashboard</h1>
      <p className="subtitle">Platform foundation status</p>
      {error ? <p className="banner error">Backend unreachable. Showing ERROR states.</p> : null}
      <div className="status-grid">
        {displayRows.map((row) => (
          <div key={row.label} className="status-row">
            <span>{row.label}</span>
            <span className={`badge ${row.status}`}>{statusLabel(row.status)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
