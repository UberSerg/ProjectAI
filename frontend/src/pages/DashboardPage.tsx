import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import { getDailyPersonalDecision, type DailyPersonalDecision } from "../api/dailyPersonalDecision";
import { getHurdle, type HurdleQuote } from "../api/investment";
import {
  getPrimaryAnalysis,
  type ManualPortfolioAnalysis,
} from "../api/manualPortfolios";
import { getPortfolioRelationsMatrix } from "../api/relations";
import { getShadowLive, type ShadowLiveResponse } from "../api/shadow";
import { getPersonalPrimary, type PersonalSummary } from "../api/personalPortfolios";
import { getSystemHealth, type HealthResponse } from "../api/system";
import { getWorkflows, type Workflow } from "../api/workflows";
import { PageState, StatusBadge } from "../components/Ui";
import {
  ActionCards,
  AllocationDonut,
  CockpitSection,
  PerformancePanel,
  RelationsPreview,
} from "../features/dashboard/DashboardSections";
import {
  allocationFromAnalysis,
  topConcentration,
  unrealizedPnl,
} from "../features/dashboard/allocation";
import { dailyDecisionToActionCards } from "../features/dashboard/dailyDecisionCards";
import { pickPortfolioA } from "../features/shadow/helpers";
import { qualityLabel } from "../features/manualPortfolio/labels";
import { useKrakenRole } from "../role/KrakenRoleContext";
import { formatDate, formatDuration, formatMoney, formatRelativeTime } from "../utils/format";
import { overviewHealthBadgeStatus, overviewHealthTitle } from "../utils/health";
import { labels } from "../utils/labels";

interface CockpitData {
  analysis: ManualPortfolioAnalysis | null;
  analysisError: string | null;
  dailyDecision: DailyPersonalDecision | null;
  dailyDecisionError: string | null;
  hurdle: HurdleQuote | null;
  health: HealthResponse;
  workflows: Workflow[];
  shadow: ShadowLiveResponse | null;
  personal: PersonalSummary | null;
}

/** Backend may return coverage as 0..1 or 0..100. */
function formatCoveragePct(coverage: number | null | undefined): string {
  if (coverage == null || Number.isNaN(coverage)) return "—";
  const pct = coverage <= 1.0001 ? coverage * 100 : coverage;
  return `${pct.toFixed(0)}%`;
}

function shortIssuer(label: string, max = 28): string {
  const t = label.trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

function heroAdvisoryNote(raw: string | undefined, hurdleRate: number | null | undefined): string {
  const parts: string[] = [];
  if (raw && !/risk findings are advisory/i.test(raw)) {
    parts.push(raw);
  } else {
    parts.push("Оценка справочная: котировки где доступны, без исполнения сделок.");
  }
  if (hurdleRate != null) {
    parts.push(`Ключевая ставка ЦБ: ${(hurdleRate * 100).toFixed(2)}%.`);
  }
  return parts.join(" ");
}

function shadowStatusRu(status: string | undefined): string {
  if (!status) return "—";
  const map: Record<string, string> = {
    ACTIVE: "Активен",
    WAITING_FOR_FUTURE_MARKET_OPEN: "Ждёт открытия рынка",
    WAITING_FOR_NEW_MARKET: "Ждёт новые данные",
  };
  return map[status] ?? labels.status(status.toLowerCase()) ?? status;
}

export function DashboardPage() {
  const [data, setData] = useState<CockpitData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [relLoading, setRelLoading] = useState(false);
  const [relError, setRelError] = useState<string | null>(null);
  const [relSummary, setRelSummary] = useState<{
    pairCount: number;
    available: number;
    avgAbs: number | null;
    strongest: string | null;
  } | null>(null);

  const load = useCallback(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([
      getPrimaryAnalysis(controller.signal).catch((reason: unknown) => ({
        __error: errorMessage(reason),
      })),
      getDailyPersonalDecision({ signal: controller.signal }).catch((reason: unknown) => ({
        __error: errorMessage(reason),
      })),
      getHurdle(controller.signal).catch(() => null),
      getSystemHealth(controller.signal).catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") throw reason;
        throw reason;
      }),
      getWorkflows(controller.signal).catch(() => [] as Workflow[]),
      getShadowLive(controller.signal).catch(() => null),
      getPersonalPrimary({ signal: controller.signal }).catch(() => null),
    ])
      .then(([analysisOrErr, dailyOrErr, hurdle, health, workflows, shadow, personal]) => {
          if (controller.signal.aborted) return;
          const analysisError =
            analysisOrErr && typeof analysisOrErr === "object" && "__error" in analysisOrErr
              ? String((analysisOrErr as { __error: string }).__error)
              : null;
          const analysis = analysisError
            ? null
            : (analysisOrErr as ManualPortfolioAnalysis);
          const dailyDecisionError =
            dailyOrErr && typeof dailyOrErr === "object" && "__error" in dailyOrErr
              ? String((dailyOrErr as { __error: string }).__error)
              : null;
          const dailyDecision = dailyDecisionError
            ? null
            : (dailyOrErr as DailyPersonalDecision);
          setData({
            analysis,
            analysisError,
            dailyDecision,
            dailyDecisionError,
            hurdle: hurdle as HurdleQuote | null,
            health: health as HealthResponse,
            workflows: workflows as Workflow[],
            shadow: shadow as ShadowLiveResponse | null,
            personal: personal as PersonalSummary | null,
          });
          setLoading(false);
        })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(errorMessage(reason));
        setLoading(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const abort = load();
    return abort;
  }, [load]);

  const symbols = useMemo(() => {
    // Same book as Personal Portfolio — prefer personal holdings for «Ваш портфель» relations.
    const fromPersonal = (data?.personal?.positions ?? [])
      .map((p) => p.secid)
      .filter((s): s is string => Boolean(s));
    if (fromPersonal.length) return fromPersonal.slice(0, 12);
    if (!data?.analysis) return [] as string[];
    return data.analysis.positions
      .map((p) => p.symbol)
      .filter(Boolean)
      .slice(0, 12);
  }, [data?.analysis, data?.personal?.positions]);

  const symbolKey = symbols.join(",");

  useEffect(() => {
    if (!symbols.length) {
      setRelSummary(null);
      setRelError(null);
      return;
    }
    const ctrl = new AbortController();
    setRelLoading(true);
    setRelError(null);
    getPortfolioRelationsMatrix({ symbols, window: 60 }, ctrl.signal)
      .then((m) => {
        const s = m.summary;
        const strong = s.strongest_positive;
        setRelSummary({
          pairCount: s.pair_count,
          available: s.available_pair_count,
          avgAbs: s.average_abs_correlation ?? null,
          strongest: strong
            ? `${strong.symbol_a}×${strong.symbol_b} (${strong.pearson.toFixed(2)})`
            : null,
        });
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) setRelError(errorMessage(err));
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setRelLoading(false);
      });
    return () => ctrl.abort();
  }, [symbolKey, symbols]);

  const { isUser } = useKrakenRole();

  if (loading) {
    return <PageState kind="loading" title="Загрузка личного кабинета Kraken…" />;
  }
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

  const analysis = data.analysis;
  const personal = data.personal;
  const journalState =
    personal?.portfolio.journal_state ??
    (personal?.portfolio.has_operations ? "ACTIVE" : personal ? "EMPTY" : null);
  // Single book: Personal summary for money metrics; analysis (same snapshot) for allocation/risk.
  const usePersonalMoney = personal != null;
  const personalActive = journalState === "ACTIVE" || Boolean(personal?.portfolio.has_operations);
  const emptyPortfolio = usePersonalMoney
    ? Number(personal!.summary.cash_rub) <= 0 &&
      (personal!.positions?.length ?? 0) === 0 &&
      journalState !== "LEGACY_PENDING"
    : Boolean(analysis) && analysis!.positions.length === 0 && analysis!.cash_rub <= 0;
  const weights = analysis
    ? allocationFromAnalysis(analysis)
    : { equity: 0, fixedIncome: 0, cash: 0 };
  const pnl = usePersonalMoney
    ? personal!.summary.investment_pnl_rub == null
      ? null
      : Number(personal!.summary.investment_pnl_rub)
    : analysis
      ? unrealizedPnl(analysis)
      : null;
  const securitiesValue = usePersonalMoney
    ? Number(personal!.summary.securities_value_rub)
    : analysis?.market_value_supported ?? null;
  const invested = securitiesValue;
  const nav = usePersonalMoney ? Number(personal!.summary.nav_rub) : analysis?.nav ?? null;
  const cash = usePersonalMoney ? Number(personal!.summary.cash_rub) : analysis?.cash_rub ?? null;
  const concentration = analysis ? topConcentration(analysis) : null;
  const cashShare =
    usePersonalMoney && nav != null && nav > 0 && cash != null
      ? cash / nav
      : analysis && analysis.nav > 0
        ? analysis.cash_rub / analysis.nav
        : null;
  const riskCount = analysis?.risk_findings?.length ?? 0;
  const coverage = analysis?.coverage_pct;

  const actions = dailyDecisionToActionCards(data.dailyDecision);

  const recent = [...data.workflows]
    .sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""))
    .slice(0, 6);

  const shadowPrimary = data.shadow
    ? pickPortfolioA(data.shadow.portfolios) ?? data.shadow.portfolios[0]
    : null;
  const shadowNav =
    shadowPrimary?.live_nav ?? shadowPrimary?.live?.nav ?? shadowPrimary?.nav ?? null;

  const deltaClass =
    pnl == null ? "flat" : pnl > 0 ? "up" : pnl < 0 ? "down" : "flat";

  return (
    <div className="cockpit" data-testid="kraken-cockpit">
      <header className="cockpit-topbar">
        <div>
          <p className="cockpit-kicker">
            Kraken · {isUser ? "личный кабинет" : "кабинет владельца"}
          </p>
          <h1 className="cockpit-title">Обзор портфеля</h1>
          <p className="cockpit-sub">
            Стоимость, структура, риски и предложения — по текущим данным.
          </p>
        </div>
        <div className="cockpit-health-quiet">
          {isUser ? (
            data.health.status !== "ok" ? (
              <p className="muted" data-testid="user-data-refresh-note">
                Данные обновляются
              </p>
            ) : (
              <p className="muted">Система в порядке</p>
            )
          ) : (
            <>
              <StatusBadge status={overviewHealthBadgeStatus(data.health)} />
              <p className="muted">{overviewHealthTitle(data.health)}</p>
            </>
          )}
        </div>
      </header>

      {/* 1. HERO */}
      <section className="cockpit-card cockpit-card-hero" data-testid="cockpit-hero">
        <p className="cockpit-hero-label">Стоимость портфеля</p>
        {data.analysisError ? (
          <div className="cockpit-empty">{data.analysisError}</div>
        ) : emptyPortfolio ? (
          <div>
            <p className="cockpit-hero-value">—</p>
            <p className="cockpit-hero-note">
              Добавьте первое пополнение или текущие позиции в «Мой портфель».
            </p>
            <div className="cockpit-footer-links">
              <Link className="button" to="/portfolio/mine">
                Открыть мой портфель
              </Link>
            </div>
          </div>
        ) : (
          <>
            <p className="cockpit-hero-value" data-testid="cockpit-nav">
              {formatMoney(nav)}
            </p>
            <div className={`cockpit-hero-delta ${deltaClass}`} data-testid="cockpit-pnl">
              {personalActive && personal!.summary.investment_pnl_rub == null ? (
                <span data-testid="cockpit-pnl-unavailable">
                  Результат недоступен — не хватает цены по части позиций
                </span>
              ) : pnl == null ? (
                <span>Результат: нет себестоимости для расчёта</span>
              ) : personalActive ? (
                <span data-testid="cockpit-investment-result">
                  Инвестиционный результат: {pnl >= 0 ? "+" : ""}
                  {formatMoney(pnl)}
                </span>
              ) : (
                <span>
                  {pnl >= 0 ? "+" : ""}
                  {formatMoney(pnl)}
                  {invested && invested > 0
                    ? ` · ${((pnl / invested) * 100).toFixed(1)}% к вложенному`
                    : ""}
                </span>
              )}
            </div>
            <div className="cockpit-metric-strip">
              <div className="cockpit-metric">
                <span className="cockpit-metric-label">Кэш</span>
                <span className="cockpit-metric-value">{formatMoney(cash)}</span>
              </div>
              <div className="cockpit-metric">
                <span className="cockpit-metric-label">
                  {personalActive ? "В бумагах" : "Вложено"}
                </span>
                <span className="cockpit-metric-value" data-testid="cockpit-securities-value">
                  {formatMoney(personalActive ? securitiesValue : invested)}
                </span>
              </div>
              <div className="cockpit-metric">
                <span className="cockpit-metric-label">Позиций</span>
                <span className="cockpit-metric-value">{analysis?.positions.length ?? 0}</span>
              </div>
              <div className="cockpit-metric">
                <span className="cockpit-metric-label">Качество цен</span>
                <span className="cockpit-metric-value" style={{ fontSize: "0.92rem" }}>
                  {qualityLabel(analysis?.quality)}
                  {coverage != null ? ` · ${formatCoveragePct(coverage)}` : ""}
                </span>
              </div>
            </div>
            <p className="cockpit-hero-note">
              {heroAdvisoryNote(analysis?.note, data.hurdle?.annual_rate)}
            </p>
          </>
        )}
      </section>

      {/* 2+3 Allocation + Performance */}
      <div className="cockpit-grid">
        <CockpitSection
          title="Структура активов"
          action={
            <Link className="cockpit-card-link" to="/portfolio/mine">
              Детали →
            </Link>
          }
        >
          {!analysis || emptyPortfolio ? (
            <div className="cockpit-empty">Нет позиций для распределения.</div>
          ) : (
            <AllocationDonut weights={weights} />
          )}
        </CockpitSection>

        <CockpitSection title="Динамика капитала">
          <PerformancePanel nav={emptyPortfolio ? null : nav} invested={invested} />
        </CockpitSection>
      </div>

      {/* 4+5 Risk + Relations */}
      <div className="cockpit-grid">
        <CockpitSection
          title="Здоровье портфеля"
          testId="cockpit-risk"
          action={
            <Link className="cockpit-card-link" to="/portfolio-risk">
              Риски →
            </Link>
          }
        >
          {!analysis || emptyPortfolio ? (
            <div className="cockpit-empty">Нет данных для сводки рисков.</div>
          ) : (
            <>
              <div className="cockpit-stat-grid">
                <div className="cockpit-stat">
                  <span>Доля кэша</span>
                  <strong>
                    {cashShare == null ? "—" : `${(cashShare * 100).toFixed(0)}%`}
                  </strong>
                </div>
                <div className="cockpit-stat">
                  <span>Концентрация</span>
                  <strong
                    title={
                      concentration
                        ? `${(concentration.weight * 100).toFixed(0)}% · ${concentration.label}`
                        : undefined
                    }
                  >
                    {concentration
                      ? `${(concentration.weight * 100).toFixed(0)}% · ${shortIssuer(concentration.label)}`
                      : "—"}
                  </strong>
                </div>
                <div className="cockpit-stat">
                  <span>Предупреждения</span>
                  <strong>{riskCount}</strong>
                </div>
                <div className="cockpit-stat">
                  <span>Покрытие цен</span>
                  <strong>{formatCoveragePct(coverage)}</strong>
                </div>
              </div>
              {analysis.risk_findings.slice(0, 3).length ? (
                <ul className="plain-list" style={{ marginTop: "0.75rem", marginBottom: 0 }}>
                  {analysis.risk_findings.slice(0, 3).map((f) => (
                    <li key={`${f.code}-${f.symbol ?? f.message}`}>{f.message}</li>
                  ))}
                </ul>
              ) : (
                <p className="cockpit-stat-note">
                  Явных предупреждений нет — это не гарантия отсутствия риска.
                </p>
              )}
            </>
          )}
        </CockpitSection>

        <CockpitSection title="Связи и диверсификация" testId="cockpit-relations-section">
          <RelationsPreview
            pairCount={relSummary?.pairCount ?? null}
            available={relSummary?.available ?? null}
            avgAbs={relSummary?.avgAbs ?? null}
            strongest={relSummary?.strongest ?? null}
            loading={relLoading}
            error={relError}
          />
        </CockpitSection>
      </div>

      {/* 6. Daily Personal Decision */}
      <CockpitSection
        title="Что делать сейчас"
        testId="cockpit-recommendations"
        action={
          <Link className="cockpit-card-link" to="/portfolio/mine?tab=decision">
            Подробнее →
          </Link>
        }
      >
        {data.dailyDecisionError && !actions.length ? (
          <div className="cockpit-empty" data-testid="daily-decision-error">
            Персональное решение временно недоступно. Остальной обзор портфеля работает.
          </div>
        ) : (
          <>
            {data.dailyDecision ? (
              <p className="muted" data-testid="daily-decision-status-line">
                {data.dailyDecision.headline}
                {data.dailyDecision.status === "PARTIAL" ? " · частичная оценка" : ""}
                {data.dailyDecision.status === "NO_ACTION" ? " · срочных действий нет" : ""}
              </p>
            ) : null}
            <p className="muted" data-testid="model-rec-disclaimer">
              {data.dailyDecision?.disclaimer ||
                "Модельная рекомендация по текущему личному портфелю — не приказ брокеру."}
            </p>
            <ActionCards cards={actions} />
          </>
        )}
      </CockpitSection>

      {/* 7. Recent activity — USER: simple; OWNER: journal + shadow */}
      {isUser ? (
        <CockpitSection title="Что произошло недавно" testId="cockpit-journal">
          {actions.length ? (
            <div className="cockpit-empty">
              Актуальные предложения Kraken — в блоке выше. История портфеля: раздел «История».
            </div>
          ) : (
            <div className="cockpit-empty">Пока нет заметных изменений в портфеле.</div>
          )}
        </CockpitSection>
      ) : (
        <div className="cockpit-grid">
          <CockpitSection
            title="Недавние события"
            testId="cockpit-journal"
            action={
              <Link className="cockpit-card-link" to="/workflows">
                Все процессы →
              </Link>
            }
          >
            {recent.length ? (
              <div className="cockpit-journal">
                {recent.map((item) => (
                  <div className="cockpit-journal-row" key={item.id}>
                    <span className="cockpit-journal-time">{formatDate(item.started_at)}</span>
                    <span>
                      <Link to="/workflows">{labels.workflowType(item.workflow_type)}</Link>
                      <span className="muted"> · {formatDuration(item.duration_seconds)}</span>
                    </span>
                    <StatusBadge status={item.status} />
                  </div>
                ))}
              </div>
            ) : (
              <div className="cockpit-empty">Пока нет зафиксированных процессов.</div>
            )}
          </CockpitSection>

          <CockpitSection title="Живой эксперимент" testId="dashboard-virtual-portfolio">
            {!shadowPrimary ? (
              <div className="cockpit-empty">Живой эксперимент ещё не запущен.</div>
            ) : (
              <>
                <div className="cockpit-stat-grid">
                  <div className="cockpit-stat">
                    <span>NAV эксперимента</span>
                    <strong data-testid="dashboard-shadow-nav">{formatMoney(shadowNav)}</strong>
                  </div>
                  <div className="cockpit-stat">
                    <span>Статус</span>
                    <strong style={{ fontSize: "0.9rem" }}>
                      {shadowStatusRu(shadowPrimary.status)}
                    </strong>
                  </div>
                </div>
                <p className="cockpit-stat-note">
                  Отдельный forward-эксперимент — не ваш личный портфель. Котировки:{" "}
                  {formatRelativeTime(data.shadow?.last_intraday_refresh?.at ?? null)}.
                </p>
                <div className="cockpit-footer-links">
                  <Link className="button secondary" to="/shadow" data-testid="dashboard-shadow-cta">
                    Открыть эксперимент
                  </Link>
                </div>
              </>
            )}
          </CockpitSection>
        </div>
      )}
    </div>
  );
}
