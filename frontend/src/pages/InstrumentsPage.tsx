import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  getCatalogInstrument,
  getInstrumentMasterSyncStatus,
  searchCatalogInstruments,
  triggerInstrumentMasterSync,
  type CatalogInstrument,
  type CatalogInstrumentDetail,
  type InstrumentMasterSyncStatus,
  type SupportLevel,
} from "../api/instruments";
import { subtypeLabel, supportLevelLabel } from "../features/manualPortfolio/labels";
import { EmptyState, MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { MetricHelp } from "../help";
import { formatDateTime, formatRelativeTime } from "../utils/format";
import { labels } from "../utils/labels";

function SupportBadge({ level }: { level?: SupportLevel | null }) {
  const raw = (level || "").toUpperCase();
  const status =
    raw === "FULL" ? "ok" : raw === "PARTIAL" ? "warning" : raw === "INACTIVE" ? "inactive" : "info";
  return <StatusBadge status={status} label={supportLevelLabel(level)} />;
}

export function InstrumentsPage() {
  const [sync, setSync] = useState<InstrumentMasterSyncStatus | null>(null);
  const [items, setItems] = useState<CatalogInstrument[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [assetClass, setAssetClass] = useState("");
  const [support, setSupport] = useState("");
  const [activeOnly, setActiveOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const [syncTick, setSyncTick] = useState(0);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(t);
  }, [search]);

  useEffect(() => {
    setPage(1);
  }, [debounced, assetClass, support, activeOnly]);

  useEffect(() => {
    const controller = new AbortController();
    getInstrumentMasterSyncStatus(controller.signal)
      .then(setSync)
      .catch(() => setSync({ status: "NONE", report: null }));
    return () => controller.abort();
  }, [syncTick]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    searchCatalogInstruments(
      {
        search: debounced || undefined,
        asset_class: assetClass || undefined,
        support: support || undefined,
        active: activeOnly ? true : undefined,
        page,
        page_size: 25,
      },
      controller.signal,
    )
      .then((resp) => {
        setItems(resp.items);
        setTotal(resp.total);
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [debounced, assetClass, support, activeOnly, page]);

  const pageCount = Math.max(1, Math.ceil(total / 25));
  const report = (sync?.report ?? {}) as Record<string, unknown>;

  async function runSync() {
    setSyncBusy(true);
    try {
      await triggerInstrumentMasterSync(true);
      setSyncTick((n) => n + 1);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSyncBusy(false);
    }
  }

  return (
    <section data-testid="instruments-catalog-page">
      <PageHeader
        title={labels.nav.instruments}
        description="Каталог инструментов MOEX: покрытие и поддержка Kraken. Не путать с котировками."
        helpPageId="instruments_catalog"
      />

      <p className="page-purpose">
        Каталог = master-поиск и coverage. Живые котировки остаются на{" "}
        <Link to="/market">Рынке / Котировках</Link>.
      </p>

      <div className="card-grid" data-testid="instrument-sync-cards">
        <MetricCard
          label="Статус sync"
          value={<StatusBadge status={sync?.status ?? "NONE"} />}
          helpId="instrument_master"
          hint={
            sync?.finished_at || sync?.started_at
              ? formatRelativeTime(sync.finished_at ?? sync.started_at)
              : "Ещё не запускался"
          }
        />
        <MetricCard
          label="Последний sync"
          value={formatDateTime(sync?.finished_at ?? sync?.started_at)}
          helpId="instrument_master"
        />
        <MetricCard
          label="Создано / обновлено"
          value={`${Number(report.created ?? 0)} / ${Number(report.updated ?? 0)}`}
          hint={`Деактивировано: ${Number(report.deactivated ?? 0)}`}
        />
        <article className="metric-card">
          <span className="metric-label">Оператор</span>
          <button type="button" className="secondary" disabled={syncBusy} onClick={() => void runSync()}>
            {syncBusy ? "Запуск…" : "Запустить sync"}
          </button>
          <small className="metric-hint">Асинхронно через Celery; не трогает research Dataset.</small>
        </article>
      </div>

      <div className="filters" style={{ marginTop: "1rem" }}>
        <label>
          Поиск
          <input
            data-testid="instruments-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="SECID, название, ISIN"
          />
        </label>
        <label>
          Класс
          <select value={assetClass} onChange={(e) => setAssetClass(e.target.value)}>
            <option value="">Все</option>
            <option value="equity">Акции</option>
            <option value="bond">Облигации</option>
          </select>
        </label>
        <label>
          Поддержка
          <select
            value={support}
            onChange={(e) => setSupport(e.target.value)}
            data-testid="instruments-support-filter"
          >
            <option value="">Любая</option>
            <option value="FULL">FULL</option>
            <option value="PARTIAL">PARTIAL</option>
            <option value="CATALOG_ONLY">CATALOG_ONLY</option>
            <option value="INACTIVE">INACTIVE</option>
          </select>
        </label>
        <label className="checkbox-row">
          <input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} />
          Только активные
        </label>
      </div>

      {loading ? <PageState kind="loading" title="Загрузка каталога…" /> : null}
      {!loading && error ? <PageState kind="error">{error}</PageState> : null}

      {!loading && !error && items.length === 0 ? (
        <EmptyState
          title="Ничего не найдено"
          reason="Измените поиск или фильтры. Если каталог пуст — запустите Instrument Master sync."
        />
      ) : null}

      {!loading && !error && items.length > 0 ? (
        <>
          <div className="table-wrap" data-testid="instruments-table">
            <table>
              <thead>
                <tr>
                  <th>SECID</th>
                  <th>Название</th>
                  <th>Тип</th>
                  <th>
                    Поддержка <MetricHelp metricId="support_level" />
                  </th>
                  <th>Board</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">
                      <Link to={`/instruments/${encodeURIComponent(row.symbol)}`}>{row.symbol}</Link>
                    </td>
                    <td>{row.name}</td>
                    <td>
                      {labels.assetClass(row.asset_class)}
                      {row.instrument_subtype ? (
                        <div className="muted">{subtypeLabel(row.instrument_subtype)}</div>
                      ) : null}
                    </td>
                    <td>
                      <SupportBadge level={row.support_level} />
                    </td>
                    <td className="mono">{row.primary_board ?? "—"}</td>
                    <td>
                      <Link to={`/instruments/${encodeURIComponent(row.symbol)}`}>Карточка</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="page-actions" style={{ marginTop: "0.75rem" }}>
            <span className="muted">
              {total} шт. · стр. {page}/{pageCount}
            </span>
            <button type="button" className="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Назад
            </button>
            <button
              type="button"
              className="secondary"
              disabled={page >= pageCount}
              onClick={() => setPage((p) => p + 1)}
            >
              Вперёд
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}

export function InstrumentCatalogDetailPage() {
  const { secid = "" } = useParams();
  const [detail, setDetail] = useState<CatalogInstrumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!secid) return;
    const controller = new AbortController();
    setDetail(null);
    setError(null);
    getCatalogInstrument(secid, controller.signal)
      .then(setDetail)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      });
    return () => controller.abort();
  }, [secid]);

  if (error) return <PageState kind="error">{error}</PageState>;
  if (!detail) return <PageState kind="loading" title="Загрузка инструмента…" />;

  const coverage = detail.coverage;
  const subtype = (detail.instrument_subtype || "").toLowerCase();
  const isBond =
    (detail.asset_class || "").toLowerCase() === "bond" ||
    subtype.includes("bond") ||
    subtype === "ofz_gov";
  const isEquity = (detail.asset_class || "").toLowerCase() === "equity";

  return (
    <section data-testid="instrument-catalog-detail">
      <PageHeader
        title={detail.symbol}
        description={detail.name}
        helpPageId="instrument_catalog_detail"
        actions={
          <Link className="secondary" to="/instruments">
            ← К каталогу
          </Link>
        }
      />

      <div className="card-grid">
        <MetricCard label="Класс" value={labels.assetClass(detail.asset_class)} />
        <MetricCard label="Подтип" value={subtypeLabel(detail.instrument_subtype)} />
        <MetricCard
          label="Поддержка"
          value={<SupportBadge level={detail.support_level} />}
          helpId="support_level"
        />
        <MetricCard label="Board" value={detail.primary_board ?? "—"} />
        <MetricCard label="ISIN" value={detail.isin ?? "—"} />
        <MetricCard
          label="Research universe"
          value={detail.research_member ? "Входит" : "Не входит"}
          helpId="model_coverage"
        />
      </div>

      <article className="panel" style={{ marginTop: "1rem" }} data-testid="coverage-matrix">
        <h2>
          Что Kraken умеет <MetricHelp metricId="model_coverage" />
        </h2>
        <p className="muted">
          Присутствие в каталоге не означает, что модель прогноза поддерживает инструмент.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Возможность</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ["live_quote", "Живая котировка"],
                  ["portfolio_value", "Оценка в портфеле"],
                  ["predict", "Прогноз модели"],
                  ["fundamental", "Фундаментал"],
                  ["fixed_income", "Анализ облигаций"],
                  ["rebalance", "Ребаланс (лоты)"],
                  ["cashflow", "Денежные потоки"],
                ] as const
              ).map(([key, label]) => (
                <tr key={key}>
                  <td>{label}</td>
                  <td>
                    <StatusBadge status={coverage[key] ? "ok" : "inactive"} label={coverage[key] ? "Да" : "Нет"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>

      <div className="page-actions" style={{ marginTop: "1rem" }}>
        {isBond ? (
          <Link to={`/bonds/${encodeURIComponent(detail.symbol)}`}>
            Открыть карточку облигации (потоки, NKD)
          </Link>
        ) : null}
        <Link to={`/market/instruments/${detail.id}`}>Котировки</Link>
        {isEquity ? <Link to="/fundamentals">Компании / фундаментал</Link> : null}
      </div>
    </section>
  );
}
