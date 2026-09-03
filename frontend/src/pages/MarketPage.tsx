import { type KeyboardEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  getInstruments,
  getMarketSummary,
  type Instrument,
  type MarketSummary,
  type Page,
} from "../api/market";
import { BackfillModal } from "../features/market/BackfillModal";
import { useMarketActions } from "../features/market/useMarketActions";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { formatDate, formatDateRange, formatNumber } from "../utils/format";
import { labels } from "../utils/labels";

const PAGE_SIZE = 25;

export function instrumentPath(id: string): string {
  return `/market/instruments/${encodeURIComponent(id)}`;
}

export function MarketPage() {
  const navigate = useNavigate();
  const { startUpdate, startBackfill, startDq } = useMarketActions();
  const [result, setResult] = useState<Page<Instrument> | null>(null);
  const [summary, setSummary] = useState<MarketSummary | null>(null);
  const [search, setSearch] = useState("");
  const [assetClass, setAssetClass] = useState("");
  const [source, setSource] = useState("");
  const [active, setActive] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [backfillOpen, setBackfillOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const filtersActive = Boolean(search || assetClass || source || active);

  useEffect(() => {
    const controller = new AbortController();
    getMarketSummary(controller.signal).then(setSummary).catch(() => setSummary(null));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getInstruments(
      {
        search: search || undefined,
        asset_class: assetClass || undefined,
        source: source || undefined,
        active: active === "" ? undefined : active === "true",
        page,
        page_size: PAGE_SIZE,
      },
      controller.signal,
    )
      .then(setResult)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(errorMessage(reason));
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [search, assetClass, source, active, page]);

  const totalPages = Math.max(1, Math.ceil((result?.total ?? 0) / PAGE_SIZE));

  function openInstrument(id: string) {
    navigate(instrumentPath(id));
  }

  function onRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, id: string) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openInstrument(id);
    }
  }

  return (
    <section>
      <PageHeader
        title={labels.nav.market}
        description="Инструменты, котировки и состояние загрузки"
        helpPageId="market"
        actions={
          <>
            <button type="button" className="secondary" disabled={busy} onClick={() => void startDq(setBusy)}>
              {labels.actions.dataQuality}
            </button>
            <button type="button" className="secondary" disabled={busy} onClick={() => setBackfillOpen(true)}>
              {labels.actions.backfill}
            </button>
            <button type="button" disabled={busy} onClick={() => void startUpdate(setBusy)}>
              {labels.actions.update}
            </button>
          </>
        }
      />

      <div className="card-grid">
        <MetricCard label="Инструментов" value={formatNumber(summary?.instruments_count ?? result?.total)} />
        <MetricCard label="Свечей" value={formatNumber(summary?.records_count)} />
        <MetricCard label="Источники данных" value="MOEX + ЦБ РФ" />
        <MetricCard label="Последние данные" value={formatDate(summary?.last_successful_update)} />
      </div>

      <div className="filters">
        <label>
          Поиск
          <input
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            placeholder="По тикеру или названию"
          />
        </label>
        <label>
          Тип актива
          <select
            value={assetClass}
            onChange={(event) => {
              setAssetClass(event.target.value);
              setPage(1);
            }}
          >
            <option value="">Все</option>
            <option value="equity">Акция</option>
            <option value="index">Индекс</option>
          </select>
        </label>
        <label>
          Источник
          <select
            value={source}
            onChange={(event) => {
              setSource(event.target.value);
              setPage(1);
            }}
          >
            <option value="">Все</option>
            <option value="MOEX">MOEX</option>
            <option value="CBR">CBR</option>
          </select>
        </label>
        <label>
          Статус
          <select
            value={active}
            onChange={(event) => {
              setActive(event.target.value);
              setPage(1);
            }}
          >
            <option value="">Все</option>
            <option value="true">Активен</option>
            <option value="false">Неактивен</option>
          </select>
        </label>
        {filtersActive ? (
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setSearch("");
              setAssetClass("");
              setSource("");
              setActive("");
              setPage(1);
            }}
          >
            {labels.actions.resetFilters}
          </button>
        ) : (
          <span />
        )}
      </div>

      {loading ? <PageState kind="loading" title="Загрузка инструментов…" /> : null}
      {error ? (
        <PageState kind="error" action={<button type="button" onClick={() => setPage((p) => p)}>{labels.actions.retry}</button>}>
          {error}
        </PageState>
      ) : null}
      {!loading && !error && result?.items.length === 0 ? (
        <PageState
          kind="empty"
          title="Рыночные данные ещё не загружены"
          action={
            <button type="button" onClick={() => setBackfillOpen(true)}>
              {labels.actions.backfill}
            </button>
          }
        >
          Запустите загрузку истории, чтобы заполнить таблицу инструментов.
        </PageState>
      ) : null}

      {!loading && !error && result && result.items.length > 0 ? (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Тикер</th>
                  <th>Инструмент</th>
                  <th>Тип</th>
                  <th>Источник</th>
                  <th>История</th>
                  <th>Записей</th>
                  <th>Данные</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((instrument) => {
                  const path = instrumentPath(instrument.id);
                  return (
                    <tr
                      key={instrument.id}
                      className="clickable"
                      tabIndex={0}
                      role="link"
                      aria-label={`${instrument.symbol}, ${instrument.name}`}
                      onClick={() => openInstrument(instrument.id)}
                      onKeyDown={(event) => onRowKeyDown(event, instrument.id)}
                    >
                      <td>
                        <Link
                          className="ticker-link"
                          to={path}
                          onClick={(event) => event.stopPropagation()}
                        >
                          {instrument.symbol}
                        </Link>
                      </td>
                      <td>{instrument.name}</td>
                      <td>{labels.assetClass(instrument.asset_class)}</td>
                      <td>{(instrument.sources ?? []).join(", ") || "—"}</td>
                      <td>{formatDateRange(instrument.first_timestamp, instrument.last_timestamp)}</td>
                      <td className="numeric">{formatNumber(instrument.records_count)}</td>
                      <td>{labels.dataFreshness(instrument.last_timestamp)}</td>
                      <td>
                        <StatusBadge status={instrument.is_active ? "active" : "inactive"} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <span>Найдено: {formatNumber(result.total)}</span>
            <div className="button-row">
              <button type="button" className="secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>
                Назад
              </button>
              <span>
                Стр. {page} из {totalPages}
              </span>
              <button
                type="button"
                className="secondary"
                disabled={page >= totalPages}
                onClick={() => setPage((value) => value + 1)}
              >
                Далее
              </button>
            </div>
          </div>
        </>
      ) : null}

      {backfillOpen ? (
        <BackfillModal
          busy={busy}
          onClose={() => setBackfillOpen(false)}
          onSubmit={(payload) => {
            setBackfillOpen(false);
            void startBackfill(payload, setBusy);
          }}
        />
      ) : null}
    </section>
  );
}
