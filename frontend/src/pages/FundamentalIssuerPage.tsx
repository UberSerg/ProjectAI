import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  getFundamentalIssuer,
  getIssuerAsOf,
  getIssuerDividends,
  getIssuerEvents,
  getIssuerReports,
  issuerDisplayName,
  provenanceOf,
  reportPeriodLabel,
  reportStandard,
  type FundamentalAsOf,
  type FundamentalDividend,
  type FundamentalEvent,
  type FundamentalIssuer,
  type FundamentalReport,
  type SourceProvenance,
} from "../api/fundamentals";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { MetricHelp } from "../help";
import { formatDate, formatDateTime, formatMoney, formatNumber, formatPercent } from "../utils/format";

function softLoad<T>(promise: Promise<T>, fallback: T): Promise<{ value: T; error?: string }> {
  return promise
    .then((value) => ({ value }))
    .catch((reason: unknown) => {
      if (reason instanceof DOMException && reason.name === "AbortError") throw reason;
      return { value: fallback, error: errorMessage(reason) };
    });
}

function ProvenanceDetails({ data }: { data?: SourceProvenance | null }) {
  if (!data) return null;
  return (
    <details className="details-tech">
      <summary>Технические детали</summary>
      <dl className="tech-dl">
        <div>
          <dt>Провайдер</dt>
          <dd>{data.provider ?? "—"}</dd>
        </div>
        <div>
          <dt>Source ID</dt>
          <dd>{data.source_id ?? data.external_id ?? "—"}</dd>
        </div>
        <div>
          <dt>Публикация</dt>
          <dd>{formatDateTime(data.publication_timestamp ?? data.published_at)}</dd>
        </div>
        <div>
          <dt>Получено</dt>
          <dd>{formatDateTime(data.retrieved_timestamp ?? data.retrieved_at)}</dd>
        </div>
        <div>
          <dt>Hash</dt>
          <dd className="mono">{data.hash ?? data.content_hash ?? "—"}</dd>
        </div>
        <div>
          <dt>Версия</dt>
          <dd>{data.version ?? "—"}</dd>
        </div>
      </dl>
    </details>
  );
}

function DividendTimeline({ rows }: { rows: FundamentalDividend[] }) {
  if (rows.length === 0) {
    return (
      <p className="muted" data-testid="dividends-empty">
        Дивидендных событий нет. Бесплатная лента дивидендов MOEX недоступна — раздел пуст честно, без
        выдуманных дат.
      </p>
    );
  }
  return (
    <div className="table-wrap">
      <table data-testid="dividends-table">
        <thead>
          <tr>
            <th>Анонс</th>
            <th>
              Рекомендация <MetricHelp metricId="dividend_recommendation" />
            </th>
            <th>
              Утверждение <MetricHelp metricId="dividend_approval" />
            </th>
            <th>
              Record date <MetricHelp metricId="record_date" />
            </th>
            <th>Выплата</th>
            <th>Сумма</th>
            <th>
              Доходность <MetricHelp metricId="dividend_yield" />
            </th>
            <th>
              Known at <MetricHelp metricId="known_at" />
            </th>
            <th>Статус</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={String(row.id ?? idx)}>
              <td>{formatDate(row.announcement_date)}</td>
              <td>{formatDate(row.recommendation_date)}</td>
              <td>{formatDate(row.approval_date)}</td>
              <td>{formatDate(row.record_date)}</td>
              <td>{formatDate(row.payment_date)}</td>
              <td>
                {row.amount == null
                  ? "—"
                  : `${formatNumber(row.amount)}${row.currency ? ` ${row.currency}` : ""}`}
              </td>
              <td>{formatPercent(row.dividend_yield ?? row.yield)}</td>
              <td>{formatDateTime(row.known_at)}</td>
              <td>{row.status ?? row.stage ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EventsTimeline({ rows }: { rows: FundamentalEvent[] }) {
  const [filter, setFilter] = useState("all");
  const filtered = useMemo(() => {
    if (filter === "all") return rows;
    return rows.filter((r) => (r.event_type ?? r.type ?? "").toUpperCase() === filter.toUpperCase());
  }, [rows, filter]);

  const types = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => {
      const t = r.event_type ?? r.type;
      if (t) set.add(String(t));
    });
    return Array.from(set).sort();
  }, [rows]);

  if (rows.length === 0) {
    return (
      <p className="muted" data-testid="events-empty">
        Структурированных корпоративных событий нет. Существующие SPLIT из market могут появиться
        позже через API событий; сырой поток раскрытий по умолчанию не показываем.
      </p>
    );
  }

  return (
    <div>
      <div className="filters">
        <label>
          Тип события{" "}
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">Все</option>
            {types.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ul className="timeline-list" data-testid="events-timeline">
        {filtered.map((ev, idx) => (
          <li key={String(ev.id ?? idx)} className="timeline-item">
            <div className="timeline-mark" />
            <div>
              <strong>{ev.title ?? ev.event_type ?? ev.type ?? "Событие"}</strong>
              <div className="muted">
                Дата: {formatDate(ev.event_date ?? ev.effective_date)} · known_at:{" "}
                {formatDateTime(ev.known_at)}
              </div>
              {ev.description ? <p>{ev.description}</p> : null}
              <ProvenanceDetails data={provenanceOf(ev)} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RestatementNote({ reports }: { reports: FundamentalReport[] }) {
  const versions = reports.filter((r) => r.is_restatement || (Number(r.version) || 1) > 1);
  if (versions.length === 0 && reports.length <= 1) return null;

  const hasMulti =
    reports.length > 1 &&
    new Set(reports.map((r) => reportPeriodLabel(r))).size < reports.length;

  if (!versions.length && !hasMulti) return null;

  return (
    <div className="banner banner-warning" data-testid="restatement-note" role="status">
      <strong>
        Отчёт был пересмотрен <MetricHelp metricId="restatement" />
      </strong>
      <p>
        При нескольких версиях для одного периода показываем цепочку Original → Restatement. На
        as-of дату <code>t</code> доступна только версия с known_at ≤ <code>t</code>.
      </p>
      <ul className="plain-list">
        {reports.map((r, idx) => (
          <li key={String(r.id ?? idx)}>
            {reportPeriodLabel(r)} · v{r.version ?? 1} · known_at {formatDateTime(r.known_at)} ·{" "}
            {r.is_restatement ? "пересмотр" : "оригинал / базовая версия"}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function FundamentalIssuerPage() {
  const { issuerId = "" } = useParams();
  const [issuer, setIssuer] = useState<FundamentalIssuer | null>(null);
  const [reports, setReports] = useState<FundamentalReport[]>([]);
  const [dividends, setDividends] = useState<FundamentalDividend[]>([]);
  const [events, setEvents] = useState<FundamentalEvent[]>([]);
  const [asOfDate, setAsOfDate] = useState("2024-04-01");
  const [asOf, setAsOf] = useState<FundamentalAsOf | null>(null);
  const [asOfLoading, setAsOfLoading] = useState(false);
  const [asOfError, setAsOfError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!issuerId) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([
      softLoad(getFundamentalIssuer(issuerId, controller.signal), {
        id: issuerId,
      } as FundamentalIssuer),
      softLoad(getIssuerReports(issuerId, controller.signal), [] as FundamentalReport[]),
      softLoad(getIssuerDividends(issuerId, controller.signal), [] as FundamentalDividend[]),
      softLoad(getIssuerEvents(issuerId, controller.signal), [] as FundamentalEvent[]),
    ])
      .then(([iss, reps, divs, evs]) => {
        setIssuer(iss.value);
        setReports(reps.value);
        setDividends(divs.value);
        setEvents(evs.value);
        if (iss.error && reps.error && divs.error && evs.error) {
          setError(
            "Данные эмитента недоступны. Пустые таблицы — ожидаемое состояние при отложенных провайдерах.",
          );
        }
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [issuerId]);

  const loadAsOf = () => {
    if (!issuerId || !asOfDate) return;
    const controller = new AbortController();
    setAsOfLoading(true);
    setAsOfError(null);
    getIssuerAsOf(issuerId, asOfDate, controller.signal)
      .then((payload) => setAsOf(payload))
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setAsOf(null);
          setAsOfError(errorMessage(reason));
        }
      })
      .finally(() => setAsOfLoading(false));
  };

  const securities = issuer?.securities ?? issuer?.mapped_securities ?? [];
  const latest = issuer?.latest_report ?? reports[0] ?? null;

  if (loading) return <PageState kind="loading" title="Загрузка эмитента…" />;

  return (
    <div className="fundamentals-issuer-page" data-testid="fundamentals-issuer-page">
      <PageHeader
        title={issuerDisplayName(issuer)}
        description="Отчётность, дивиденды и события с учётом known_at / даты публикации."
        helpPageId="fundamentals"
        actions={
          <Link className="button secondary" to="/fundamentals">
            ← К обзору
          </Link>
        }
      />

      {error ? (
        <div className="banner banner-warning" role="status">
          {error}
        </div>
      ) : null}

      <div className="card-grid">
        <MetricCard label="ИНН" value={issuer?.inn ?? issuer?.emitent_inn ?? "—"} />
        <MetricCard
          label="Стандарт отчётности"
          value={issuer?.reporting_standard ?? reportStandard(latest)}
          helpId="IFRS"
        />
        <MetricCard
          label="Возраст отчёта (дни)"
          value={formatNumber(issuer?.report_age_days)}
          helpId="report_age"
        />
        <MetricCard
          label="Последний период"
          value={reportPeriodLabel(latest)}
          helpId="reporting_period"
        />
      </div>

      <div className="card">
        <h3>Привязанные ценные бумаги</h3>
        {securities.length === 0 ? (
          <p className="muted">Нет привязанных SECID / инструментов.</p>
        ) : (
          <ul className="plain-list">
            {securities.map((s, idx) => (
              <li key={`${s.instrument_id ?? s.secid ?? s.ticker ?? idx}`}>
                <strong>{s.ticker ?? s.secid ?? "—"}</strong>
                {s.isin ? <span className="muted"> · {s.isin}</span> : null}
                {s.board ? <span className="muted"> · {s.board}</span> : null}
                {s.instrument_id != null ? (
                  <span>
                    {" "}
                    · <Link to={`/market/instruments/${s.instrument_id}`}>карточка</Link>
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      <RestatementNote reports={reports} />

      <div className="card" data-testid="reports-section">
        <h3>
          Отчёты <MetricHelp metricId="financial_report" />
        </h3>
        {reports.length === 0 ? (
          <p className="muted" data-testid="reports-empty">
            Отчётов нет. Не выдумываем даты публикации и не подставляем scraped disclosure.
          </p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>
                    Период <MetricHelp metricId="reporting_period" />
                  </th>
                  <th>
                    Стандарт <MetricHelp metricId="IFRS" /> / <MetricHelp metricId="RAS" />
                  </th>
                  <th>
                    Публикация <MetricHelp metricId="publication_date" />
                  </th>
                  <th>
                    Known at <MetricHelp metricId="known_at" />
                  </th>
                  <th>Версия</th>
                  <th>
                    Выручка <MetricHelp metricId="revenue" />
                  </th>
                  <th>
                    Чистая прибыль <MetricHelp metricId="net_income" />
                  </th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {reports.map((r, idx) => (
                  <tr key={String(r.id ?? idx)}>
                    <td>{reportPeriodLabel(r)}</td>
                    <td>{reportStandard(r)}</td>
                    <td>{formatDate(r.publication_date ?? r.published_at)}</td>
                    <td>{formatDateTime(r.known_at)}</td>
                    <td>{r.version ?? 1}</td>
                    <td>{r.revenue == null ? "—" : formatMoney(r.revenue)}</td>
                    <td>{r.net_income == null ? "—" : formatMoney(r.net_income)}</td>
                    <td>
                      <StatusBadge status={r.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {reports.map((r, idx) => (
          <ProvenanceDetails key={`prov-${String(r.id ?? idx)}`} data={provenanceOf(r)} />
        ))}
      </div>

      <div className="card" data-testid="dividends-section">
        <h3>Дивиденды</h3>
        <p className="muted">
          Рекомендация ≠ утверждённый дивиденд. Record date ≠ дата анонса. Доходность — производная
          от известной суммы и рыночной цены; total-return учёт пока не ведётся.
        </p>
        <DividendTimeline rows={dividends} />
        {dividends.map((d, idx) => (
          <ProvenanceDetails key={`div-prov-${String(d.id ?? idx)}`} data={provenanceOf(d)} />
        ))}
      </div>

      <div className="card" data-testid="events-section">
        <h3>
          События <MetricHelp metricId="corporate_event" />
        </h3>
        <EventsTimeline rows={events} />
      </div>

      <div className="card" data-testid="asof-explorer">
        <h3>Что было известно на дату?</h3>
        <p className="muted">
          As-of explorer показывает последний отчёт, дивидендное состояние и события с known_at ≤
          выбранной даты — визуальная проверка PIT.
        </p>
        <div className="filters asof-row">
          <label>
            Дата{" "}
            <input
              type="date"
              value={asOfDate}
              onChange={(e) => setAsOfDate(e.target.value)}
              data-testid="asof-date-input"
            />
          </label>
          <button type="button" onClick={loadAsOf} disabled={asOfLoading}>
            {asOfLoading ? "Загрузка…" : "Показать"}
          </button>
        </div>
        {asOfError ? (
          <p className="muted" data-testid="asof-error">
            {asOfError}. Пустой ответ — нормально, если на эту дату ещё нечего было знать.
          </p>
        ) : null}
        {asOf ? (
          <div className="asof-result" data-testid="asof-result">
            <p>
              As-of: <strong>{asOf.as_of ?? asOf.date ?? asOfDate}</strong>
            </p>
            <div className="metric-grid">
              <MetricCard
                label="Последний известный отчёт"
                value={reportPeriodLabel(asOf.latest_report ?? asOf.report)}
              />
              <MetricCard
                label="Дивиденды (известны)"
                value={formatNumber((asOf.dividends ?? asOf.dividend_state ?? []).length)}
              />
              <MetricCard
                label="События (известны)"
                value={formatNumber((asOf.events ?? asOf.known_events ?? []).length)}
              />
            </div>
            {(asOf.notes?.length ?? 0) > 0 ? (
              <ul className="plain-list">
                {asOf.notes?.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : (
          <p className="muted">Выберите дату и нажмите «Показать».</p>
        )}
      </div>
    </div>
  );
}
