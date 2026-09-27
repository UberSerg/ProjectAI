import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  getCatalogInstrument,
  searchCatalogInstruments,
  type CatalogInstrument,
  type CatalogInstrumentDetail,
} from "../api/instruments";
import { getDailyPersonalDecision, type DailyPersonalDecision } from "../api/dailyPersonalDecision";
import {
  addPrimaryPosition,
  getPrimaryAnalysis,
  getPrimaryCashflows,
  getPrimaryCompareCandidate,
  getPrimaryRebalance,
  type ManualCompareCandidate,
  type ManualPortfolioAnalysis,
  type ManualRebalancePlan,
  type PortfolioCashflows,
} from "../api/manualPortfolios";
import {
  AllocationBars,
  DataQualityCard,
  ExplanationCard,
  MetricCard,
  PageHeader,
  PageState,
  RiskCard,
  StatusBadge,
  WarningCard,
} from "../components/Ui";
import {
  compareStatusLabel,
  isBondLike,
  moneyRub,
  pctWeight,
  qualityLabel,
  suggestedActionLabel,
} from "../features/manualPortfolio/labels";
import { MetricHelp } from "../help";
import {
  getPortfolioFundamentalCoverage,
  type PortfolioFundamentalCoverage,
} from "../api/fundamentals";
import { DailyDecisionPanel } from "../features/personalPortfolio/DailyDecisionPanel";
import { PersonalPortfolioPanel } from "../features/personalPortfolio/PersonalPortfolioPanel";
import { useKrakenRole } from "../role/KrakenRoleContext";

type Tab = "holdings" | "decision" | "analysis" | "payments" | "compare" | "rebalance";


function AddInstrumentModal({
  open,
  onClose,
  onAdded,
}: {
  open: boolean;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [hits, setHits] = useState<CatalogInstrument[]>([]);
  const [selected, setSelected] = useState<CatalogInstrument | null>(null);
  const [units, setUnits] = useState("10");
  const [avgPrice, setAvgPrice] = useState("");
  const [nonStandardLot, setNonStandardLot] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(query.trim()), 300);
    return () => window.clearTimeout(t);
  }, [query]);

  useEffect(() => {
    if (!open || !debounced) {
      setHits([]);
      return;
    }
    const controller = new AbortController();
    searchCatalogInstruments({ search: debounced, active: true, page_size: 12 }, controller.signal)
      .then((resp) => setHits(resp.items))
      .catch(() => setHits([]));
    return () => controller.abort();
  }, [debounced, open]);

  if (!open) return null;

  async function submit() {
    if (!selected) {
      setErr("Выберите инструмент");
      return;
    }
    const unitsNum = Number(units);
    if (!Number.isFinite(unitsNum) || unitsNum <= 0) {
      setErr("Количество должно быть больше нуля");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await addPrimaryPosition({
        instrument_id: selected.id,
        units: unitsNum,
        average_price: avgPrice === "" ? null : Number(avgPrice),
        non_standard_lot: nonStandardLot,
      });
      onAdded();
      onClose();
      setQuery("");
      setSelected(null);
      setUnits("10");
      setAvgPrice("");
      setNonStandardLot(false);
    } catch (reason) {
      setErr(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Добавить инструмент"
        data-testid="add-instrument-modal"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2>Добавить инструмент</h2>
        <label>
          Поиск
          <input
            data-testid="add-instrument-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="SBER, ОФЗ, ISIN…"
            autoFocus
          />
        </label>
        {hits.length > 0 ? (
          <ul className="plain-list" data-testid="add-instrument-hits" style={{ maxHeight: 180, overflow: "auto" }}>
            {hits.map((hit) => (
              <li key={hit.id}>
                <button
                  type="button"
                  className={selected?.id === hit.id ? "secondary" : "linkish"}
                  onClick={() => setSelected(hit)}
                >
                  <strong className="mono">{hit.symbol}</strong> — {hit.name}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {selected ? (
          <p className="muted">
            Выбрано: <strong className="mono">{selected.symbol}</strong> ({selected.name})
          </p>
        ) : null}
        <div className="filters" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <label>
            Количество (шт.)
            <input data-testid="add-instrument-units" value={units} onChange={(e) => setUnits(e.target.value)} />
          </label>
          <label>
            Средняя цена покупки (опц.)
            <input
              data-testid="add-instrument-avg"
              value={avgPrice}
              onChange={(e) => setAvgPrice(e.target.value)}
              placeholder="необязательно"
            />
          </label>
        </div>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={nonStandardLot}
            onChange={(e) => setNonStandardLot(e.target.checked)}
          />
          Нестандартный лот (если LOTSIZE неизвестен или дробный остаток)
        </label>
        {err ? (
          <WarningCard title="Проверка лота">
            <p style={{ margin: 0 }}>{err}</p>
          </WarningCard>
        ) : null}
        <div className="modal-actions">
          <button type="button" className="secondary" onClick={onClose}>
            Отмена
          </button>
          <button type="button" disabled={busy} onClick={() => void submit()} data-testid="add-instrument-submit">
            {busy ? "Сохранение…" : "Добавить"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function MyPortfolioPage() {
  const { isUser } = useKrakenRole();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabFromUrl = searchParams.get("tab");
  const initialTab: Tab =
    tabFromUrl === "analysis" ||
    tabFromUrl === "payments" ||
    tabFromUrl === "compare" ||
    tabFromUrl === "rebalance" ||
    tabFromUrl === "decision" ||
    tabFromUrl === "holdings"
      ? tabFromUrl
      : "holdings";
  const [analysis, setAnalysis] = useState<ManualPortfolioAnalysis | null>(null);
  const [catalogBySymbol, setCatalogBySymbol] = useState<Record<string, CatalogInstrumentDetail>>({});
  const [compare, setCompare] = useState<ManualCompareCandidate | null>(null);
  const [rebalance, setRebalance] = useState<ManualRebalancePlan | null>(null);
  const [dailyDecision, setDailyDecision] = useState<DailyPersonalDecision | null>(null);
  const [tab, setTab] = useState<Tab>(initialTab);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [cashflows, setCashflows] = useState<PortfolioCashflows | null>(null);
  const [fundCoverage, setFundCoverage] = useState<PortfolioFundamentalCoverage | null>(null);
  const focusSymbol = (searchParams.get("focus") || "").toUpperCase();

  useEffect(() => {
    const t = searchParams.get("tab");
    if (
      t === "analysis" ||
      t === "payments" ||
      t === "compare" ||
      t === "rebalance" ||
      t === "decision" ||
      t === "holdings"
    ) {
      setTab(t);
    }
  }, [searchParams]);

  function selectTab(next: Tab) {
    setTab(next);
    const params = new URLSearchParams(searchParams);
    params.set("tab", next);
    setSearchParams(params, { replace: true });
  }

  const reload = useCallback(async (signal?: AbortSignal) => {
    const next = await getPrimaryAnalysis(signal);
    setAnalysis(next);
    const symbols = [...new Set(next.positions.map((p) => p.symbol))];
    const details = await Promise.all(
      symbols.map((symbol) => getCatalogInstrument(symbol, signal).catch(() => null)),
    );
    const map: Record<string, CatalogInstrumentDetail> = {};
    details.forEach((d) => {
      if (d) map[d.symbol.toUpperCase()] = d;
    });
    setCatalogBySymbol(map);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    reload(controller.signal)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [reload]);

  useEffect(() => {
    if (tab !== "analysis") return;
    const controller = new AbortController();
    getPortfolioFundamentalCoverage(controller.signal)
      .then((payload) => setFundCoverage(payload))
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setFundCoverage(null);
        }
      });
    return () => controller.abort();
  }, [tab]);

  useEffect(() => {
    if (tab !== "decision") return;
    const controller = new AbortController();
    getDailyPersonalDecision({ signal: controller.signal })
      .then(setDailyDecision)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setDailyDecision(null);
          setError(errorMessage(reason));
        }
      });
    return () => controller.abort();
  }, [tab]);

  useEffect(() => {
    if (tab !== "compare" || !analysis) return;
    const controller = new AbortController();
    getPrimaryCompareCandidate(controller.signal)
      .then(setCompare)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      });
    return () => controller.abort();
  }, [tab, analysis]);

  useEffect(() => {
    if (tab !== "rebalance" || !analysis) return;
    const controller = new AbortController();
    getPrimaryRebalance(controller.signal)
      .then(setRebalance)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      });
    return () => controller.abort();
  }, [tab, analysis]);

  useEffect(() => {
    if (tab !== "payments" || !analysis) return;
    const controller = new AbortController();
    getPrimaryCashflows(controller.signal)
      .then(setCashflows)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      });
    return () => controller.abort();
  }, [tab, analysis]);


  const allocationWeights = useMemo(() => {
    if (!analysis) return { equity: 0, fixedIncome: 0, cash: 0 };
    const nav = analysis.nav || 1;
    let equity = 0;
    let fixedIncome = 0;
    for (const row of analysis.positions) {
      const cat = catalogBySymbol[row.symbol.toUpperCase()];
      const w = row.weight ?? (row.market_value != null ? row.market_value / nav : 0);
      if (isBondLike(cat?.asset_class, cat?.instrument_subtype, row.detail)) {
        fixedIncome += w;
      } else {
        equity += w;
      }
    }
    const cash = analysis.nav > 0 ? analysis.cash_rub / analysis.nav : 0;
    return { equity, fixedIncome, cash };
  }, [analysis, catalogBySymbol]);




  if (loading && tab !== "holdings") return <PageState kind="loading" title="Загрузка портфеля…" />;
  if (error && !analysis && tab !== "holdings") return <PageState kind="error">{error}</PageState>;


  return (
    <section data-testid="my-portfolio-page">
      <PageHeader
        title="Мой портфель"
        description="Реальные операции и оценка по рыночным данным. Без брокера и без исполнения сделок."
        helpPageId="manual_portfolio"
      />

      {error && tab !== "holdings" ? (
        <WarningCard title="Сообщение">
          <p style={{ margin: 0 }}>{error}</p>
        </WarningCard>
      ) : null}

      <p className="muted recommendation-disclaimer" data-testid="model-recommendation-disclaimer">
        Блок «Что делать» — модельная рекомендация по текущему личному портфелю, не приказ брокеру.
      </p>

      <div className="tabs" role="tablist" style={{ marginTop: "1rem" }}>
        {(
          [
            ["holdings", "Состав"],
            ["decision", "Что делать"],
            ["analysis", "Анализ"],
            ["payments", "Выплаты"],
            ["compare", "Сравнение с Kraken"],
            ["rebalance", "Ребаланс"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`tab${tab === id ? " active" : ""}`}
            onClick={() => selectTab(id)}
            data-testid={`tab-${id}`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "holdings" ? (
        <div data-testid="tab-holdings-panel">
          <PersonalPortfolioPanel />
        </div>
      ) : null}

      {tab === "decision" ? (
        <div data-testid="tab-decision-panel" style={{ marginTop: "0.75rem" }}>
          <DailyDecisionPanel decision={dailyDecision} owner={!isUser} />
        </div>
      ) : null}

      {tab === "analysis" && analysis ? (
        <div data-testid="tab-analysis-panel" style={{ marginTop: "0.75rem" }}>
          <ExplanationCard title="Распределение" level={1}>
            <AllocationBars
              equity={allocationWeights.equity}
              fixedIncome={allocationWeights.fixedIncome}
              cash={allocationWeights.cash}
            />
            <MetricHelp metricId="allocation" />
          </ExplanationCard>

          <article className="panel" style={{ marginTop: "1rem" }}>
            <h2>
              Концентрация по эмитенту <MetricHelp metricId="issuer_concentration" />
            </h2>
            {analysis.concentration_by_issuer.length === 0 ? (
              <p className="muted">Нет данных</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Эмитент</th>
                      <th>Оценка</th>
                      <th>Вес</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysis.concentration_by_issuer.map((row) => (
                      <tr key={row.issuer_key}>
                        <td>{row.issuer_title}</td>
                        <td>{moneyRub(row.market_value)}</td>
                        <td>{pctWeight(row.weight)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>

          <RiskCard title="Риск (advisory)">
            <p className="muted">
              Находки носят рекомендательный характер и не являются статусом BLOCKED / gate.
            </p>
            {analysis.risk_findings.length === 0 ? (
              <p>Критичных advisory-замечаний нет.</p>
            ) : (
              <ul className="plain-list">
                {analysis.risk_findings.map((f, idx) => (
                  <li key={`${f.code}-${idx}`}>
                    <strong>{f.code}</strong>: {f.message}
                    {f.issuer ? ` (${f.issuer})` : ""}
                    {f.symbol ? ` · ${f.symbol}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </RiskCard>

          {analysis.credit_intelligence ? (
            <article
              className="panel"
              style={{ marginTop: "1rem" }}
              data-testid="portfolio-credit-intelligence"
            >
              <h2>
                Кредитный риск облигаций{" "}
                <MetricHelp metricId="credit_data_coverage" />
              </h2>
              <p className="muted">
                Весовое покрытие (не счётчик бумаг). Источник рейтингов:{" "}
                {analysis.credit_intelligence.provider_verdict || "NOT_READY"}. Без авто-сделок по
                рейтингам.{" "}
                <MetricHelp metricId="government_debt" />
              </p>
              <div className="card-grid">
                <MetricCard
                  label="Госдолг (вес)"
                  value={pctWeight(analysis.credit_intelligence.government_weight)}
                  helpId="government_debt"
                />
                <MetricCard
                  label="Корпоративные"
                  value={pctWeight(analysis.credit_intelligence.corporate_weight)}
                  helpId="credit_rating"
                />
                <MetricCard
                  label="С рейтингом"
                  value={pctWeight(analysis.credit_intelligence.rated_corporate_weight)}
                  helpId="issuer_rating"
                />
                <MetricCard
                  label="Без данных (SOURCE_NOT_READY)"
                  value={pctWeight(analysis.credit_intelligence.credit_data_unavailable_weight)}
                  helpId="unrated"
                />
              </div>
              {(analysis.credit_intelligence.top_issuers || []).length > 0 ? (
                <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Эмитент</th>
                        <th>Статус</th>
                        <th>Рейтинг</th>
                        <th>Вес</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analysis.credit_intelligence.top_issuers.map((row) => (
                        <tr key={row.issuer_key}>
                          <td>{row.issuer_title}</td>
                          <td>{row.availability_status || "—"}</td>
                          <td>
                            {row.rating_raw
                              ? `${row.rating_raw}${row.agency_code ? ` (${row.agency_code})` : ""}`
                              : "—"}
                          </td>
                          <td>{pctWeight(row.weight)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="muted">Нет облигационных позиций для кредитного разреза.</p>
              )}
            </article>
          ) : null}

          <article
            className="panel"
            style={{ marginTop: "1rem" }}
            data-testid="portfolio-fundamental-coverage"
          >
            <h2>
              Фундаментальное покрытие (RAS / FNS){" "}
              <MetricHelp metricId="fundamental_data" />
            </h2>
            <p className="muted">
              Read-only coverage research cohort. Sync только через{" "}
              <code>sync_fundamentals_fns</code> / Celery — не при рендере страницы.{" "}
              <MetricHelp metricId="fns_gir_bo" />
            </p>
            {!fundCoverage ? (
              <p className="muted">Загрузка coverage…</p>
            ) : (
              <>
                <div className="card-grid">
                  <MetricCard
                    label="Industrial с отчётами"
                    value={String(fundCoverage.industrial_with_reports ?? "—")}
                    helpId="financial_report"
                  />
                  <MetricCard
                    label="Industrial mapped"
                    value={String(fundCoverage.industrial_mapped ?? "—")}
                  />
                  <MetricCard
                    label="Банки / FI unsupported"
                    value={String(fundCoverage.bank_unsupported ?? "—")}
                    helpId="RAS"
                  />
                  <MetricCard label="UNMAPPED" value={String(fundCoverage.unmapped ?? "—")} />
                </div>
                {fundCoverage.note ? <p className="muted">{fundCoverage.note}</p> : null}
                <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
                  <table>
                    <thead>
                      <tr>
                        <th>SECID</th>
                        <th>Статус</th>
                        <th>Отчёты</th>
                        <th>Период</th>
                        <th>known_at</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(fundCoverage.rows ?? []).slice(0, 20).map((row) => (
                        <tr key={`${row.secid}-${row.issuer_id}`}>
                          <td className="mono">{row.secid ?? "—"}</td>
                          <td>{row.support_status ?? "—"}</td>
                          <td>{row.reports ?? 0}</td>
                          <td>{row.latest_period_end ?? "—"}</td>
                          <td>{row.latest_known_at ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="muted">
                  Полный список:{" "}
                  <Link to="/fundamentals">Компании / фундаментал</Link>.
                </p>
              </>
            )}
          </article>

          <DataQualityCard title="Качество котировок">
            <p style={{ margin: 0 }}>
              Сводка: <StatusBadge status={analysis.quality === "LIVE" ? "ok" : "warning"} label={qualityLabel(analysis.quality)} />
              . Неоценённых позиций: {analysis.unsupported_count}.{" "}
              <MetricHelp metricId="indicative_price" />
            </p>
          </DataQualityCard>
        </div>
      ) : null}

      {tab === "payments" && analysis ? (
        <div data-testid="tab-payments-panel" style={{ marginTop: "0.75rem" }}>
          {!cashflows ? (
            <PageState kind="loading" title="Загрузка выплат…" />
          ) : (
            <>
              <p className="muted">
                Gross до налогов и комиссий. Оферты — только информационно.{" "}
                <MetricHelp metricId="portfolio_cashflows" />
              </p>
              <div className="card-grid">
                <MetricCard
                  label="30 дней"
                  value={moneyRub(cashflows.horizons["30d"]?.gross ?? 0)}
                  helpId="portfolio_cashflows"
                />
                <MetricCard label="90 дней" value={moneyRub(cashflows.horizons["90d"]?.gross ?? 0)} />
                <MetricCard label="12 месяцев" value={moneyRub(cashflows.horizons["12m"]?.gross ?? 0)} />
              </div>
              <article className="panel" style={{ marginTop: "1rem" }}>
                <h2>Облигации: ближайшая выплата</h2>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Тикер</th>
                        <th>Дата</th>
                        <th>Тип</th>
                        <th>Сумма</th>
                        <th>Статус данных</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cashflows.positions.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="muted">
                            Нет облигационных позиций
                          </td>
                        </tr>
                      ) : (
                        cashflows.positions.map((p) => (
                          <tr key={p.instrument_id}>
                            <td className="mono">{p.symbol}</td>
                            <td>{p.next_payment?.event_date ?? "—"}</td>
                            <td>{p.next_payment?.event_type ?? "—"}</td>
                            <td>
                              {p.next_payment?.gross_amount != null
                                ? moneyRub(p.next_payment.gross_amount)
                                : "—"}
                            </td>
                            <td>
                              {p.enrichment_pending ? (
                                <StatusBadge status="warning" label="Обогащение…" />
                              ) : p.missing_terms ? (
                                <StatusBadge status="warning" label="Нет terms" />
                              ) : (
                                <StatusBadge status="ok" label="OK" />
                              )}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </article>
              <article className="panel" style={{ marginTop: "1rem" }}>
                <h2>Календарь выплат</h2>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Дата</th>
                        <th>Тикер</th>
                        <th>Тип</th>
                        <th>Gross</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cashflows.events
                        .filter((e) => !e.informational)
                        .slice(0, 40)
                        .map((e, idx) => (
                          <tr key={`${e.symbol}-${e.event_date}-${e.event_type}-${idx}`}>
                            <td>{e.event_date}</td>
                            <td className="mono">{e.symbol}</td>
                            <td>{e.event_type}</td>
                            <td>{e.gross_amount != null ? moneyRub(e.gross_amount) : "—"}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </article>
            </>
          )}
        </div>
      ) : null}

      {tab === "compare" && analysis ? (
        <div data-testid="tab-compare-panel" style={{ marginTop: "0.75rem" }}>
          {!compare ? (
            <PageState kind="loading" title="Сравнение…" />
          ) : (
            <>
              <p className="muted">
                Источник кандидата: {compare.candidate_source}
                {compare.candidate_id ? ` · ${compare.candidate_id}` : ""}. «Нет у Kraken» ≠ сигнал продать.
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Тикер</th>
                      <th>Мой вес</th>
                      <th>Kraken</th>
                      <th>Статус</th>
                      <th>Совет</th>
                    </tr>
                  </thead>
                  <tbody>
                    {compare.comparisons.map((row) => (
                      <tr key={row.symbol}>
                        <td className="mono">{row.symbol}</td>
                        <td>{pctWeight(row.manual_weight)}</td>
                        <td>{pctWeight(row.candidate_weight)}</td>
                        <td>{compareStatusLabel(row.status)}</td>
                        <td>{suggestedActionLabel(row.suggested_action)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p>
                <Link to="/portfolio/candidate">Открыть кандидат портфеля</Link>
              </p>
            </>
          )}
        </div>
      ) : null}

      {tab === "rebalance" && analysis ? (
        <div data-testid="tab-rebalance-panel" style={{ marginTop: "0.75rem" }}>
          <WarningCard title="Расчётный план, не заявки">
            <p style={{ margin: 0 }}>
              Ребаланс advisory: лотовый план без сохранения ордеров и без брокера.{" "}
              <MetricHelp metricId="rebalance" />
            </p>
          </WarningCard>
          {!rebalance ? (
            <PageState kind="loading" title="План ребаланса…" />
          ) : (
            <>
              <div className="card-grid" style={{ marginTop: "0.75rem" }}>
                <MetricCard label="NAV" value={moneyRub(rebalance.nav)} />
                <MetricCard label="Кэш сейчас" value={moneyRub(rebalance.cash)} />
                <MetricCard label="Кэш после" value={moneyRub(rebalance.projected_cash)} />
                <MetricCard
                  label="Запас ликвидности"
                  value={rebalance.cash_safe ? "Достаточный" : "Риск нехватки"}
                />
              </div>
              <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Тикер</th>
                      <th>Действие</th>
                      <th>Δ лоты</th>
                      <th>Δ шт.</th>
                      <th>Цель</th>
                      <th>Сейчас</th>
                      <th>Нотионал</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rebalance.plan_rows.map((row) => (
                      <tr
                        key={`${row.ticker}-${row.action}`}
                        data-focus={focusSymbol === row.ticker.toUpperCase() ? "true" : undefined}
                        style={
                          focusSymbol === row.ticker.toUpperCase()
                            ? { background: "rgba(77, 143, 255, 0.12)" }
                            : undefined
                        }
                      >
                        <td className="mono">{row.ticker}</td>
                        <td>
                          {(() => {
                            const a = (row.action || "").toUpperCase();
                            if (a.includes("BUY") || a.includes("INCREASE")) return "Докупить";
                            if (a.includes("SELL") || a.includes("REDUCE") || a.includes("EXIT"))
                              return "Сократить";
                            const labeled = suggestedActionLabel(row.action);
                            return labeled !== "—" ? labeled : row.action;
                          })()}
                        </td>
                        <td>{row.lots_delta}</td>
                        <td>{row.units_delta}</td>
                        <td>{pctWeight(row.target_weight)}</td>
                        <td>{pctWeight(row.current_weight)}</td>
                        <td>{moneyRub(row.estimated_notional)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {rebalance.review_rows.length > 0 ? (
                <article className="panel" style={{ marginTop: "1rem" }}>
                  <h2>На проверку (REVIEW)</h2>
                  <ul className="plain-list">
                    {rebalance.review_rows.map((row, idx) => (
                      <li key={`${row.symbol}-${idx}`}>
                        <strong className="mono">{row.symbol}</strong>: {row.reason}
                      </li>
                    ))}
                  </ul>
                </article>
              ) : null}
            </>
          )}
        </div>
      ) : null}

      <AddInstrumentModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onAdded={() => void reload()}
      />
    </section>
  );
}
