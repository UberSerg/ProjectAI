import { useEffect, useState } from "react";
import { errorMessage } from "../api/client";
import { getSystemHealth, getSystemInfo, type HealthResponse, type SystemInfo } from "../api/system";
import { PageHeader, PageState, ServiceDot, StatusBadge } from "../components/Ui";
import { overviewHealthBadgeStatus, resolveServiceStatus, SYSTEM_SERVICES } from "../utils/health";
import { labels } from "../utils/labels";

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

  if (error) return <PageState kind="error">{error}</PageState>;
  if (!health || !info) return <PageState kind="loading" title="Загрузка сведений о системе…" />;

  const rawPath = info.raw_storage_path ?? info.market_raw_path ?? "—";

  return (
    <section>
      <PageHeader title={labels.nav.system} description="Диагностика окружения и сервисов" />

      <div className="dashboard-grid">
        <article className="panel">
          <h2>Приложение</h2>
          <div className="key-value">
            <span>Версия ProjectAI</span>
            <strong>{info.version}</strong>
          </div>
          <div className="key-value">
            <span>Окружение</span>
            <strong>{info.environment}</strong>
          </div>
          <div className="key-value">
            <span>API</span>
            <strong>{info.api_version}</strong>
          </div>
          <div className="key-value">
            <span>Автообновление рынка</span>
            <StatusBadge status={info.market_update_enabled ? "enabled" : "disabled"} />
          </div>
          <div className="key-value">
            <span>RAW-хранилище</span>
            <strong className="mono">{rawPath}</strong>
          </div>
        </article>

        <article className="panel">
          <div className="page-header" style={{ marginBottom: "0.5rem" }}>
            <h2>Сервисы</h2>
            <StatusBadge status={overviewHealthBadgeStatus(health)} />
          </div>
          <div className="service-list">
            {SYSTEM_SERVICES.map((key) => (
              <div className="service-item" key={key}>
                <span>{labels.service(key)}</span>
                <ServiceDot status={resolveServiceStatus(health.services, key)} />
              </div>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}
