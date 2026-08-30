import { useCallback, useEffect, useMemo, useState } from "react";
import { errorMessage } from "../api/client";
import {
  getDiagnosticsText,
  getSystemHealth,
  getSystemInfo,
  getTechEvents,
  type HealthResponse,
  type SystemInfo,
  type TechEvent,
} from "../api/system";
import { PageHeader, PageState, ServiceDot, StatusBadge } from "../components/Ui";
import { formatDateTime } from "../utils/format";
import { overviewHealthBadgeStatus, resolveServiceStatus, SYSTEM_SERVICES } from "../utils/health";
import { labels } from "../utils/labels";

type Tab = "overview" | "diagnostics";
type LevelFilter = "ALL" | "ERROR" | "WARNING" | "INFO";

export function SystemPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [events, setEvents] = useState<TechEvent[]>([]);
  const [level, setLevel] = useState<LevelFilter>("ALL");
  const [component, setComponent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportText, setReportText] = useState("");
  const [reportBusy, setReportBusy] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "manual">("idle");

  const loadOverview = useCallback(async (signal?: AbortSignal) => {
    const [nextHealth, nextInfo] = await Promise.all([getSystemHealth(signal), getSystemInfo(signal)]);
    setHealth(nextHealth);
    setInfo(nextInfo);
  }, []);

  const loadEvents = useCallback(
    async (signal?: AbortSignal) => {
      const items = await getTechEvents(
        {
          level: level === "ALL" ? undefined : level,
          component: component || undefined,
          limit: 200,
        },
        signal,
      );
      setEvents(items);
    },
    [level, component],
  );

  useEffect(() => {
    const controller = new AbortController();
    loadOverview(controller.signal).catch((reason: unknown) => {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(errorMessage(reason));
    });
    return () => controller.abort();
  }, [loadOverview]);

  useEffect(() => {
    if (tab !== "diagnostics") return;
    const controller = new AbortController();
    loadEvents(controller.signal).catch((reason: unknown) => {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(errorMessage(reason));
    });
    return () => controller.abort();
  }, [tab, loadEvents]);

  const components = useMemo(
    () => [...new Set(events.map((event) => event.component).filter(Boolean))].sort(),
    [events],
  );

  async function openReport() {
    setReportBusy(true);
    try {
      const text = await getDiagnosticsText();
      setReportText(text);
      setReportOpen(true);
      try {
        await navigator.clipboard.writeText(text);
        setCopyState("copied");
      } catch {
        setCopyState("manual");
      }
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setReportBusy(false);
    }
  }

  async function copyReport() {
    try {
      await navigator.clipboard.writeText(reportText);
      setCopyState("copied");
    } catch {
      setCopyState("manual");
    }
  }

  if (error && !health) return <PageState kind="error">{error}</PageState>;
  if (!health || !info) return <PageState kind="loading" title="Загрузка сведений о системе…" />;

  const rawPath = info.raw_storage_path ?? info.market_raw_path ?? "—";

  return (
    <section>
      <PageHeader
        title={labels.nav.system}
        description="Диагностика окружения, сервисов и технологический журнал"
        actions={
          <button type="button" className="secondary" disabled={reportBusy} onClick={() => void openReport()}>
            Скопировать диагностический отчёт
          </button>
        }
      />

      <div className="tabs" role="tablist">
        <button type="button" className={`tab${tab === "overview" ? " active" : ""}`} onClick={() => setTab("overview")}>
          Обзор
        </button>
        <button
          type="button"
          className={`tab${tab === "diagnostics" ? " active" : ""}`}
          onClick={() => setTab("diagnostics")}
        >
          Диагностика
        </button>
      </div>

      {tab === "overview" ? (
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
      ) : null}

      {tab === "diagnostics" ? (
        <article className="panel">
          <div className="page-header" style={{ marginBottom: "0.75rem" }}>
            <h2>Технологический журнал (сегодня)</h2>
            <button type="button" className="secondary" onClick={() => void loadEvents()}>
              Обновить
            </button>
          </div>
          <div className="filters" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
            <label>
              Уровень
              <select value={level} onChange={(event) => setLevel(event.target.value as LevelFilter)}>
                <option value="ALL">Все</option>
                <option value="ERROR">Ошибки</option>
                <option value="WARNING">Предупреждения</option>
                <option value="INFO">Информация</option>
              </select>
            </label>
            <label>
              Компонент
              <select value={component} onChange={(event) => setComponent(event.target.value)}>
                <option value="">Все</option>
                {components.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {events.length === 0 ? (
            <p className="muted">Событий за текущий день нет.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Время</th>
                    <th>Уровень</th>
                    <th>Компонент</th>
                    <th>Событие</th>
                    <th>Сообщение</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => (
                    <tr key={event.id} className={event.level === "ERROR" ? "row-error" : undefined}>
                      <td>{formatDateTime(event.timestamp)}</td>
                      <td>
                        <StatusBadge status={event.level.toLowerCase()} />
                      </td>
                      <td>{event.component}</td>
                      <td className="mono">{event.event_type}</td>
                      <td>{event.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      ) : null}

      {reportOpen ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setReportOpen(false)}>
          <div
            className="modal diagnostics-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="diag-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <h2 id="diag-title">Диагностический отчёт</h2>
            {copyState === "copied" ? <p className="muted">Диагностический отчёт скопирован</p> : null}
            {copyState === "manual" ? (
              <p className="muted">Автокопирование недоступно — скопируйте текст вручную.</p>
            ) : null}
            <textarea className="diagnostics-text" readOnly value={reportText} rows={18} />
            <div className="button-row">
              <button type="button" disabled={reportBusy} onClick={() => void copyReport()}>
                Скопировать
              </button>
              <button type="button" className="secondary" disabled={reportBusy} onClick={() => void openReport()}>
                Обновить отчёт
              </button>
              <button type="button" className="secondary" onClick={() => setReportOpen(false)}>
                Закрыть
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
