import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  getLatestForwardBatch,
  listForwardBatches,
  type ForwardBatchDetail,
  type ForwardBatchSummary,
  type ForwardPredictionItem,
} from "../api/forward";
import { getIntradayStatus, type IntradayMarketStatus } from "../api/intraday";
import {
  getResearchCycleStatus,
  type ResearchCycleOperationalStatus,
} from "../api/researchCycle";
import {
  getShadowDailyOperations,
  getShadowDecisions,
  getShadowFills,
  getShadowLive,
  getShadowNav,
  getShadowOrders,
  getShadowOverview,
  type ShadowDailyOperations,
  type ShadowDecision,
  type ShadowFill,
  type ShadowLiveResponse,
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
  AutomationWarningBanner,
  CashCard,
  DailyLifecycleStrip,
  EmptyNavHistory,
  LivePortfolioTable,
  NextSessionPanel,
  OperationalStage,
  PendingOrdersTable,
  PendingReasonsList,
  PendingZeroState,
  PnLCards,
  SkippedReasonsList,
  TodaySessionPanel,
} from "../features/shadow/components";
import {
  deriveLiveExperimentStatus,
  experimentAgeDays,
  experimentAgeLabel,
  experimentMaturity,
  hasFewObservations,
  isCalmMarketClosedStatus,
  liveExperimentStatusLabel,
  liveExperimentStatusTone,
  orderActionLabel,
  partitionShadowPortfolios,
  pickPortfolioA,
  pickPortfolioB,
  portfolioHumanName,
  portfolioHumanSubtitle,
  riskModeLabel,
  shadowStatusLabel,
  shadowStatusTone,
  shortHash,
  type LiveExperimentUiStatus,
} from "../features/shadow/helpers";
import { MetricHelp } from "../help";
import { usePolling } from "../hooks/usePolling";
import {
  formatDate,
  formatDateTime,
  formatMoney,
  formatPercent,
  formatPrice,
  formatRelativeTime,
} from "../utils/format";
import { labels } from "../utils/labels";

const LIVE_POLL_MS = 45_000;

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

function LiveStatusChip({ status }: { status: LiveExperimentUiStatus }) {
  return (
    <span
      className={`badge badge-${liveExperimentStatusTone(status)}`}
      data-testid="shadow-live-status"
    >
      {liveExperimentStatusLabel(status)}
    </span>
  );
}

function PortfolioCard({
  bundle,
  letter,
  liveSummary,
}: {
  bundle: PortfolioBundle;
  letter: "A" | "B";
  liveSummary?: ShadowPortfolioSummary | null;
}) {
  const p = liveSummary ?? bundle.summary;
  const isB = letter === "B";
  const liveNav = p.live_nav ?? p.live?.nav;
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
          <dt>
            NAV <MetricHelp metricId="live_portfolio_nav" />
          </dt>
          <dd>{formatMoney(liveNav ?? p.nav ?? p.cash)}</dd>
        </div>
        <div>
          <dt>Cash</dt>
          <dd>{formatMoney(p.live?.cash ?? p.cash)}</dd>
        </div>
        <div>
          <dt>Рыночная стоимость</dt>
          <dd>{formatMoney(p.live_market_value ?? p.live?.market_value ?? p.market_value ?? 0)}</dd>
        </div>
        <div>
          <dt>Позиции</dt>
          <dd>{p.live?.positions?.length ?? p.position_count ?? 0}</dd>
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
        {p.experiment_group ? (
          <>
            {" "}
            · <code>{p.experiment_group}</code>
          </>
        ) : null}
      </p>
    </article>
  );
}

export function ShadowPage() {
  const [overview, setOverview] = useState<ShadowOverview | null>(null);
  const [live, setLive] = useState<ShadowLiveResponse | null>(null);
  const [ops, setOps] = useState<ShadowDailyOperations | null>(null);
  const [opsError, setOpsError] = useState<string | null>(null);
  const [intradayStatus, setIntradayStatus] = useState<IntradayMarketStatus | null>(null);
  const [bundles, setBundles] = useState<PortfolioBundle[] | null>(null);
  const [forward, setForward] = useState<ForwardBatchDetail | null>(null);
  const [forwardList, setForwardList] = useState<ForwardBatchSummary[]>([]);
  const [cycleStatus, setCycleStatus] = useState<ResearchCycleOperationalStatus | null>(null);
  const [cycleError, setCycleError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [lastUiUpdateAt, setLastUiUpdateAt] = useState<string | null>(null);
  const [showAllPreds, setShowAllPreds] = useState(false);
  const [showResearchDetails, setShowResearchDetails] = useState(false);
  const [armTab, setArmTab] = useState<string | null>(null);
  const [selectedOrder, setSelectedOrder] = useState<{
    order: ShadowOrder;
    portfolioName: string;
    riskName: string;
  } | null>(null);

  const refreshLive = useCallback(async (signal?: AbortSignal) => {
    try {
      const [liveResp, intraday, dailyOps] = await Promise.all([
        getShadowLive(signal),
        getIntradayStatus(signal).catch(() => null),
        getShadowDailyOperations(signal).catch((reason: unknown) => {
          if (!(reason instanceof DOMException && reason.name === "AbortError")) {
            setOpsError(errorMessage(reason));
          }
          return null;
        }),
      ]);
      setLive(liveResp);
      if (intraday) setIntradayStatus(intraday);
      if (dailyOps) {
        setOps(dailyOps);
        setOpsError(null);
      }
      setLiveError(null);
      setLastUiUpdateAt(new Date().toISOString());
    } catch (reason: unknown) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setLiveError(errorMessage(reason));
      }
    }
  }, []);

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
        await refreshLive(controller.signal);
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
  }, [refreshLive]);

  usePolling(() => refreshLive(), LIVE_POLL_MS, Boolean(overview && bundles && bundles.length > 0));

  const liveById = useMemo(() => {
    const m = new Map<string, ShadowPortfolioSummary>();
    for (const p of live?.portfolios ?? []) m.set(String(p.id), p);
    return m;
  }, [live]);

  const partitioned = useMemo(() => {
    const summaries = (bundles ?? []).map((b) => liveById.get(String(b.summary.id)) ?? b.summary);
    return partitionShadowPortfolios(summaries);
  }, [bundles, liveById]);

  const primaryArmSummaries = partitioned.primary;
  const legacyArmSummaries = partitioned.legacy;

  useEffect(() => {
    if (!primaryArmSummaries.length) return;
    if (armTab && primaryArmSummaries.some((p) => String(p.id) === armTab)) return;
    const preferred = pickPortfolioA(primaryArmSummaries) ?? primaryArmSummaries[0];
    setArmTab(String(preferred.id));
  }, [primaryArmSummaries, armTab]);

  const activeSummary =
    primaryArmSummaries.find((p) => String(p.id) === armTab) ??
    pickPortfolioA(primaryArmSummaries) ??
    primaryArmSummaries[0] ??
    null;

  const activeBundle = bundles?.find((b) => b.summary.id === activeSummary?.id);
  const primaryLive = activeSummary;

  const portfolioA = useMemo(
    () => (bundles ? pickPortfolioA(primaryArmSummaries.length ? primaryArmSummaries : bundles.map((b) => b.summary)) : undefined),
    [bundles, primaryArmSummaries],
  );
  const portfolioB = useMemo(
    () => (bundles ? pickPortfolioB(primaryArmSummaries.length ? primaryArmSummaries : bundles.map((b) => b.summary)) : undefined),
    [bundles, primaryArmSummaries],
  );
  const bundleA = bundles?.find((b) => b.summary.id === portfolioA?.id);
  const bundleB = bundles?.find((b) => b.summary.id === portfolioB?.id);

  const ageDays = experimentAgeDays(
    activeSummary?.activated_at ?? overview?.activated_at,
  );
  const maturity = experimentMaturity(ageDays);
  const fewObs = hasFewObservations(ageDays);

  const uiStatus = deriveLiveExperimentStatus({
    live,
    primary: primaryLive,
    hasForward: Boolean(forward),
    loadError: Boolean(liveError && !live),
  });

  const selectedTickers = useMemo(() => {
    const set = new Set<string>();
    for (const o of activeBundle?.orders ?? []) set.add(o.ticker);
    return set;
  }, [activeBundle]);

  const rankedPreds = useMemo(() => {
    const preds = [...(forward?.predictions ?? [])];
    preds.sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));
    return preds;
  }, [forward]);

  const visiblePreds = showAllPreds ? rankedPreds : rankedPreds.slice(0, 10);
  const targetByTicker = useMemo(() => {
    const m = new Map<string, number>();
    for (const o of activeBundle?.orders ?? []) {
      if (o.target_weight != null) m.set(o.ticker, o.target_weight);
    }
    return m;
  }, [activeBundle]);
  const nameByTicker = useMemo(() => {
    const m = new Map<string, string>();
    for (const o of activeBundle?.orders ?? []) {
      if (o.display_name) m.set(o.ticker, o.display_name);
    }
    return m;
  }, [activeBundle]);

  if (error) return <PageState kind="error">{error}</PageState>;
  if (!overview || bundles == null) {
    return <PageState kind="loading" title="Загрузка живого эксперимента…" />;
  }
  if (!bundles.length) {
    return (
      <section className="shadow-page page-layout-wide" data-layout="wide">
        <PageHeader
          title="Живой эксперимент"
          description="проверяет решения на новых данных без реальных денег"
          helpPageId="shadow"
        />
        <p className="page-purpose">
          Это не брокерский портфель. Пустой список значит: shadow ещё не инициализирован операционно.
        </p>
        <PageState kind="empty">
          Shadow-портфели ещё не инициализированы. Сначала выполните init через CLI/API.
        </PageState>
      </section>
    );
  }

  const status = primaryLive?.status ?? activeBundle?.summary.status;
  const pendingTotal = bundles.reduce(
    (s, b) => s + (liveById.get(String(b.summary.id))?.pending_orders ?? b.summary.pending_orders),
    0,
  );
  const fillsTotal = bundles.reduce((s, b) => s + b.summary.fills, 0);
  const latestMarket =
    primaryLive?.last_processed_market_date ??
    activeBundle?.summary.last_processed_market_date ??
    forward?.batch.as_of_date ??
    null;
  const hasNavHistory = bundles.some((b) => b.nav.length > 0);
  const lastDecision = activeBundle?.decisions?.[0];
  const lastRefreshAt =
    live?.last_intraday_refresh?.at ??
    overview.intraday?.last_refresh?.at ??
    intradayStatus?.last_refresh?.at ??
    null;
  const livePositions = primaryLive?.live?.positions ?? [];
  const pendingReasons = primaryLive?.pending_order_reasons ?? [];
  const skipped = primaryLive?.skipped ?? primaryLive?.order_plan?.skipped ?? [];
  const calmClosed = isCalmMarketClosedStatus(uiStatus);
  const liveNav = primaryLive?.live_nav ?? primaryLive?.live?.nav;

  return (
    <section className="shadow-page page-layout-wide" data-layout="wide">
      <PageHeader
        title="Живой эксперимент"
        description="проверяет решения на новых данных без реальных денег"
        helpPageId="shadow"
        actions={
          <Link to="/simulator" className="secondary button-link">
            Исторический симулятор
          </Link>
        }
      />

      <div className="shadow-session-grid" data-testid="shadow-session-grid">
        <TodaySessionPanel
          ops={ops}
          error={opsError}
          primary={primaryLive}
          marketSession={
            pendingReasons.find((r) => r.market_status)?.market_status ??
            (uiStatus === "waiting_session" ? "CLOSED" : uiStatus === "positions_open" ? "OPEN" : null)
          }
        />
        <NextSessionPanel ops={ops} error={opsError} />
      </div>
      <AutomationWarningBanner ops={ops} />
      <DailyLifecycleStrip ops={ops} primary={primaryLive} />

      <div className="shadow-hero panel" data-testid="shadow-hero">
        <div className="shadow-hero-main">
          <LiveStatusChip status={uiStatus} />
          <p className="shadow-hero-copy">
            {uiStatus === "updates_disabled"
              ? "Внутридневные обновления выключены. Эксперимент жив, но живые котировки и исполнение на OPEN по этому контуру сейчас не опрашиваются."
              : uiStatus === "waiting_session"
                ? "Рынок закрыт или сессия ещё не началась — это обычная пауза, не ошибка. Ордера ждут допустимый OPEN."
                : uiStatus === "waiting_open_price"
                  ? "Сессия есть, но официальная цена открытия ещё не опубликована."
                  : uiStatus === "waiting_forward"
                    ? "Ждём новый Forward-сигнал или ещё нет завершённого прогноза."
                    : uiStatus === "positions_open"
                      ? "Есть открытые виртуальные позиции; оценка обновляется по живым котировкам."
                      : "Есть проблема со статусом эксперимента — проверьте операционный контур."}
          </p>
        </div>
        <div className="shadow-hero-meta">
          <span className="sim-meta-chip">
            Обновлено UI: {formatRelativeTime(lastUiUpdateAt)}
          </span>
          <span className="sim-meta-chip">
            Котировки: {formatRelativeTime(lastRefreshAt)}{" "}
            <MetricHelp metricId="intraday_market" />
          </span>
          <span className="sim-meta-chip">
            Запуск: {formatDateTime(activeSummary?.activated_at ?? overview.activated_at)}
          </span>
          <span className="sim-meta-chip">
            Возраст: {experimentAgeLabel(ageDays)} <MetricHelp metricId="experiment_age" />
          </span>
          {partitioned.hasV2 ? (
            <span className="sim-meta-chip" data-testid="shadow-experiment-v2">
              Realism V2
            </span>
          ) : null}
        </div>
        {fewObs ? (
          <p className="banner banner-warning" data-testid="shadow-few-observations">
            Мало наблюдений: возраст эксперимента {experimentAgeLabel(ageDays)}. Ранние результаты
            нельзя считать доказательством edge.
          </p>
        ) : null}
        {calmClosed ? (
          <p className="shadow-calm-note muted" data-testid="shadow-market-closed-calm">
            Когда биржа закрыта, страница остаётся спокойной: нет красной аварии, только ожидание
            следующей сессии.
          </p>
        ) : null}
        {liveError ? (
          <p className="banner banner-warning" data-testid="shadow-live-error">
            Живую оценку временно не удалось обновить: {liveError}
          </p>
        ) : null}
      </div>

      <div className="panel" data-testid="shadow-arms">
        <h2 className="sim-section-title">Плечи эксперимента</h2>
        <p className="muted">
          NAV и позиции по плечам разделены — не смешивайте их в одну цифру.
          {partitioned.hasV2 ? " Основной контур: Realism V2 (целые лоты)." : null}
        </p>
        <div className="tabs shadow-arm-tabs" role="tablist">
          {primaryArmSummaries.map((p, idx) => {
            const letter = p.name.includes("DD") ? "B" : idx === 0 ? "A" : String(idx + 1);
            const selected = String(p.id) === String(activeSummary?.id);
            return (
              <button
                key={p.id}
                type="button"
                role="tab"
                aria-selected={selected}
                className={selected ? "tab active" : "tab"}
                data-testid={`shadow-arm-tab-${p.id}`}
                onClick={() => setArmTab(String(p.id))}
              >
                {letter}: {portfolioHumanName(p.name)}
              </button>
            );
          })}
        </div>
        {activeSummary ? (
          <div className="shadow-arm-panel" data-testid="shadow-arm-panel">
            <header className="shadow-portfolio-card-head">
              <div>
                <h3 style={{ margin: "0.25rem 0" }}>{portfolioHumanName(activeSummary.name)}</h3>
                <p className="muted">{portfolioHumanSubtitle(activeSummary.name)}</p>
              </div>
              <StatusChip status={activeSummary.status} />
            </header>
            <div className="card-grid sim-metrics-grid">
              <MetricCard
                label="NAV сейчас"
                value={formatMoney(liveNav ?? activeSummary.nav)}
                helpId="live_portfolio_nav"
              />
              <MetricCard
                label="Позиций"
                value={livePositions.length || (activeSummary.position_count ?? 0)}
              />
              <MetricCard
                label="Покрытие котировок"
                value={
                  activeSummary.live?.quote_coverage == null
                    ? "—"
                    : formatPercent(activeSummary.live.quote_coverage)
                }
                helpId="quote_freshness"
              />
              <MetricCard
                label="Lot-aware"
                value={activeSummary.lot_aware ? "да" : "нет"}
                helpId="lot"
              />
            </div>
            <PnLCards portfolio={activeSummary} />
            <CashCard portfolio={activeSummary} />
            <h3 className="shadow-subheading">Позиции</h3>
            <LivePortfolioTable
              positions={livePositions}
              nav={liveNav ?? activeSummary.nav}
              quoteFallbackAt={lastRefreshAt}
            />
            <h3 className="shadow-subheading">
              Ожидающие ордера <MetricHelp metricId="pending_order" />
            </h3>
            <PendingOrdersTable
              orders={activeBundle?.orders ?? []}
              reasons={pendingReasons}
              onSelect={(order) =>
                setSelectedOrder({
                  order,
                  portfolioName: activeSummary.policy_name,
                  riskName: activeSummary.risk_name,
                })
              }
            />
            <h3 className="shadow-subheading">
              Пропуски плана <MetricHelp metricId="order_plan" />
            </h3>
            <SkippedReasonsList skipped={skipped} />
            <h3 className="shadow-subheading">Почему ордера ждут</h3>
            <PendingReasonsList reasons={pendingReasons} />
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
        ) : null}
      </div>

      {legacyArmSummaries.length ? (
        <div className="panel" data-testid="shadow-legacy-v1">
          <h2 className="sim-section-title">Legacy V1</h2>
          <p className="muted">
            Дробные Shadow-портфели прежнего эксперимента. Не смешивайте NAV с Realism V2.
          </p>
          <ul className="plain-list">
            {legacyArmSummaries.map((p) => (
              <li key={p.id}>
                <strong>{portfolioHumanName(p.name)}</strong>
                {" · "}
                NAV {formatMoney(p.live_nav ?? p.live?.nav ?? p.nav ?? p.cash)}
                {" · "}
                {shadowStatusLabel(p.status)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="shadow-primary-grid">
        <div className="panel" data-testid="shadow-decision-block">
          <h2 className="sim-section-title">Решение</h2>
          <dl className="sim-dl">
            <div>
              <dt>Последний Forward</dt>
              <dd>
                {forward
                  ? `${formatDate(forward.batch.as_of_date)} · ${formatDateTime(forward.batch.generated_at)}`
                  : "Нет завершённого Forward"}
              </dd>
            </div>
            <div>
              <dt>Последнее решение</dt>
              <dd>
                {lastDecision
                  ? `${lastDecision.iso_week} · ${formatDateTime(lastDecision.decision_at)}`
                  : "Пока нет решений"}
              </dd>
            </div>
            <div>
              <dt>Инструментов в сигнале</dt>
              <dd>{forward?.batch.eligible_count ?? "—"}</dd>
            </div>
            <div>
              <dt>Операционный статус</dt>
              <dd>
                <StatusChip status={status} />
              </dd>
            </div>
          </dl>
        </div>

        <div className="panel" data-testid="shadow-execution-block">
          <h2 className="sim-section-title">
            Исполнение <MetricHelp metricId="shadow_execution" />
          </h2>
          <dl className="sim-dl">
            <div>
              <dt>
                Сессия <MetricHelp metricId="market_session" />
              </dt>
              <dd>
                {labels.marketSession(
                  pendingReasons.find((r) => r.market_status)?.market_status ??
                    (uiStatus === "waiting_session" ? "CLOSED" : null),
                )}
              </dd>
            </div>
            <div>
              <dt>
                OPEN <MetricHelp metricId="session_open" />
              </dt>
              <dd>
                {pendingReasons.find((r) => r.open_price != null)?.open_price != null
                  ? formatPrice(pendingReasons.find((r) => r.open_price != null)?.open_price)
                  : uiStatus === "waiting_open_price"
                    ? "ещё не доступен"
                    : "—"}
              </dd>
            </div>
            <div>
              <dt>Последняя проверка котировок</dt>
              <dd>{formatRelativeTime(lastRefreshAt)}</dd>
            </div>
            <div>
              <dt>Политика</dt>
              <dd>
                <code>{live?.open_execution_policy ?? overview.intraday?.policy ?? "—"}</code>
              </dd>
            </div>
          </dl>
        </div>
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
        <MetricCard
          label="Запущен"
          value={formatDate(activeSummary?.activated_at ?? overview.activated_at)}
          helpId="activation_date"
        />
        <MetricCard
          label="Последний сигнал"
          value={formatDate(forward?.batch.as_of_date)}
          hint={forward ? `сформирован ${formatDateTime(forward.batch.generated_at)}` : undefined}
          helpId="forward_signal"
        />
        <MetricCard label="Последняя рыночная дата" value={formatDate(latestMarket)} helpId="market_watermark" />
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

      {bundles.every((b) => (b.summary.position_count ?? 0) === 0) && livePositions.length === 0 ? (
        <div className="shadow-zero panel" data-testid="shadow-zero-positions">
          <h2 className="sim-section-title">Позиций пока нет</h2>
          <p>
            Эксперимент живой, но открытых позиций сейчас 0. Это не выдуманный P&amp;L и не скрытая
            экспозиция — только то, что уже успело исполниться на будущих OPEN.
          </p>
          <ul className="plain-list">
            <li>Ожидающих ордеров: {pendingTotal}</li>
            <li>Исполненных сделок: {fillsTotal}</li>
            <li>
              Операционный статус: {shadowStatusLabel(status)}
              {pendingTotal > 0
                ? " — ордера сформированы и ждут допустимого будущего открытия рынка"
                : fillsTotal === 0
                  ? " — сделок ещё не было"
                  : " — после исполнений позиции могли быть закрыты или ещё не отражены"}
            </li>
          </ul>
        </div>
      ) : null}

      <div className="panel">
        <div className="shadow-details-toggle">
          <h2 className="sim-section-title" style={{ margin: 0 }}>
            Исследовательские детали
          </h2>
          <button
            type="button"
            className="secondary"
            onClick={() => setShowResearchDetails((v) => !v)}
          >
            {showResearchDetails ? "Скрыть" : "Показать"}
          </button>
        </div>
        {!showResearchDetails ? (
          <p className="muted">
            Прогноз модели, сравнение A/B, ордера, NAV-история и fills — вторичный слой; откройте при
            разборе research.
          </p>
        ) : null}
      </div>

      {showResearchDetails ? (
        <>
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
              {bundleA ? (
                <PortfolioCard
                  bundle={bundleA}
                  letter="A"
                  liveSummary={liveById.get(String(bundleA.summary.id))}
                />
              ) : null}
              {bundleB ? (
                <PortfolioCard
                  bundle={bundleB}
                  letter="B"
                  liveSummary={liveById.get(String(bundleB.summary.id))}
                />
              ) : null}
            </div>
          </div>

          <div className="panel">
            <h2 className="sim-section-title">
              Ожидающие ордера (детали) <MetricHelp metricId="pending_order" />
            </h2>
            {activeBundle && activeBundle.orders.filter((o) => o.status === "PENDING").length ? (
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
                    {activeBundle.orders
                      .filter((o) => o.status === "PENDING")
                      .map((order) => (
                        <tr
                          key={order.id}
                          className="clickable"
                          onClick={() =>
                            setSelectedOrder({
                              order,
                              portfolioName: activeBundle.summary.policy_name,
                              riskName: activeBundle.summary.risk_name,
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
                  {(activeBundle?.decisions ?? []).map((d) => (
                    <tr key={d.id}>
                      <td>{d.iso_week}</td>
                      <td>{d.forward_batch_id}</td>
                      <td>{formatDateTime(d.decision_at)}</td>
                      <td>{Array.isArray(d.targets) ? d.targets.length : "—"}</td>
                      <td>{d.policy_name ?? "—"}</td>
                      <td>{riskModeLabel(d.risk_mode)}</td>
                    </tr>
                  ))}
                  {!activeBundle?.decisions.length ? (
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
                  <code>
                    {activeSummary?.experiment_group ?? overview.experiment_group ?? "—"}
                  </code>
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
                <dt>Intraday</dt>
                <dd>
                  {live?.intraday_enabled || overview.intraday?.enabled
                    ? `включено · refresh ${intradayStatus?.refresh_minutes ?? overview.intraday?.refresh_minutes ?? "—"} мин`
                    : "выключено"}
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
        </>
      ) : null}
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
