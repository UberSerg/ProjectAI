import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  getSimulatorCostSensitivity,
  getSimulatorDay,
  getSimulatorFills,
  getSimulatorNav,
  getSimulatorRun,
  listSimulatorRuns,
  type CostSensitivityItem,
  type DayInspectorResponse,
  type NavSeriesResponse,
  type SimulationFill,
  type SimulationRunSummary,
} from "../api/simulator";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { DrawdownChart } from "../features/simulator/DrawdownChart";
import {
  contextFromSimulatorFill,
  DecisionExplanationPanel,
} from "../features/decisionExplanation";
import {
  costLabel,
  isResearchContextSegment,
  pickCanonicalPair,
  policyShort,
  segmentLabel,
  segmentTone,
  SIM_RANGE_PRESETS,
  simPresetRange,
  type SimRangePreset,
} from "../features/simulator/helpers";
import { NavEquityChart } from "../features/simulator/NavEquityChart";
import { MetricHelp, PageHelp } from "../help";
import {
  formatDate,
  formatDateRange,
  formatMoney,
  formatNumber,
  formatPercent,
  formatPercentPoints,
  formatPrice,
  shortHash,
} from "../utils/format";
import { labels } from "../utils/labels";

function SegmentBadge({ segment }: { segment?: string | null }) {
  return <span className={`sim-segment-badge sim-segment-${segmentTone(segment)}`}>{segmentLabel(segment)}</span>;
}

function signedReturnClass(value?: number | null): string {
  if (value == null || Number.isNaN(value) || value === 0) return "";
  return value < 0 ? "value-negative" : "value-positive";
}

/** Excess pp must not look like portfolio profit — neutral analytical tone. */
function excessClass(): string {
  return "value-excess";
}

export function SimulatorRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [run, setRun] = useState<SimulationRunSummary | null>(null);
  const [nav, setNav] = useState<NavSeriesResponse | null>(null);
  const [fills, setFills] = useState<SimulationFill[]>([]);
  const [costs, setCosts] = useState<CostSensitivityItem[]>([]);
  const [siblings, setSiblings] = useState<SimulationRunSummary[]>([]);
  const [day, setDay] = useState<DayInspectorResponse | null>(null);
  const [dayLoading, setDayLoading] = useState(false);
  const [selectedFill, setSelectedFill] = useState<SimulationFill | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const available = useMemo(() => {
    const from = nav?.date_from ?? run?.date_from ?? null;
    const to = nav?.date_to ?? run?.date_to ?? null;
    if (!from || !to) return null;
    return { from, to };
  }, [nav, run]);

  const rangeFrom = searchParams.get("from") ?? available?.from ?? "";
  const rangeTo = searchParams.get("to") ?? available?.to ?? "";
  const selectedDate = searchParams.get("date");

  const patchParams = useCallback(
    (patch: Record<string, string | null>) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          Object.entries(patch).forEach(([key, value]) => {
            if (value == null || value === "") next.delete(key);
            else next.set(key, value);
          });
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([
      getSimulatorRun(runId, controller.signal),
      getSimulatorNav(runId, controller.signal),
      getSimulatorFills(runId, controller.signal),
      getSimulatorCostSensitivity(runId, controller.signal),
      listSimulatorRuns(50, controller.signal),
    ])
      .then(([runRow, navRow, fillRows, costRow, allRuns]) => {
        setRun(runRow);
        setNav(navRow);
        setFills(fillRows);
        setCosts(costRow.items ?? []);
        setSiblings(allRuns);
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [runId]);

  // Seed URL range when nav arrives and params empty
  useEffect(() => {
    if (!available) return;
    if (!searchParams.get("from") || !searchParams.get("to")) {
      patchParams({
        from: searchParams.get("from") ?? available.from,
        to: searchParams.get("to") ?? available.to,
      });
    }
  }, [available, patchParams, searchParams]);

  useEffect(() => {
    if (!runId || !selectedDate) {
      setDay(null);
      return;
    }
    const controller = new AbortController();
    setDayLoading(true);
    getSimulatorDay(runId, selectedDate, controller.signal)
      .then(setDay)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setDay(null);
        }
      })
      .finally(() => setDayLoading(false));
    return () => controller.abort();
  }, [runId, selectedDate]);

  const pair = useMemo(() => {
    if (!run) return { dev: null, holdout: null };
    return pickCanonicalPair(siblings, run);
  }, [run, siblings]);

  if (error) return <PageState kind="error">{error}</PageState>;
  if (loading || !run) return <PageState kind="loading" title="Загрузка симуляции…" />;

  const metrics = run.metrics ?? {};
  const bench = run.benchmark ?? nav?.benchmark ?? {};
  const portfolioReturn = metrics.total_price_return ?? null;
  const imoexReturn = bench.total_price_return ?? null;
  const excess =
    metrics.excess_vs_imoex != null
      ? metrics.excess_vs_imoex
      : portfolioReturn != null && imoexReturn != null
        ? portfolioReturn - imoexReturn
        : null;

  const researchLabel =
    run.research_result ??
    (isResearchContextSegment(run.segment) ? "MIXED" : null);

  const effectiveFrom = rangeFrom || available?.from || "";
  const effectiveTo = rangeTo || available?.to || "";

  function applyPreset(preset: SimRangePreset) {
    if (!available) return;
    const next = simPresetRange(preset, available);
    patchParams({ from: next.from, to: next.to });
  }

  function selectDate(date: string) {
    patchParams({ date });
  }

  const costMaxAbs = Math.max(
    0.01,
    ...costs.map((c) => Math.abs(c.total_price_return ?? 0)),
  );

  return (
    <section className="sim-run-page">
      <PageHeader
        title="Симуляция портфеля"
        description={`${segmentLabel(run.segment)} · ${formatDateRange(run.date_from, run.date_to)}`}
        helpPageId="simulator_run"
        actions={
          <Link to="/simulator" className="button secondary">
            ← {labels.nav.simulations}
          </Link>
        }
      />

      <div className="sim-chip-row">
        <SegmentBadge segment={run.segment} />
        <span className="chip sim-meta-chip">Candidate V0</span>
        <span className="chip sim-meta-chip">{policyShort(run.spec?.policy_name)}</span>
        <span className="chip sim-meta-chip" title="sim_rebalance">
          {run.spec?.rebalance === "weekly" || run.spec?.rebalance === "WEEKLY" ? "weekly" : run.spec?.rebalance ?? "weekly"}
          <MetricHelp metricId="sim_rebalance" />
        </span>
        <span className="chip sim-meta-chip">
          {run.spec?.execution_timing === "next_open" || !run.spec?.execution_timing
            ? "next open"
            : String(run.spec.execution_timing)}
          <MetricHelp metricId="sim_next_open" />
        </span>
        <span className="chip sim-meta-chip">
          {costLabel(run.spec?.commission_bps)}
          <MetricHelp metricId="sim_bps" />
        </span>
        <PageHelp pageId="simulator_run" />
      </div>

      <div className="sim-status-row panel">
        <div className="sim-status-block">
          <h3>Инженерный статус</h3>
          <StatusBadge status={run.engineering_status ?? run.status} />
          <p className="muted">Успешность прогона пайплайна (данные записаны, расчёт завершён).</p>
        </div>
        <div className="sim-status-block">
          <h3>Research-контекст Candidate V0</h3>
          {researchLabel ? (
            <>
              <span className="sim-research-badge">{researchLabel}</span>
              <p className="muted">
                Качественная пометка исследования модели — не вердикт прибыльности и не gate к торговле.{" "}
                <MetricHelp metricId="sim_oos" />
              </p>
            </>
          ) : (
            <p className="muted">Нет research-метки для этого сегмента.</p>
          )}
        </div>
      </div>

      <div className="card-grid sim-metrics-grid">
        <MetricCard
          label="Начальный NAV"
          value={formatMoney(metrics.initial_nav ?? run.spec?.initial_capital)}
          helpId="sim_nav"
        />
        <MetricCard label="Конечный NAV" value={formatMoney(metrics.final_nav)} helpId="sim_nav" />
        <MetricCard
          label="Доходность портфеля"
          value={
            <span className={signedReturnClass(portfolioReturn)}>{formatPercent(portfolioReturn)}</span>
          }
          hint="Price return (без дивидендов)"
          helpId="sim_cagr"
        />
        <MetricCard
          label="IMOEX"
          value={
            <span className={signedReturnClass(imoexReturn)}>{formatPercent(imoexReturn)}</span>
          }
          hint="Price index"
        />
        <MetricCard
          label="Относительный результат (п.п.)"
          value={<span className={excessClass()}>{formatPercentPoints(excess)}</span>}
          hint="Избыток к IMOEX, не прибыль портфеля"
          helpId="sim_excess"
        />
        <MetricCard
          label="Max DD"
          value={<span className="value-negative">{formatPercent(metrics.max_drawdown)}</span>}
          hint={
            metrics.max_drawdown_peak_date
              ? `${formatDate(metrics.max_drawdown_peak_date)} → ${formatDate(metrics.max_drawdown_trough_date)}`
              : undefined
          }
          helpId="sim_max_drawdown"
        />
        <MetricCard
          label="Sharpe (rf=0)"
          value={
            metrics.sharpe_rf0 == null
              ? "—"
              : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(metrics.sharpe_rf0)
          }
          hint="Research metric"
          helpId="sim_sharpe"
        />
        <MetricCard
          label="Оборот"
          value={
            metrics.turnover_ratio == null
              ? "—"
              : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(metrics.turnover_ratio)
          }
          hint={metrics.trade_count != null ? `${formatNumber(metrics.trade_count)} сделок` : undefined}
          helpId="sim_turnover"
        />
      </div>

      <div className="panel">
        <div className="quotes-toolbar">
          <div>
            <h2 className="sim-section-title">Кривая капитала</h2>
            <p className="muted">Kraken NAV vs IMOEX, нормализованный к начальному NAV выбранного окна.</p>
          </div>
          <div className="quotes-presets">
            {SIM_RANGE_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                className={`chip${presetActive(preset, effectiveFrom, effectiveTo, available) ? " active" : ""}`}
                onClick={() => applyPreset(preset)}
              >
                {preset}
              </button>
            ))}
          </div>
        </div>
        {nav?.items?.length ? (
          <NavEquityChart
            items={nav.items}
            benchmarkSeries={nav.benchmark_series ?? []}
            rebalanceDates={nav.rebalance_dates ?? []}
            dateFrom={effectiveFrom}
            dateTo={effectiveTo}
            selectedDate={selectedDate}
            onSelectDate={selectDate}
          />
        ) : (
          <PageState kind="empty">Нет серии NAV</PageState>
        )}
      </div>

      <div className="panel">
        <h2 className="sim-section-title">Просадка</h2>
        <p className="muted">
          Пик: {formatDate(metrics.max_drawdown_peak_date)} · Дно:{" "}
          {formatDate(metrics.max_drawdown_trough_date)} · Восстановление:{" "}
          {formatDate(metrics.max_drawdown_recovery_date)}
        </p>
        {nav?.items?.length ? (
          <DrawdownChart
            items={nav.items}
            dateFrom={effectiveFrom}
            dateTo={effectiveTo}
            peakDate={metrics.max_drawdown_peak_date}
            troughDate={metrics.max_drawdown_trough_date}
            recoveryDate={metrics.max_drawdown_recovery_date}
            selectedDate={selectedDate}
            onSelectDate={selectDate}
          />
        ) : null}
      </div>

      <div className="panel sim-inspector">
        <h2 className="sim-section-title">Инспектор даты</h2>
        {!selectedDate ? (
          <p className="muted">Кликните по графику, чтобы выбрать дату.</p>
        ) : dayLoading ? (
          <p className="muted">Загрузка дня {formatDate(selectedDate)}…</p>
        ) : !day ? (
          <p className="muted">Нет данных на {formatDate(selectedDate)}</p>
        ) : (
          <>
            <div className="sim-inspector-metrics">
              <MetricCard label="NAV" value={formatMoney(day.nav?.nav)} helpId="sim_nav" />
              <MetricCard label="Cash" value={formatMoney(day.nav?.cash)} helpId="sim_cash" />
              <MetricCard
                label="Gross exposure"
                value={formatMoney(day.nav?.gross_exposure)}
                helpId="sim_exposure"
              />
              <MetricCard label="Позиций" value={formatNumber(day.nav?.positions_count)} />
              <MetricCard label="Ребаланс" value={day.rebalance ? "Да" : "Нет"} helpId="sim_rebalance" />
              <MetricCard label="Ордеров" value={formatNumber(day.orders.length)} />
              <MetricCard label="Исполнений" value={formatNumber(day.fills.length)} />
            </div>
            <h3>Позиции на {formatDate(selectedDate)}</h3>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Тикер</th>
                    <th className="numeric">Кол-во</th>
                    <th className="numeric">Цена</th>
                    <th className="numeric">Стоимость</th>
                    <th className="numeric">Вес</th>
                  </tr>
                </thead>
                <tbody>
                  {day.positions.length ? (
                    day.positions.map((p) => (
                      <tr key={`${p.instrument_id}-${p.ticker}`}>
                        <td>{p.ticker}</td>
                        <td className="numeric">{formatNumber(p.quantity)}</td>
                        <td className="numeric">{formatPrice(p.market_price)}</td>
                        <td className="numeric">{formatMoney(p.market_value)}</td>
                        <td className="numeric">{formatPercent(p.weight)}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={5}>Нет позиций</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      <div className="panel">
        <h2 className="sim-section-title">Исполнения (fills)</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Дата</th>
                <th>Тикер</th>
                <th>Сторона</th>
                <th className="numeric">Кол-во</th>
                <th className="numeric">Цена</th>
                <th className="numeric">Notional</th>
                <th className="numeric">Rank</th>
                <th>Политика</th>
              </tr>
            </thead>
            <tbody>
              {fills.length ? (
                fills.map((f, idx) => (
                  <tr
                    key={`${f.execution_date}-${f.instrument_id}-${f.side}-${idx}`}
                    className="clickable"
                    onClick={() => setSelectedFill(f)}
                  >
                    <td>{formatDate(f.execution_date)}</td>
                    <td>{f.ticker}</td>
                    <td>{f.side}</td>
                    <td className="numeric">{formatNumber(f.quantity)}</td>
                    <td className="numeric">{formatPrice(f.fill_price)}</td>
                    <td className="numeric">{formatMoney(f.notional)}</td>
                    <td className="numeric">{f.rank ?? "—"}</td>
                    <td>{f.policy_name ?? "—"}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8}>Нет исполнений</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {selectedFill ? (
          <DecisionExplanationPanel
            context={contextFromSimulatorFill(selectedFill, {
              candidateConfigHash: run.candidate_config_hash,
            })}
            onClose={() => setSelectedFill(null)}
          />
        ) : null}
      </div>

      <div className="panel">
        <h2 className="sim-section-title">
          Чувствительность к издержкам <MetricHelp metricId="sim_commission" />
        </h2>
        {costs.length ? (
          <div className="sim-cost-bars">
            {costs.map((c) => {
              const ret = c.total_price_return ?? 0;
              const widthPct = Math.min(100, (Math.abs(ret) / costMaxAbs) * 100);
              return (
                <button
                  key={c.run_id}
                  type="button"
                  className={`sim-cost-row${c.is_current ? " current" : ""}`}
                  onClick={() => {
                    if (!c.is_current) navigate(`/simulator/${c.run_id}`);
                  }}
                >
                  <span className="sim-cost-label">
                    {costLabel(c.commission_bps)}
                    {c.is_current ? " · текущий" : ""}
                  </span>
                  <span className="sim-cost-bar-track">
                    <span
                      className={`sim-cost-bar-fill${ret < 0 ? " neg" : " pos"}`}
                      style={{ width: `${widthPct}%` }}
                    />
                  </span>
                  <span className={`sim-cost-value ${signedReturnClass(ret)}`}>{formatPercent(ret)}</span>
                </button>
              );
            })}
          </div>
        ) : (
          <p className="muted">Нет sibling-прогонов с другой комиссией.</p>
        )}
      </div>

      <div className="panel">
        <h2 className="sim-section-title">
          DEV vs HOLDOUT <MetricHelp metricId="sim_holdout" />
        </h2>
        <p className="muted">
          Образовательное сравнение 0 bps прогонов одного candidate (не доказательство стабильности
          прибыли). Candidate: <code>{shortHash(run.candidate_config_hash)}</code>
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Сегмент</th>
                <th>Run</th>
                <th className="numeric">Доходность</th>
                <th className="numeric">IMOEX</th>
                <th className="numeric">Отн. (п.п.)</th>
                <th className="numeric">Max DD</th>
                <th className="numeric">Sharpe</th>
              </tr>
            </thead>
            <tbody>
              {!pair.dev && !pair.holdout ? (
                <tr>
                  <td colSpan={7} className="muted">
                    Пара 0 bps DEV/HOLDOUT для этого candidate не найдена в списке прогонов.
                  </td>
                </tr>
              ) : (
                ([pair.dev, pair.holdout].filter(Boolean) as SimulationRunSummary[]).map((r) => {
                  const m = r.metrics ?? {};
                  const b = r.benchmark ?? {};
                  const ex =
                    m.excess_vs_imoex != null
                      ? m.excess_vs_imoex
                      : m.total_price_return != null && b.total_price_return != null
                        ? m.total_price_return - b.total_price_return
                        : null;
                  return (
                    <tr key={r.id} className={r.id === run.id ? "sim-row-current" : undefined}>
                      <td>
                        <SegmentBadge segment={r.segment} />
                      </td>
                      <td>
                        <Link to={`/simulator/${r.id}`}>#{r.id}</Link>
                      </td>
                      <td className="numeric">
                        <span className={signedReturnClass(m.total_price_return)}>
                          {formatPercent(m.total_price_return)}
                        </span>
                      </td>
                      <td className="numeric">
                        <span className={signedReturnClass(b.total_price_return)}>
                          {formatPercent(b.total_price_return)}
                        </span>
                      </td>
                      <td className="numeric">
                        <span className={excessClass()}>{formatPercentPoints(ex)}</span>
                      </td>
                      <td className="numeric">{formatPercent(m.max_drawdown)}</td>
                      <td className="numeric">
                        {m.sharpe_rf0 == null
                          ? "—"
                          : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(m.sharpe_rf0)}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel sim-limitations">
        <h2 className="sim-section-title">
          Ограничения интерпретации <MetricHelp metricId="sim_survivorship" />
        </h2>
        <ul>
          <li>Universe — текущая активная когорта (survivorship bias возможен).</li>
          <li>Доходности — price return; дивидендный cash в V0 не моделируется.</li>
          <li>IMOEX — ценовой индекс, не total-return бенчмарк.</li>
          <li>Издержки упрощены (commission/slippage bps); не брокерский реализм.</li>
          <li>Research-метка MIXED — контекст Candidate V0, не сигнал к реальной торговле.</li>
          <li>Историческая симуляция ≠ независимый рыночный опыт; walk-forward обязателен.</li>
        </ul>
      </div>
    </section>
  );
}

function presetActive(
  preset: SimRangePreset,
  from: string,
  to: string,
  available: { from: string; to: string } | null,
): boolean {
  if (!available) return false;
  const expected = simPresetRange(preset, available);
  return expected.from === from && expected.to === to;
}
