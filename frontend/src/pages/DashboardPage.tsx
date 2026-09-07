import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  decideInvestment,
  getHurdle,
  previewPortfolioCandidate,
  type HurdleQuote,
  type InvestmentDecisionResponse,
  type PortfolioCandidate,
} from "../api/investment";
import { getMarketSummary, type MarketSummary } from "../api/market";
import { getShadowDailyOperations, getShadowLive, type ShadowDailyOperations, type ShadowLiveResponse } from "../api/shadow";
import { getSystemHealth, type HealthResponse } from "../api/system";
import { getWorkflows, type Workflow } from "../api/workflows";
import {
  AllocationBars,
  DataQualityCard,
  ExplanationCard,
  HeroCard,
  MetricCard,
  PageHeader,
  PageState,
  RiskCard,
  ServiceDot,
  StatusBadge,
  WarningCard,
} from "../components/Ui";
import {
  automationWarningText,
  mapNextSessionStage,
  nextSessionPrepCode,
  nextSessionStageTone,
  pickPortfolioA,
  todaySessionHeadline,
} from "../features/shadow/helpers";
import { isWorkflowActive, usePolling } from "../hooks/usePolling";
import { formatDate, formatDuration, formatMoney, formatNumber, formatRelativeTime } from "../utils/format";
import {
  DASHBOARD_SERVICES,
  overviewHealthBadgeStatus,
  overviewHealthTitle,
  resolveServiceStatus,
} from "../utils/health";
import { labels } from "../utils/labels";

interface DashboardData {
  health: HealthResponse;
  market: MarketSummary;
  workflows: Workflow[];
  hurdle: HurdleQuote | null;
  decision: InvestmentDecisionResponse | null;
  decisionError: string | null;
  candidate: PortfolioCandidate | null;
}

function pct(weight: number | undefined | null): string {
  if (weight == null) return "—";
  return `${(weight * 100).toFixed(0)}%`;
}

function VirtualPortfolioCard() {
  const [live, setLive] = useState<ShadowLiveResponse | null>(null);
  const [ops, setOps] = useState<ShadowDailyOperations | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getShadowLive(controller.signal),
      getShadowDailyOperations(controller.signal).catch(() => null),
    ])
      .then(([resp, dailyOps]) => {
        setLive(resp);
        setOps(dailyOps);
        setErr(null);
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setErr(errorMessage(reason));
        }
      });
    return () => controller.abort();
  }, []);

  const primary = live ? pickPortfolioA(live.portfolios) ?? live.portfolios[0] : null;
  const nav = primary?.live_nav ?? primary?.live?.nav ?? primary?.nav ?? primary?.cash;
  const cash = primary?.live?.cash ?? primary?.cash;
  const pnl =
    nav != null && primary?.initial_capital != null
      ? nav - primary.initial_capital
      : primary?.live?.unrealized_pnl;
  const positions = primary?.live?.positions?.length ?? primary?.position_count ?? 0;
  const quoteAge = live?.last_intraday_refresh?.at ?? null;
  const today = todaySessionHeadline(ops);
  const prep = nextSessionPrepCode(ops);
  const nextStage = mapNextSessionStage(prep);
  const nextTone = nextSessionStageTone(nextStage);
  const warning = automationWarningText(ops);
  const blocked = nextStage === "BLOCKED" || Boolean(warning);
  const cardTone = blocked ? (nextTone === "error" ? "error" : "warning") : nextTone === "success" ? "success" : "neutral";

  return (
    <article
      className={`panel shadow-live-card shadow-live-card-${cardTone}`}
      data-testid="dashboard-virtual-portfolio"
    >
      <h2 style={{ marginTop: 0 }}>Живой эксперимент</h2>
      {err ? (
        <p className="muted">Живая оценка временно недоступна.</p>
      ) : !live ? (
        <p className="muted">Загрузка…</p>
      ) : !primary ? (
        <p className="muted">Shadow ещё не инициализирован.</p>
      ) : (
        <>
          <p style={{ margin: "0.25rem 0" }} data-testid="dashboard-shadow-nav">
            NAV {formatMoney(nav)}
            {pnl == null ? "" : ` · P&L ${formatMoney(pnl)}`}
            {cash == null ? "" : ` · cash ${formatMoney(cash)}`}
            {` · позиций ${positions}`}
          </p>
          <p className="muted" data-testid="dashboard-shadow-today">
            Сегодня: {today.title}
          </p>
          <p className="muted" data-testid="dashboard-shadow-next">
            Следующая сессия:{" "}
            <span className={`badge badge-${nextTone}`}>{nextStage}</span>{" "}
            {labels.nextSessionStage(nextStage)}
          </p>
          {warning ? (
            <p className="banner banner-warning" data-testid="dashboard-automation-warning">
              {warning}
            </p>
          ) : null}
          <p className="muted">Котировки: {formatRelativeTime(quoteAge)}</p>
        </>
      )}
      <p style={{ marginBottom: 0 }}>
        <Link to="/shadow" data-testid="dashboard-shadow-cta">
          Открыть живой эксперимент →
        </Link>
      </p>
    </article>
  );
}

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [whyOpen, setWhyOpen] = useState(false);

  function load() {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([
      getSystemHealth(controller.signal),
      getMarketSummary(controller.signal),
      getWorkflows(controller.signal),
      getHurdle(controller.signal).catch(() => null),
      decideInvestment(
        { profile_id: "BALANCED_ALLOCATION_V0", capital: 100000 },
        controller.signal,
      ).catch((reason: unknown) => ({ __error: errorMessage(reason) })),
      previewPortfolioCandidate({ capital: 100000 }, controller.signal).catch(() => null),
    ])
      .then(([health, market, workflows, hurdle, decisionOrError, candidate]) => {
        const decisionError =
          decisionOrError && typeof decisionOrError === "object" && "__error" in decisionOrError
            ? String((decisionOrError as { __error: string }).__error)
            : null;
        const decision = decisionError
          ? null
          : (decisionOrError as InvestmentDecisionResponse);
        setData({
          health,
          market,
          workflows,
          hurdle,
          decision,
          decisionError,
          candidate: candidate as PortfolioCandidate | null,
        });
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }

  const silentRefresh = useCallback(async () => {
    const [health, market, workflows] = await Promise.all([
      getSystemHealth(),
      getMarketSummary(),
      getWorkflows(),
    ]);
    setData((prev) =>
      prev
        ? { ...prev, health, market, workflows }
        : {
            health,
            market,
            workflows,
            hurdle: null,
            decision: null,
            decisionError: null,
            candidate: null,
          },
    );
  }, []);

  useEffect(() => load(), []);

  const needsPoll = Boolean(data?.workflows.some((item) => isWorkflowActive(item.status)));
  usePolling(() => silentRefresh(), 10_000, needsPoll && !loading && !error);

  if (loading) return <PageState kind="loading" title="Загрузка обзора…" />;
  if (error || !data) {
    return (
      <PageState
        kind="error"
        title="Не удалось получить данные"
        action={
          <button type="button" onClick={() => load()}>
            {labels.actions.retry}
          </button>
        }
      >
        {error}
      </PageState>
    );
  }

  const recent = [...data.workflows]
    .sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""))
    .slice(0, 8);
  const decision = data.decision?.decision;
  const equityW = decision?.equity_weight ?? 0;
  const fiW = decision?.fixed_income_weight ?? 0;
  const cashW = decision?.cash_weight ?? 0;
  const risks = [
    ...(decision?.warnings ?? []),
    ...(data.decision?.bond_safety_reminder ? [data.decision.bond_safety_reminder] : []),
  ].slice(0, 4);

  return (
    <section>
      <PageHeader
        title={labels.nav.overview}
        description="За несколько секунд: что предлагает Kraken, почему и какие риски."
        helpPageId="overview"
      />

      <HeroCard
        eyebrow="Текущее решение"
        headline={
          decision
            ? "Kraken рекомендует исследовательское распределение"
            : "Решение пока недоступно"
        }
        actions={
          <>
            <button type="button" className="why-toggle" onClick={() => setWhyOpen((v) => !v)}>
              {whyOpen ? "Скрыть «Почему?»" : "Почему?"}
            </button>
            <Link className="why-toggle" to="/portfolio/candidate">
              Открыть состав
            </Link>
            <Link className="why-toggle" to="/investment-decision">
              Открыть решение
            </Link>
            <Link className="why-toggle" to="/portfolio-risk">
              Проверка риска
            </Link>
          </>
        }
      >
        {decision ? (
          <>
            <AllocationBars equity={equityW} fixedIncome={fiW} cash={cashW} />
            <p className="muted" style={{ margin: 0 }}>
              Акции {pct(equityW)} · Облигации {pct(fiW)} · Деньги {pct(cashW)}. Это research-кандидат
              на 100 000 ₽, не приказ брокеру.
            </p>
          </>
        ) : (
          <p className="muted" style={{ margin: 0 }}>
            {data.decisionError ??
              "Пока нет готового инвестиционного решения. Откройте раздел «Инвестиционное решение»."}
          </p>
        )}
        <div className="reveal-panel" hidden={!whyOpen}>
          <div className="level-stack">
            <ExplanationCard title="Простыми словами" level={1}>
              {decision?.explanations?.[0] ??
                "Kraken сравнивает возможности акций и облигаций с ключевой ставкой ЦБ и учитывает уверенность модели."}
            </ExplanationCard>
            <div className="card-grid">
              <MetricCard
                label="Ключевая ставка ЦБ"
                value={
                  data.hurdle?.annual_rate == null
                    ? "Нет данных"
                    : `${(data.hurdle.annual_rate * 100).toFixed(2)}%`
                }
                helpId="cbr_hurdle"
                hint="Порог сравнения, не «безрисковый депозит»."
              />
              <MetricCard
                label="Уверенность модели"
                value={data.decision?.equity_opportunity?.calibration_status ?? "UNKNOWN"}
                helpId="opportunity_confidence"
              />
              <MetricCard
                label="Статус решения"
                value={<StatusBadge status={decision?.status ?? "unknown"} />}
                helpId="investment_decision"
              />
            </div>
          </div>
        </div>
      </HeroCard>

      {data.candidate ? (
        <div className="ds-card ds-card-hero">
          <div className="ds-card-title">Кандидат портфеля</div>
          <div className="ds-card-headline">
            {data.candidate.summary?.positions_count ?? data.candidate.positions.length} позиций ·{" "}
            {data.candidate.as_of ?? "сейчас"} · {data.candidate.status}
          </div>
          <AllocationBars
            equity={data.candidate.allocation.equity.target_weight}
            fixedIncome={data.candidate.allocation.fixed_income.target_weight}
            cash={data.candidate.allocation.cash.target_weight}
          />
          <p className="muted">
            {(data.candidate.warnings || []).slice(0, 2).join(" ") ||
              data.candidate.readiness.banner_ru}
          </p>
          <div className="page-actions" style={{ marginTop: "0.75rem" }}>
            <Link className="why-toggle" to="/portfolio/candidate">
              Открыть состав
            </Link>
          </div>
        </div>
      ) : null}

      <VirtualPortfolioCard />

      <div className="card-grid">
        <RiskCard title="Риски прямо сейчас">
          {risks.length ? (
            <ul className="plain-list">
              {risks.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : (
            <p>Явных предупреждений в текущем решении нет — это не значит «без риска».</p>
          )}
        </RiskCard>
        <WarningCard title="Доверие к прогнозу">
          <p>
            {data.decision?.calibration.uncertainty_note ??
              "Без достаточного числа проверенных прогнозов Kraken не притворяется уверенным."}
          </p>
          <p>
            <Link to="/calibration">Смотреть качество прогнозов →</Link>
          </p>
        </WarningCard>
        <DataQualityCard title="Контекст рынка">
          <p>
            Ставка ЦБ:{" "}
            {data.hurdle?.annual_rate == null
              ? "нет данных"
              : `${(data.hurdle.annual_rate * 100).toFixed(2)}%`}
          </p>
          <p>Инструментов: {formatNumber(data.market.instruments_count)}</p>
          <p>Последние данные: {formatDate(data.market.last_successful_update ?? null)}</p>
          <p>Свежесть: {labels.dataFreshness(data.market.last_successful_update ?? null)}</p>
        </DataQualityCard>
      </div>

      <div className="hero-status">
        <div>
          <h2 style={{ margin: 0 }}>Kraken</h2>
          <p className="subtitle">{overviewHealthTitle(data.health)}</p>
        </div>
        <StatusBadge status={overviewHealthBadgeStatus(data.health)} />
      </div>

      <h2>Рыночные данные</h2>
      <div className="card-grid">
        <MetricCard label="Инструментов" value={formatNumber(data.market.instruments_count)} />
        <MetricCard label="Свечей" value={formatNumber(data.market.records_count)} />
        <MetricCard label="Рядов ЦБ" value={formatNumber(data.market.series_count ?? 0)} />
        <MetricCard
          label="Последние данные"
          value={formatDate(data.market.last_successful_update ?? null)}
        />
      </div>

      <h2>Сервисы</h2>
      <div className="card-grid">
        {DASHBOARD_SERVICES.map((service) => (
          <article className="metric-card" key={service}>
            <span className="metric-label">{labels.service(service)}</span>
            <ServiceDot status={resolveServiceStatus(data.health.services, service)} />
          </article>
        ))}
      </div>

      <h2>Недавние процессы</h2>
      <div className="card">
        {recent.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Процесс</th>
                  <th>Статус</th>
                  <th>Начало</th>
                  <th>Длительность</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <Link to="/workflows">{labels.workflowType(item.workflow_type)}</Link>
                    </td>
                    <td>
                      <StatusBadge status={item.status} />
                    </td>
                    <td>{formatDate(item.started_at)}</td>
                    <td>{formatDuration(item.duration_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">Пока нет завершённых процессов — это нормально для тихого окна.</p>
        )}
      </div>
    </section>
  );
}
