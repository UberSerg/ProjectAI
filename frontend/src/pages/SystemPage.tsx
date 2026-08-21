import { useEffect, useState } from "react";
import { errorMessage } from "../api/client";
import { getSystemHealth, getSystemInfo, type HealthResponse, type SystemInfo } from "../api/system";
import { PageState, StatusBadge } from "../components/Ui";

export function SystemPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([getSystemHealth(controller.signal), getSystemInfo(controller.signal)])
      .then(([healthResponse, infoResponse]) => {
        setHealth(healthResponse);
        setInfo(infoResponse);
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(errorMessage(reason));
      });
    return () => controller.abort();
  }, []);

  if (error) return <PageState kind="error">Unable to load system information: {error}</PageState>;
  if (!health || !info) return <PageState kind="loading">Loading system information…</PageState>;

  return (
    <section>
      <h1>System</h1>
      <p className="subtitle">Runtime information and service health</p>
      <div className="detail-grid">
        <article className="panel">
          <h2>Runtime</h2>
          <div className="key-value"><span>Application</span><strong>{info.name}</strong></div>
          <div className="key-value"><span>Version</span><strong>{info.version}</strong></div>
          <div className="key-value"><span>API version</span><strong>{info.api_version}</strong></div>
          <div className="key-value"><span>Environment</span><strong>{info.environment}</strong></div>
          <div className="key-value"><span>Market updates</span><StatusBadge status={info.market_update_enabled == null ? "unknown" : info.market_update_enabled ? "enabled" : "disabled"} /></div>
          <div className="key-value"><span>Raw market path</span><strong className="mono">{info.raw_storage_path ?? info.market_raw_path ?? "Not reported"}</strong></div>
        </article>
        <article className="panel">
          <div className="page-header"><h2>Services</h2><StatusBadge status={health.status} /></div>
          {Object.entries(health.services).length ? Object.entries(health.services).map(([service, status]) => <div className="key-value" key={service}><span>{service.replaceAll("_", " ")}</span><StatusBadge status={status} /></div>) : <p className="muted">No service details reported.</p>}
        </article>
      </div>
    </section>
  );
}
