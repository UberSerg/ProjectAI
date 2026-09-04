import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  getLatestForwardBatch,
  listForwardBatches,
  type ForwardBatchDetail,
  type ForwardBatchSummary,
  type ForwardPredictionItem,
} from "../api/forward";
import {
  getResearchCycleStatus,
  type ResearchCycleOperationalStatus,
} from "../api/researchCycle";
import {
  getShadowDecisions,
  getShadowFills,
  getShadowNav,
  getShadowOrders,
  getShadowOverview,
  type ShadowDecision,
  type ShadowFill,
  type ShadowNavPoint,
  type ShadowOrder,
  type ShadowOverview,
  type ShadowPortfolioSummary,
} from "../api/shadow";
import { MetricCard, PageHeader, PageState } from "../components/Ui";
import {
  contextFromShadowOrder,
  DecisionExplanationPanel,
} from "../features/decisionExplanation";
import { ResearchCycleOpsStrip } from "../features/researchCycle/ResearchCycleOpsStrip";
import { formatAutomaticSchedule } from "../features/researchCycle/helpers";
import {
  EmptyNavHistory,
  OperationalStage,
  PendingZeroState,
} from "../features/shadow/components";
import {
  experimentAgeDays,
  experimentAgeLabel,
  experimentMaturity,
  orderActionLabel,
  pickPortfolioA,
  pickPortfolioB,
  portfolioHumanName,
  portfolioHumanSubtitle,
  riskModeLabel,
  shadowStatusLabel,
  shadowStatusTone,
  shortHash,
} from "../features/shadow/helpers";
import { MetricHelp } from "../help";
import {
  formatDate,
  formatDateTime,
  formatMoney,
  formatPercent,
} from "../utils/format";
import { labels } from "../utils/labels";

interface PortfolioBundle {
  summary: ShadowPortfolioSummary;
  orders: ShadowOrder[];
  fills: ShadowFill[];
  nav: ShadowNavPoint[];
  decisions: ShadowDecision[];
}

async function loadBundle(
  summary: ShadowPortfolioSummary,
  signal: AbortSignal,
): Promise<PortfolioBundle> {
  const id = summary.id;
  const [orders, fills, nav, decisions] = await Promise.all([
    getShadowOrders(id, signal),
    getShadowFills(id, signal),
    getShadowNav(id, signal),
    getShadowDecisions(id, signal),
  ]);
  return { summary, orders, fills, nav, decisions };
}

function StatusChip({ status }: { status?: string | null }) {
  return (
    <span className={`badge badge-${shadowStatusTone(status)}`}>{shadowStatusLabel(status)}</span>
  );
}

function PortfolioCard({
  bundle,
  letter,
}: {
  bundle: PortfolioBundle;
  letter: "A" | "B";
}) {
  const p = bundle.summary;
  const isB = letter === "B";
  return (
    <article className="shadow-portfolio-card panel">
      <header className="shadow-portfolio-card-head">
        <div>
          <p className="shadow-portfolio-letter">Портфель {letter}</p>
          <h3>{portfolioHumanName(p.name)}</h3>
          <p className="muted">{portfolioHumanSubtitle(p.name)}</p>
        </div>
        <StatusChip status={p.status} />
      </header>
      <dl className="sim-dl">
        <div>
          <dt>NAV</dt>
          <dd>{formatMoney(p.nav ?? p.cash)}</dd>
        </div>
        <div>
          <dt>Cash</dt>
          <dd>{formatMoney(p.cash)}</dd>
        </div>
        <div>
          <dt>Рыночная стоимость</dt>
          <dd>{formatMoney(p.market_value ?? 0)}</dd>
        </div>
        <div>
          <dt>Позиции</dt>
          <dd>{p.position_count ?? 0}</dd>
        </div>
        <div>
          <dt>Ожидающие ордера</dt>
          <dd>{p.pending_orders}</dd>
        </div>
        <div>
          <dt>Исполнения</dt>
          <dd>{p.fills}</dd>
        </div>
        <div>
          <dt>Gross exposure</dt>
          <dd>{formatPercent(p.gross_exposure ?? 0)}</dd>
        </div>
        <div>
          <dt>Просадка</dt>
          <dd>{formatPercent(p.drawdown ?? 0)}</dd>
        </div>
        <div>
          <dt>Risk state</dt>
          <dd>{riskModeLabel(p.risk_mode)}</dd>
        </div>
        <div>
          <dt>Последнее решение</dt>
          <dd>{p.last_decision_iso_week ?? "—"}</dd>
        </div>
      </dl>
      {isB ? (
        <div className="shadow-dd-box">
          <h4>
            Защита от просадки <MetricHelp metricId="decision_risk_guard" />
          </h4>
          <p>
            Сейчас: <strong>{riskModeLabel(p.risk_mode)}</strong>, лимит экспозиции{" "}
            {formatPercent(p.exposure_cap)}.
          </p>
          <p className="muted">
            Активируется при просадке {formatPercent(p.dd_trigger ?? -0.2)}; возвращает полную
            экспозицию при {formatPercent(p.dd_recovery ?? -0.1)}. Пока просадки нет — guard не
            вмешивается.
          </p>
        </div>
      ) : (
        <p className="muted shadow-dd-box">Базовые ограничения риска без Drawdown Guard.</p>
      )}
      <p className="shadow-tech-id muted">
        Технический id: <code>{p.name}</code>
      </p>
    </article>
  );
}

export function ShadowPage() {
  const [overview, setOverview] = useState<ShadowOverview | null>(null);
  const [bundles, setBundles] = useState<PortfolioBundle[] | null>(null);
  const [forward, setForward] = useState<ForwardBatchDetail | null>(null);
  const [forwardList, setForwardList] = useState<ForwardBatchSummary[]>([]);
  const [cycleStatus, setCycleStatus] = useState<ResearchCycleOperationalStatus | null>(null);
  const [cycleError, setCycleError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAllPreds, setShowAllPreds] = useState(false);
  const [selectedOrder, setSelectedOrder] = useState<{
    order: ShadowOrder;
    portfolioName: string;
    riskName: string;
  } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const ov = await getShadowOverview(controller.signal);
        setOverview(ov);
        if (!ov.portfolios.length) {
          setBundles([]);
          return;
        }
        const loaded = await Promise.all(ov.portfolios.map((p) => loadBundle(p, controller.signal)));
        setBundles(loaded);
        try {
          const latest = await getLatestForwardBatch(controller.signal);
          setForward(latest);
        } catch {
          setForward(null);
        }
        try {
          setForwardList(await listForwardBatches(20, controller.signal));
        } catch {
          setForwardList([]);
        }
        try {
          setCycleStatus(await getResearchCycleStatus(controller.signal));
          setCycleError(null);
        } catch (reason: unknown) {
          setCycleStatus(null);
          if (!(reason instanceof DOMException && reason.name === "AbortError")) {
            setCycleError(errorMessage(reason));
          }
        }
      } catch (reason: unknown) {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      }
    })();
    return () => controller.abort();
  }, []);

  const portfolioA = useMemo(
    () => (bundles ? pickPortfolioA(bundles.map((b) => b.summary)) : undefined),
    [bundles],
  );
  const portfolioB = useMemo(
    () => (bundles ? pickPortfolioB(bundles.map((b) => b.summary)) : undefined),
    [bundles],
  );
  const bundleA = bundles?.find((b) => b.summary.id === portfolioA?.id);
  const bundleB = bundles?.find((b) => b.summary.id === portfolioB?.id);
  const primary = bundleA ?? bundles?.[0];
  const ageDays = experimentAgeDays(overview?.activated_at);
  const maturity = experimentMaturity(ageDays);

  const selectedTickers = useMemo(() => {
    const set = new Set<string>();
    for (const o of primary?.orders ?? []) set.add(o.ticker);
    return set;
  }, [primary]);

  const rankedPreds = useMemo(() => {
    const preds = [...(forward?.predictions ?? [])];
    preds.sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));
    return preds;
  }, [forward]);

  const visiblePreds = showAllPreds ? rankedPreds : rankedPreds.slice(0, 10);
  const targetByTicker = useMemo(() => {
    const m = new Map<string, number>();
    for (const o of primary?.orders ?? []) {
      if (o.target_weight != null) m.set(o.ticker, o.target_weight);
    }
    return m;
  }, [primary]);
  const nameByTicker = useMemo(() => {
    const m = new Map<string, string>();
    for (const o of primary?.orders ?? []) {
      if (o.display_name) m.set(o.ticker, o.display_name);
    }
    return m;
  }, [primary]);

  if (error) return <PageState kind="error">{error}</PageState>;
  if (!overview || bundles == null) {
    return <PageState kind="loading" title="Загрузка живого эксперимента…" />;
  }
  if (!bundles.length) {
    return (
      <section>
        <PageHeader
          title={labels.nav.liveExperiment}
          description="Проспективное наблюдение за решениями ProjectAI"
          helpPageId="shadow"
        />
        <PageState kind="empty">
          Shadow-портфели ещё не инициализированы. Сначала выполните init через CLI/API.
        </PageState>
      </section>
    );
  }

  const status = primary?.summary.status;
  const pendingTotal = bundles.reduce((s, b) => s + b.summary.pending_orders, 0);
  const fillsTotal = bundles.reduce((s, b) => s + b.summary.fills, 0);
  const latestMarket =
    primary?.summary.last_processed_market_date ??
    forward?.batch.as_of_date ??
    null;
  const hasNavHistory = bundles.some((b) => b.nav.length > 0);

  return (
    <section className="shadow-page">
      <PageHeader
        title={labels.nav.liveExperiment}
        description="Проспективное наблюдение за решениями ProjectAI на данных, которые появились после запуска эксперимента."
        helpPageId="shadow"
        actions={
          <Link to="/simulator" className="secondary button-link">
            Исторический симулятор
          </Link>
        }
      />

      <div className="shadow-header-meta">
        <StatusChip status={status} />
        <span className="sim-meta-chip">
          Запуск: {formatDateTime(overview.activated_at)}
        </span>
        <span className="sim-meta-chip">
          Возраст: {experimentAgeLabel(ageDays)} <MetricHelp metricId="experiment_age" />
        </span>
        <span className="sim-meta-chip">
          Последний сигнал: {formatDate(forward?.batch.as_of_date)}{" "}
          <MetricHelp metricId="signal_as_of" />
        </span>
        <span className="sim-meta-chip">
          Рыночные данные: {formatDate(latestMarket)} <MetricHelp metricId="market_watermark" />
        </span>
      </div>

      <ResearchCycleOpsStrip status={cycleStatus} error={cycleError} />

      <div className="shadow-note panel">
        <p>
          В отличие от исторического симулятора, этот эксперимент не пересчитывает прошлое. Прогнозы,
          решения и исполнения фиксируются только после их фактического появления.{" "}
          <MetricHelp metricId="prospective_experiment" />
        </p>
      </div>

      <div className="card-grid sim-metrics-grid">
        <MetricCard label="Запущен" value={formatDate(overview.activated_at)} helpId="activation_date" />
        <MetricCard
          label="Последний сигнал"
          value={formatDate(forward?.batch.as_of_date)}
          hint={forward ? `сформирован ${formatDateTime(forward.batch.generated_at)}` : undefined}
          helpId="forward_signal"
        />
        <MetricCard label="Последняя рыночная дата" value={formatDate(latestMarket)} helpId="market_watermark" />
        <MetricCard
          label="Инструментов в сигнале"
          value={forward?.batch.eligible_count ?? "—"}
        />
        <MetricCard label="Ожидающих ордеров" value={pendingTotal} helpId="pending_order" />
        <MetricCard label="Исполненных сделок" value={fillsTotal} />
        <MetricCard
          label="Возраст эксперимента"
          value={experimentAgeLabel(ageDays)}
          hint={maturity.label}
          helpId="experiment_age"
        />
      </div>

      <OperationalStage status={status} />

      {fillsTotal === 0 ? <PendingZeroState pendingCount={pendingTotal} /> : null}

      <div className="panel">
        <h2 className="sim-section-title">
          Последний прогноз модели <MetricHelp metricId="forward_signal" />
        </h2>
        {forward ? (
          <>
            <dl className="sim-dl">
              <div>
                <dt>Дата рыночных данных</dt>
                <dd>{formatDate(forward.batch.as_of_date)}</dd>
              </div>
              <div>
                <dt>Прогноз сформирован</dt>
                <dd>{formatDateTime(forward.batch.generated_at)}</dd>
              </div>
              <div>
                <dt>Модель</dt>
                <dd>
                  Prediction Candidate V0{" "}
                  <code title={forward.batch.candidate_config_hash}>
                    {shortHash(forward.batch.candidate_config_hash)}
                  </code>
                </dd>
              </div>
              <div>
                <dt>Инструментов</dt>
                <dd>{forward.batch.eligible_count}</dd>
              </div>
              <div>
                <dt>PIT</dt>
                <dd>{forward.batch.pit_status}</dd>
              </div>
              <div>
                <dt>Prediction hash</dt>
                <dd>
                  <code title={forward.batch.prediction_hash ?? undefined}>
                    {shortHash(forward.batch.prediction_hash)}
                  </code>
                </dd>
              </div>
            </dl>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>Ticker</th>
                    <th>Name</th>
                    <th className="numeric">Predicted Return 20d</th>
                    <th>Selected</th>
                    <th className="numeric">Target weight</th>
                  </tr>
                </thead>
                <tbody>
                  {visiblePreds.map((pred: ForwardPredictionItem) => {
                    const selected = selectedTickers.has(pred.ticker);
                    return (
                      <tr key={`${pred.instrument_id}-${pred.rank}`}>
                        <td>{pred.rank ?? "—"}</td>
                        <td>{pred.ticker}</td>
                        <td>{nameByTicker.get(pred.ticker) ?? "—"}</td>
                        <td className="numeric">{formatSignedPrediction(pred.predicted_return_20d)}</td>
                        <td>
                          {selected ? <span className="shadow-badge">Ордер создан</span> : "—"}
                        </td>
                        <td className="numeric">
                          {selected && targetByTicker.has(pred.ticker)
                            ? formatPercent(targetByTicker.get(pred.ticker))
                            : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {rankedPreds.length > 10 ? (
              <button
                type="button"
                className="secondary"
                onClick={() => setShowAllPreds((v) => !v)}
              >
                {showAllPreds ? "Показать Top 10" : `Показать все ${rankedPreds.length}`}
              </button>
            ) : null}
          </>
        ) : (
          <PageState kind="empty">Нет завершённого Forward Signal batch.</PageState>
        )}
      </div>

      <div className="panel">
        <h2 className="sim-section-title">Сравнение портфелей</h2>
        <div className="shadow-compare-grid">
          {bundleA ? <PortfolioCard bundle={bundleA} letter="A" /> : null}
          {bundleB ? <PortfolioCard bundle={bundleB} letter="B" /> : null}
        </div>
      </div>

      <div className="panel">
        <h2 className="sim-section-title">
          Ожидающие ордера <MetricHelp metricId="pending_order" />
        </h2>
        {primary && primary.orders.filter((o) => o.status === "PENDING").length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Action</th>
                  <th className="numeric">Prediction</th>
                  <th>Rank</th>
                  <th className="numeric">Target weight</th>
                  <th>Created</th>
                  <th>Earliest execution</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {primary.orders
                  .filter((o) => o.status === "PENDING")
                  .map((order) => (
                    <tr
                      key={order.id}
                      className="clickable"
                      onClick={() =>
                        setSelectedOrder({
                          order,
                          portfolioName: primary.summary.policy_name,
                          riskName: primary.summary.risk_name,
                        })
                      }
                    >
                      <td>{order.ticker}</td>
                      <td>{orderActionLabel(order.side, order.status)}</td>
                      <td className="numeric">{formatSignedPrediction(order.predicted_return_20d)}</td>
                      <td>
                        {order.rank != null && order.eligible_count != null
                          ? `${order.rank} / ${order.eligible_count}`
                          : (order.rank ?? "—")}
                      </td>
                      <td className="numeric">{formatPercent(order.target_weight)}</td>
                      <td>{formatDateTime(order.decision_at)}</td>
                      <td>{formatDate(order.min_execution_date)}</td>
                      <td>{order.status}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">Нет ожидающих ордеров.</p>
        )}
        {selectedOrder ? (
          <DecisionExplanationPanel
            title="Почему принято это решение?"
            context={contextFromShadowOrder(selectedOrder.order, {
              policyName: selectedOrder.portfolioName,
              riskPolicyName: selectedOrder.riskName,
              predictionCandidate: "prediction_ml_candidate/v0",
              candidateConfigHash: forward?.batch.candidate_config_hash,
              predictionHash: forward?.batch.prediction_hash,
            })}
            onClose={() => setSelectedOrder(null)}
          />
        ) : null}
      </div>

      {hasNavHistory ? (
        <div className="panel">
          <h2 className="sim-section-title">История NAV</h2>
          <p className="muted">Появится график A / B / IMOEX, когда будут реальные NAV-точки.</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Портфель</th>
                  <th className="numeric">NAV</th>
                  <th className="numeric">Cash</th>
                  <th className="numeric">DD</th>
                </tr>
              </thead>
              <tbody>
                {bundles.flatMap((b) =>
                  b.nav.map((n) => (
                    <tr key={`${b.summary.id}-${n.as_of_date}`}>
                      <td>{formatDate(n.as_of_date)}</td>
                      <td>{portfolioHumanName(b.summary.name)}</td>
                      <td className="numeric">{formatMoney(n.nav)}</td>
                      <td className="numeric">{formatMoney(n.cash)}</td>
                      <td className="numeric">{formatPercent(n.drawdown)}</td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <EmptyNavHistory />
      )}

      <div className="panel">
        <h2 className="sim-section-title">Недельные решения</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ISO week</th>
                <th>Forward batch</th>
                <th>Decision date</th>
                <th>Selected</th>
                <th>Policy</th>
                <th>Risk state</th>
              </tr>
            </thead>
            <tbody>
              {(primary?.decisions ?? []).map((d) => (
                <tr key={d.id}>
                  <td>{d.iso_week}</td>
                  <td>{d.forward_batch_id}</td>
                  <td>{formatDateTime(d.decision_at)}</td>
                  <td>{Array.isArray(d.targets) ? d.targets.length : "—"}</td>
                  <td>{d.policy_name ?? "—"}</td>
                  <td>{riskModeLabel(d.risk_mode)}</td>
                </tr>
              ))}
              {!primary?.decisions.length ? (
                <tr>
                  <td colSpan={6}>Пока нет решений</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <h2 className="sim-section-title">История Forward Signal</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Batch</th>
                <th>as_of</th>
                <th>generated_at</th>
                <th>eligible</th>
                <th>hash</th>
                <th>status</th>
              </tr>
            </thead>
            <tbody>
              {forwardList.map((b) => (
                <tr key={b.id}>
                  <td>{b.id}</td>
                  <td>{formatDate(b.as_of_date)}</td>
                  <td>{formatDateTime(b.generated_at)}</td>
                  <td>{b.eligible_count}</td>
                  <td>
                    <code title={b.prediction_hash ?? undefined}>{shortHash(b.prediction_hash)}</code>
                  </td>
                  <td>{b.status}</td>
                </tr>
              ))}
              {!forwardList.length ? (
                <tr>
                  <td colSpan={6}>Нет batch</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <h2 className="sim-section-title">Исполнения (fills)</h2>
        {fillsTotal === 0 ? (
          <p className="muted">Исполнений пока нет — это ожидаемо до первого будущего OPEN.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Ticker</th>
                  <th>Side</th>
                  <th className="numeric">Qty</th>
                  <th className="numeric">OPEN</th>
                  <th className="numeric">Fill</th>
                </tr>
              </thead>
              <tbody>
                {bundles.flatMap((b) =>
                  b.fills.map((f) => (
                    <tr key={`${b.summary.id}-${f.id}`}>
                      <td>{formatDate(f.execution_date)}</td>
                      <td>{f.ticker}</td>
                      <td>{f.side}</td>
                      <td className="numeric">{f.quantity}</td>
                      <td className="numeric">{f.raw_open}</td>
                      <td className="numeric">{f.fill_price}</td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel">
        <h2 className="sim-section-title">Технический статус</h2>
        <dl className="sim-dl">
          <div>
            <dt>Experiment group</dt>
            <dd>
              <code>{overview.experiment_group ?? "—"}</code>
            </dd>
          </div>
          <div>
            <dt>Автоматическое ежедневное обновление</dt>
            <dd>
              {cycleStatus
                ? formatAutomaticSchedule(cycleStatus.automatic_schedule, cycleStatus.schedule)
                : overview.automatic_schedule === "not_configured"
                  ? "не настроено"
                  : (overview.automatic_schedule ?? "не настроено")}
            </dd>
          </div>
          <div>
            <dt>Зрелость эксперимента</dt>
            <dd>
              {maturity.label}
              <br />
              <span className="muted">{maturity.hint}</span>
            </dd>
          </div>
          <div>
            <dt>Доходность / Sharpe</dt>
            <dd>Недостаточно данных</dd>
          </div>
        </dl>
        <p className="muted">
          Операторские команды (Forward run / Shadow advance) остаются в CLI. На дашборде — только
          чтение.
        </p>
      </div>
    </section>
  );
}

function formatSignedPrediction(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  const pct = value * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toLocaleString("ru-RU", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}%`;
}
