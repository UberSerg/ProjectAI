import { useEffect, useMemo, useState } from "react";
import { errorMessage } from "../../api/client";
import {
  getExternalCaProbes,
  getExternalCoverage,
  getExternalInstruments,
  getExternalMlReadiness,
  getExternalReconciliation,
  getExternalSummary,
  type CoverageYear,
  type ExternalInstrument,
  type ExternalSummary,
  type MlYear,
  type ReconciliationItem,
} from "../../api/marketHistory";
import { MetricCard, PageState, StatusBadge } from "../../components/Ui";
import { MetricHelp } from "../../help";
import { formatDate, formatNumber } from "../../utils/format";

type Filter = "all" | "current" | "historical-only" | "quality";

function semanticLabel(value?: string): string {
  switch (value) {
    case "RAW_COMPATIBLE":
      return "Совместимо с RAW";
    case "LIKELY_ADJUSTED":
      return "Похоже на скорректированные цены";
    case "MIXED":
      return "Смешанная семантика";
    case "INCOMPATIBLE":
      return "Несовместимо";
    default:
      return "Не определено";
  }
}

function reconLabel(status: string): string {
  switch (status) {
    case "MATCH":
      return "Совпадает";
    case "SMALL_DIFF":
      return "Небольшие расхождения";
    case "LARGE_DIFF":
      return "Существенные расхождения";
    case "LIKELY_ADJUSTED":
      return "Похоже на скорректированные цены";
    default:
      return "Требует проверки";
  }
}

function maxSymbols(items: CoverageYear[]): number {
  return Math.max(1, ...items.map((i) => i.symbols));
}

export function ExternalArchivePanel() {
  const [summary, setSummary] = useState<ExternalSummary | null>(null);
  const [coverage, setCoverage] = useState<CoverageYear[]>([]);
  const [instruments, setInstruments] = useState<ExternalInstrument[]>([]);
  const [recon, setRecon] = useState<ReconciliationItem[]>([]);
  const [priceSemantic, setPriceSemantic] = useState("UNKNOWN");
  const [ml, setMl] = useState<MlYear[]>([]);
  const [probes, setProbes] = useState<{ symbol: string; event_date: string; verdict: string; label: string }[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([
      getExternalSummary(controller.signal),
      getExternalCoverage(controller.signal),
      getExternalInstruments({ limit: 500 }, controller.signal),
      getExternalReconciliation(controller.signal),
      getExternalMlReadiness(controller.signal),
      getExternalCaProbes(controller.signal),
    ])
      .then(([sum, cov, inst, rec, ready, ca]) => {
        setSummary(sum);
        setCoverage(cov.items ?? []);
        setInstruments(inst.items ?? []);
        setRecon(rec.items ?? []);
        setPriceSemantic(rec.price_semantic ?? sum.price_semantic ?? "UNKNOWN");
        setMl(ready.items ?? []);
        setProbes(ca.items ?? []);
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  const filtered = useMemo(() => {
    return instruments.filter((row) => {
      if (filter === "current") return row.match_status === "EXACT_CURRENT_MATCH";
      if (filter === "historical-only") return row.match_status === "UNKNOWN_HISTORICAL_SYMBOL";
      if (filter === "quality") return row.quality_status !== "OK";
      return true;
    });
  }, [instruments, filter]);

  if (loading) return <PageState kind="loading" title="Загрузка исторического архива…" />;
  if (error) return <PageState kind="error">{error}</PageState>;
  if (!summary?.registered) {
    return (
      <div className="card">
        <p>
          Исторический архив ещё не зарегистрирован. Оператор загружает его через CLI
          (<code>python -m app.modules.market_history.cli_external</code>), не через браузер.
        </p>
      </div>
    );
  }

  const matchCounts = summary.match_counts ?? {};
  const historicalOnly = matchCounts.UNKNOWN_HISTORICAL_SYMBOL ?? 0;
  const exact = matchCounts.EXACT_CURRENT_MATCH ?? 0;
  const peak = maxSymbols(coverage);
  const eligibleRows = summary.eligibility_counts?.ELIGIBLE ?? 0;

  return (
    <div className="external-archive">
      <div className="banner banner-warning" role="status">
        Этот архив используется для исследования. Он не заменяет официальные MOEX данные в рабочем
        контуре. <MetricHelp metricId="external_history" />
      </div>

      <div className="card-grid">
        <MetricCard label="Источник" value="External 30Y CSV" helpId="external_history" />
        <MetricCard
          label="Период"
          value={`${formatDate(summary.min_date)} → ${formatDate(summary.max_date)}`}
          helpId="coverage"
        />
        <MetricCard label="Строк" value={formatNumber(summary.rows ?? summary.staged_rows)} />
        <MetricCard label="Инструментов" value={formatNumber(summary.symbols)} helpId="historical_universe" />
        <MetricCard label="Historical-only" value={formatNumber(historicalOnly)} helpId="survivorship_bias" />
        <MetricCard label="Совпало с текущим" value={formatNumber(exact)} helpId="ticker_identity" />
        <MetricCard label="Семантика цен" value={semanticLabel(priceSemantic)} helpId="raw_price" />
        <MetricCard
          label="Canonical"
          value={summary.canonical_candles_untouched ? "не изменён" : "проверьте"}
          helpId="canonical_market_data"
        />
      </div>

      <div className="card-grid">
        <div className="card">
          <h3>
            Исторический universe <MetricHelp metricId="historical_universe" />
          </h3>
          <p>Текущий universe: 43</p>
          <p>Исторический архив: {formatNumber(summary.symbols)} уникальных тикеров</p>
          <p>Historical-only: {formatNumber(historicalOnly)}</p>
          <p>Потенциально eligible (строки): {formatNumber(eligibleRows)}</p>
          <p className="muted">
            Это расширяет исследовательский набор относительно текущей когорты, но не означает, что
            смещение выживаемости полностью устранено.
          </p>
        </div>
        <div className="card">
          <h3>
            Качество данных <MetricHelp metricId="price_jump" />
          </h3>
          <p>Валидных строк: {formatNumber(summary.valid_rows)}</p>
          <p>Отклонённых: {formatNumber(summary.rejected_rows)}</p>
          <p>Quality OK: {formatNumber(summary.quality_counts?.OK)}</p>
          <p>Degraded / sparse: {formatNumber(
            (summary.quality_counts?.DEGRADED ?? 0) + (summary.quality_counts?.SPARSE ?? 0),
          )}</p>
          <p className="muted">Крупные ценовые скачки — диагностика, не автоматическая ошибка.</p>
        </div>
        <div className="card">
          <h3>
            ML readiness <MetricHelp metricId="research_eligible" />
          </h3>
          <p>Price-only history: да (staging)</p>
          <p>Dataset PIT V2 (90 признаков): {priceSemantic === "RAW_COMPATIBLE" ? "частично" : "нет / частично"}</p>
          <p>
            Готовых лет feature-stack: {ml.filter((y) => y.feature_stack_status === "READY").length}
          </p>
          <p className="muted">
            Ранние годы часто без полного macro/relations контекста. Не форсируем 90 признаков в 1995.
          </p>
        </div>
        <div className="card">
          <h3>
            Corporate-action probes <MetricHelp metricId="adjusted_price" />
          </h3>
          {probes.length === 0 ? (
            <p className="muted">Нет результатов probes — сначала reconcile.</p>
          ) : (
            <ul className="plain-list">
              {probes.map((p) => (
                <li key={`${p.symbol}-${p.event_date}`}>
                  <strong>{p.symbol}</strong> {p.event_date}: {p.verdict}{" "}
                  <span className="muted">({p.label})</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="card">
        <h3>
          Покрытие по годам <MetricHelp metricId="coverage" />
        </h3>
        <div className="coverage-bars" aria-label="Инструменты по годам">
          {coverage.map((row) => (
            <div key={row.year} className="coverage-bar-row" title={`${row.year}: ${row.symbols}`}>
              <span className="coverage-year">{row.year}</span>
              <div className="coverage-track">
                <div className="coverage-fill" style={{ width: `${(100 * row.symbols) / peak}%` }} />
              </div>
              <span className="coverage-count">{row.symbols}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>
          Сверка с MOEX <MetricHelp metricId="source_reconciliation" />
        </h3>
        <p>
          Precedence: MOEX &gt; external <MetricHelp metricId="source_precedence" />
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Overlap</th>
                <th>Exact OHLC %</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {recon.slice(0, 40).map((row) => (
                <tr key={row.source_symbol}>
                  <td>{row.source_symbol}</td>
                  <td>{formatNumber(row.overlap_rows)}</td>
                  <td>
                    {row.exact_ohlc_share == null ? "—" : `${(row.exact_ohlc_share * 100).toFixed(1)}%`}
                  </td>
                  <td>{reconLabel(row.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="filters">
          <label>
            Фильтр инструментов
            <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
              <option value="all">Все</option>
              <option value="current">Текущий match</option>
              <option value="historical-only">Historical-only</option>
              <option value="quality">Quality issues</option>
            </select>
          </label>
          <StatusBadge status={summary.status} />
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>First</th>
                <th>Last</th>
                <th>Rows</th>
                <th>Years</th>
                <th>Match</th>
                <th>Quality</th>
                <th>Research</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 100).map((row) => (
                <tr key={row.source_symbol}>
                  <td>{row.source_symbol}</td>
                  <td>{formatDate(row.first_date)}</td>
                  <td>{formatDate(row.last_date)}</td>
                  <td>{formatNumber(row.observations)}</td>
                  <td>{row.active_years.length}</td>
                  <td>{row.match_status}</td>
                  <td>{row.quality_status}</td>
                  <td>{row.research_eligible ? "да" : "нет"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
