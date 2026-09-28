import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { PortfolioSwitcher } from "../portfolio/PortfolioSwitcher";
import { usePortfolioContext } from "../portfolio/PortfolioContext";
import { errorMessage } from "../api/client";
import {
  getCatalogInstrument,
  searchCatalogInstruments,
  type CatalogInstrument,
  type CatalogInstrumentDetail,
} from "../api/instruments";
import { getDailyPersonalDecision, type DailyPersonalDecision } from "../api/dailyPersonalDecision";
import {
  getPortfolioAnalysis,
  getPortfolioCashflows,
  getPortfolioCompareCandidate,
  getPortfolioRebalance,
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
import {
  addDraftPosition,
  deletePersonalPortfolio,
  getPersonalPortfolio,
  patchPersonalPortfolio,
  type PersonalOperationType,
  type PersonalSummary,
} from "../api/personalPortfolios";
import { DailyDecisionPanel } from "../features/personalPortfolio/DailyDecisionPanel";
import {
  OP_LABELS,
  PersonalPortfolioPanel,
  portfolioLifecycleState,
} from "../features/personalPortfolio/PersonalPortfolioPanel";
import { useKrakenRole } from "../role/KrakenRoleContext";

type Tab = "holdings" | "history" | "decision" | "analysis" | "payments" | "compare" | "rebalance";

const DRAFT_PRELIMINARY_NOTE =
  "История операций ещё не начата. Анализ относится к текущему составу портфеля.";
const DRAFT_PRELIMINARY_CALC_NOTE = "Предварительный расчёт по текущему составу.";

function lifecycleHeaderLabel(state: string | undefined): string {
  if (state === "ACTIVE") return "Учёт включён";
  return "Настройка";
}

type Resource<T> = { data: T | null; loading: boolean; error: string | null };

const EMPTY_RESOURCE: Resource<never> = { data: null, loading: false, error: null };

/**
 * Tab-local resource: reloads on `key` change, drops responses from superseded
 * keys so a slow portfolio A answer can never land on portfolio B.
 */
function useTabResource<T>(
  active: boolean,
  key: string,
  loader: (signal: AbortSignal) => Promise<T>,
): Resource<T> {
  const [state, setState] = useState<Resource<T>>(EMPTY_RESOURCE);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const seq = useRef(0);

  useEffect(() => {
    seq.current += 1;
    const mine = seq.current;
    if (!active) {
      setState(EMPTY_RESOURCE);
      return;
    }
    const controller = new AbortController();
    setState({ data: null, loading: true, error: null });
    loaderRef
      .current(controller.signal)
      .then((data) => {
        if (seq.current !== mine) return;
        setState({ data, loading: false, error: null });
      })
      .catch((reason: unknown) => {
        if (seq.current !== mine) return;
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setState({ data: null, loading: false, error: errorMessage(reason) });
      });
    return () => controller.abort();
  }, [active, key]);

  return state;
}

function TabLoadState({ resource, loadingTitle }: { resource: Resource<unknown>; loadingTitle: string }) {
  if (resource.loading) return <PageState kind="loading" title={loadingTitle} />;
  if (resource.error) {
    return (
      <WarningCard title="Не удалось загрузить данные">
        <p style={{ margin: 0 }}>{resource.error}</p>
      </WarningCard>
    );
  }
  return null;
}

function money(v: string | null | undefined): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return v;
  return `${n.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
}


function AddInstrumentModal({
  open,
  onClose,
  onAdded,
  portfolioId,
}: {
  open: boolean;
  onClose: () => void;
  onAdded: () => void;
  portfolioId: number;
}) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [hits, setHits] = useState<CatalogInstrument[]>([]);
  const [selected, setSelected] = useState<CatalogInstrument | null>(null);
  const [units, setUnits] = useState("10");
  const [avgPrice, setAvgPrice] = useState("");
  const [costBasisTotal, setCostBasisTotal] = useState("");
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
    const isBond = (selected.asset_class || "").toLowerCase() === "bond";
    setBusy(true);
    setErr(null);
    try {
      const body: Parameters<typeof addDraftPosition>[1] = {
        instrument_id: selected.id,
        units: unitsNum,
        non_standard_lot: nonStandardLot,
      };
      if (isBond) {
        if (costBasisTotal.trim() !== "") {
          body.cost_basis_total_rub = Number(costBasisTotal);
        }
      } else {
        body.average_price = avgPrice === "" ? null : Number(avgPrice);
      }
      await addDraftPosition(portfolioId, body);
      onAdded();
      onClose();
      setQuery("");
      setSelected(null);
      setUnits("10");
      setAvgPrice("");
      setCostBasisTotal("");
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
            {(selected.asset_class || "").toLowerCase() === "bond" ? " · облигация" : ""}
          </p>
        ) : null}
        <div className="filters" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <label>
            Количество (шт.)
            <input data-testid="add-instrument-units" value={units} onChange={(e) => setUnits(e.target.value)} />
          </label>
          {(selected?.asset_class || "").toLowerCase() === "bond" ? (
            <label>
              Сколько всего было потрачено на позицию, ₽ — необязательно
              <input
                data-testid="add-instrument-cost-basis"
                value={costBasisTotal}
                onChange={(e) => setCostBasisTotal(e.target.value)}
                placeholder="необязательно"
              />
            </label>
          ) : (
            <label>
              Себестоимость позиции / средняя цена, ₽
              <input
                data-testid="add-instrument-avg"
                value={avgPrice}
                onChange={(e) => setAvgPrice(e.target.value)}
                placeholder="необязательно"
              />
            </label>
          )}
        </div>
        {(selected?.asset_class || "").toLowerCase() === "bond" ? (
          <p className="muted" data-testid="bond-cost-basis-hint">
            Если себестоимость не указана, Kraken покажет позицию без расчёта P&amp;L.
          </p>
        ) : null}
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
  const { portfolioId: routePortfolioId } = useParams();
  const navigate = useNavigate();
  const {
    selectedPortfolioId,
    selectPortfolio,
    portfolios,
    loading: portfoliosLoading,
    refreshList,
    selectedPortfolio,
  } = usePortfolioContext();
  // An explicit deep link is only honoured once it is proven to exist. An unknown
  // id must not become the stored selection, must not silently redirect, and must
  // not trigger any portfolio request.
  const routeId = useMemo(() => {
    if (!routePortfolioId) return null;
    const id = Number(routePortfolioId);
    return Number.isInteger(id) && id > 0 ? id : null;
  }, [routePortfolioId]);
  const routeIdResolved = routeId != null && portfolios.some((p) => p.id === routeId);
  const portfolioId = routePortfolioId ? (routeIdResolved ? routeId : null) : selectedPortfolioId;

  useEffect(() => {
    if (!routeIdResolved || routeId === selectedPortfolioId) return;
    selectPortfolio(routeId);
  }, [routeIdResolved, routeId, selectedPortfolioId, selectPortfolio]);

  useEffect(() => {
    if (!routePortfolioId && selectedPortfolioId != null) {
      navigate(`/portfolio/${selectedPortfolioId}${window.location.search}`, { replace: true });
    }
  }, [routePortfolioId, selectedPortfolioId, navigate]);

  const { isUser } = useKrakenRole();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabFromUrl = searchParams.get("tab");
  const initialTab: Tab =
    tabFromUrl === "analysis" ||
    tabFromUrl === "payments" ||
    tabFromUrl === "compare" ||
    tabFromUrl === "rebalance" ||
    tabFromUrl === "decision" ||
    tabFromUrl === "history" ||
    tabFromUrl === "holdings"
      ? tabFromUrl
      : "holdings";
  const [catalogBySymbol, setCatalogBySymbol] = useState<Record<string, CatalogInstrumentDetail>>({});
  const [tab, setTab] = useState<Tab>(initialTab);
  const [modalOpen, setModalOpen] = useState(false);
  const [dataVersion, setDataVersion] = useState(0);
  const focusSymbol = (searchParams.get("focus") || "").toUpperCase();
  const reload = useCallback(() => setDataVersion((v) => v + 1), []);

  /** Every mutation refreshes the panel, the tab resources and the switcher counts. */
  const onPortfolioMutated = useCallback(() => {
    reload();
    void refreshList();
  }, [reload, refreshList]);

  useEffect(() => {
    const t = searchParams.get("tab");
    if (
      t === "analysis" ||
      t === "payments" ||
      t === "compare" ||
      t === "rebalance" ||
      t === "decision" ||
      t === "history" ||
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

  // Core: the personal summary alone is enough to render «Состав» and «История».
  const summaryRes = useTabResource<PersonalSummary>(
    portfolioId != null,
    `summary:${portfolioId}:${isUser}:${dataVersion}`,
    (signal) => getPersonalPortfolio(portfolioId!, { owner: !isUser, signal }),
  );
  const personalJournal = summaryRes.data;

  const analysisRes = useTabResource<ManualPortfolioAnalysis>(
    portfolioId != null && tab === "analysis",
    `analysis:${portfolioId}:${dataVersion}`,
    (signal) => getPortfolioAnalysis(portfolioId!, signal),
  );
  const analysis = analysisRes.data;

  const decisionRes = useTabResource<DailyPersonalDecision>(
    portfolioId != null && tab === "decision",
    `decision:${portfolioId}:${dataVersion}`,
    (signal) => getDailyPersonalDecision(portfolioId!, { signal }),
  );

  const cashflowsRes = useTabResource<PortfolioCashflows>(
    portfolioId != null && tab === "payments",
    `cashflows:${portfolioId}:${dataVersion}`,
    (signal) => getPortfolioCashflows(portfolioId!, signal),
  );

  const compareRes = useTabResource<ManualCompareCandidate>(
    portfolioId != null && tab === "compare",
    `compare:${portfolioId}:${dataVersion}`,
    (signal) => getPortfolioCompareCandidate(portfolioId!, signal),
  );

  const rebalanceRes = useTabResource<ManualRebalancePlan>(
    portfolioId != null && tab === "rebalance",
    `rebalance:${portfolioId}:${dataVersion}`,
    (signal) => getPortfolioRebalance(portfolioId!, signal),
  );

  const coverageRes = useTabResource<PortfolioFundamentalCoverage>(
    tab === "analysis",
    `coverage:${dataVersion}`,
    (signal) => getPortfolioFundamentalCoverage(signal),
  );
  const fundCoverage = coverageRes.data;
  const cashflows = cashflowsRes.data;
  const compare = compareRes.data;
  const rebalance = rebalanceRes.data;

  const lifecycle =
    selectedPortfolio?.lifecycle_state ??
    (personalJournal ? portfolioLifecycleState(personalJournal) : "DRAFT");
  const isDraft = lifecycle !== "ACTIVE";

  // Asset-class hints for the allocation split; failures degrade to equity-only.
  useEffect(() => {
    setCatalogBySymbol({});
    if (!analysis) return;
    const controller = new AbortController();
    const symbols = [...new Set(analysis.positions.map((p) => p.symbol))];
    Promise.all(symbols.map((symbol) => getCatalogInstrument(symbol, controller.signal).catch(() => null)))
      .then((details) => {
        if (controller.signal.aborted) return;
        const map: Record<string, CatalogInstrumentDetail> = {};
        details.forEach((d) => {
          if (d) map[d.symbol.toUpperCase()] = d;
        });
        setCatalogBySymbol(map);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [analysis]);

  async function onRenamePortfolio() {
    if (portfolioId == null) return;
    const current = selectedPortfolio?.name ?? "Портфель";
    const next = window.prompt("Новое название портфеля", current);
    if (!next?.trim()) return;
    try {
      await patchPersonalPortfolio(portfolioId, { name: next.trim() });
      await refreshList();
      void reload();
    } catch (reason) {
      window.alert(errorMessage(reason));
    }
  }

  async function onDeletePortfolio() {
    if (portfolioId == null) return;
    const label = selectedPortfolio?.name ?? "Портфель";
    if (!window.confirm(`Удалить портфель «${label}»?\nУдаление нельзя отменить.`)) return;
    if (!window.confirm(`Подтвердите удаление портфеля «${label}».`)) return;
    try {
      await deletePersonalPortfolio(portfolioId);
      const items = await refreshList();
      const nextId = items[0]?.id ?? null;
      selectPortfolio(nextId);
      navigate(nextId != null ? `/portfolio/${nextId}` : "/portfolio");
    } catch (reason) {
      window.alert(errorMessage(reason));
    }
  }

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




  if (!portfoliosLoading && portfolios.length === 0) {
    return (
      <section data-testid="my-portfolio-page">
        <PageHeader
          title="Мой портфель"
          description="У вас пока нет портфелей"
          helpPageId="manual_portfolio"
        />
        <p>
          Создайте первый портфель, добавьте деньги и активы — Kraken начнёт анализировать именно его.
        </p>
        <p>
          <Link to="/portfolio">Создать портфель</Link>
        </p>
      </section>
    );
  }

  if (routePortfolioId && !portfoliosLoading && portfolios.length > 0 && !routeIdResolved) {
    return (
      <section data-testid="my-portfolio-page">
        <PageHeader title="Портфель не найден" description="Такого портфеля нет." />
        <p>
          <Link to="/portfolio">К списку портфелей</Link>
        </p>
      </section>
    );
  }

  const portfolioTitle =
    selectedPortfolio?.name ?? personalJournal?.portfolio.name ?? analysis?.portfolio.name ?? "Мой портфель";
  const portfolioLifecycleLabel = lifecycleHeaderLabel(lifecycle);


  return (
    <section data-testid="my-portfolio-page">
      <PortfolioSwitcher />
      <PageHeader
        title={portfolioTitle}
        description={`${portfolioLifecycleLabel} · Реальные операции и оценка по рыночным данным. Без брокера и без исполнения сделок.`}
        helpPageId="manual_portfolio"
      />
      <div className="page-header-row" style={{ marginBottom: "0.75rem" }} data-testid="portfolio-header-actions">
        <StatusBadge
          status={isDraft ? "warning" : "ok"}
          label={portfolioLifecycleLabel}
        />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {isDraft ? (
            <button type="button" className="btn secondary" onClick={() => setModalOpen(true)} data-testid="add-instrument-open">
              Добавить инструмент
            </button>
          ) : null}
          <button type="button" className="btn ghost" onClick={() => void onRenamePortfolio()} data-testid="rename-portfolio-btn">
            Переименовать
          </button>
          <button type="button" className="btn ghost" onClick={() => void onDeletePortfolio()} data-testid="delete-portfolio-btn">
            Удалить
          </button>
        </div>
      </div>

      {summaryRes.error ? (
        <WarningCard title="Не удалось загрузить портфель">
          <p style={{ margin: 0 }} data-testid="portfolio-core-error">
            {summaryRes.error}
          </p>
        </WarningCard>
      ) : null}

      <p className="muted recommendation-disclaimer" data-testid="model-recommendation-disclaimer">
        Блок «Что делать» — модельная рекомендация по текущему личному портфелю, не приказ брокеру.
      </p>

      <div className="tabs" role="tablist" style={{ marginTop: "1rem" }}>
        {(
          [
            ["holdings", "Состав"],
            ["history", "История"],
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
            title={
              isDraft && (id === "compare" || id === "rebalance")
                ? "История операций ещё не начата — сравнение приблизительное"
                : undefined
            }
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "holdings" && portfolioId != null ? (
        <div data-testid="tab-holdings-panel">
          <PersonalPortfolioPanel
            portfolioId={portfolioId}
            refreshToken={dataVersion}
            onChanged={onPortfolioMutated}
          />
        </div>
      ) : null}

      {tab === "history" ? (
        <div data-testid="tab-history-panel" style={{ marginTop: "0.75rem" }}>
          {summaryRes.loading && !personalJournal ? (
            <PageState kind="loading" title="Загрузка истории…" />
          ) : !personalJournal ? (
            <p className="muted">Нет данных журнала.</p>
          ) : personalJournal.operations.filter((o) => o.status === "ACTIVE").length === 0 ? (
            <p className="muted">Операций пока нет — начните учёт на вкладке «Состав».</p>
          ) : (
            <article className="panel">
              <h2>Журнал операций</h2>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Дата</th>
                      <th>Тип</th>
                      <th>Детали</th>
                      <th>Комментарий</th>
                    </tr>
                  </thead>
                  <tbody>
                    {personalJournal.operations
                      .filter((o) => o.status === "ACTIVE")
                      .map((o) => (
                        <tr key={o.id}>
                          <td>{o.occurred_at?.slice(0, 19).replace("T", " ") ?? "—"}</td>
                          <td>
                            {OP_LABELS[o.operation_type as PersonalOperationType] || o.operation_type}
                          </td>
                          <td>
                            {o.amount ? money(o.amount) : null}
                            {o.units && o.price ? ` · ${o.units} × ${money(o.price)}` : null}
                            {o.commission && o.commission !== "0" ? ` · комиссия ${money(o.commission)}` : null}
                          </td>
                          <td>{o.note || "—"}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </article>
          )}
        </div>
      ) : null}

      {tab === "decision" ? (
        <div data-testid="tab-decision-panel" style={{ marginTop: "0.75rem" }}>
          <TabLoadState resource={decisionRes} loadingTitle="Загрузка рекомендаций…" />
          {decisionRes.data ? <DailyDecisionPanel decision={decisionRes.data} owner={!isUser} /> : null}
        </div>
      ) : null}

      {tab === "analysis" && !analysis ? (
        <div data-testid="tab-analysis-panel" style={{ marginTop: "0.75rem" }}>
          <TabLoadState resource={analysisRes} loadingTitle="Загрузка анализа…" />
        </div>
      ) : null}

      {tab === "analysis" && analysis ? (
        <div data-testid="tab-analysis-panel" style={{ marginTop: "0.75rem" }}>
          {isDraft ? (
            <WarningCard title="Предварительный анализ">
              <p style={{ margin: 0 }} data-testid="draft-preliminary-analysis-note">
                {DRAFT_PRELIMINARY_NOTE}
              </p>
            </WarningCard>
          ) : null}
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
              Фундаментальное покрытие: исследовательская выборка{" "}
              <MetricHelp metricId="fundamental_data" />
            </h2>
            <p className="muted" data-testid="fundamental-coverage-scope">
              Общая исследовательская выборка Kraken по отчётности (РСБУ / ФНС), а не покрытие
              выбранного портфеля. Данные только для чтения и обновляются фоновой задачей.{" "}
              <MetricHelp metricId="fns_gir_bo" />
            </p>
            {!fundCoverage ? (
              <p className="muted">Загрузка данных по отчётности…</p>
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

      {tab === "payments" ? (
        <div data-testid="tab-payments-panel" style={{ marginTop: "0.75rem" }}>
          {!cashflows ? (
            <TabLoadState resource={cashflowsRes} loadingTitle="Загрузка выплат…" />
          ) : (
            <>
              <p className="muted">
                Gross до налогов и комиссий. Оферты — только информационно.{" "}
                <MetricHelp metricId="portfolio_cashflows" />
              </p>
              <div className="card-grid">
                <MetricCard
                  label="30 дней"
                  value={moneyRub(cashflows.horizons?.["30d"]?.gross ?? 0)}
                  helpId="portfolio_cashflows"
                />
                <MetricCard label="90 дней" value={moneyRub(cashflows.horizons?.["90d"]?.gross ?? 0)} />
                <MetricCard label="12 месяцев" value={moneyRub(cashflows.horizons?.["12m"]?.gross ?? 0)} />
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
                      {(cashflows.positions ?? []).length === 0 ? (
                        <tr>
                          <td colSpan={5} className="muted">
                            Нет облигационных позиций
                          </td>
                        </tr>
                      ) : (
                        (cashflows.positions ?? []).map((p) => (
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
                      {(cashflows.events ?? [])
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

      {tab === "compare" ? (
        <div data-testid="tab-compare-panel" style={{ marginTop: "0.75rem" }}>
          {!compare ? (
            <TabLoadState resource={compareRes} loadingTitle="Сравнение…" />
          ) : (
            <>
              {isDraft ? (
                <p className="muted" data-testid="draft-preliminary-compare-note">
                  {DRAFT_PRELIMINARY_CALC_NOTE}
                </p>
              ) : null}
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

      {tab === "rebalance" ? (
        <div data-testid="tab-rebalance-panel" style={{ marginTop: "0.75rem" }}>
          <WarningCard title="Расчётный план, не заявки">
            <p style={{ margin: 0 }}>
              Ребаланс advisory: лотовый план без сохранения ордеров и без брокера.{" "}
              <MetricHelp metricId="rebalance" />
            </p>
          </WarningCard>
          {!rebalance ? (
            <TabLoadState resource={rebalanceRes} loadingTitle="План ребаланса…" />
          ) : (
            <>
              {isDraft ? (
                <p className="muted" data-testid="draft-preliminary-rebalance-note">
                  {DRAFT_PRELIMINARY_CALC_NOTE}
                </p>
              ) : null}
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

      {portfolioId != null ? (
        <AddInstrumentModal
          portfolioId={portfolioId}
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          onAdded={onPortfolioMutated}
        />
      ) : null}
    </section>
  );
}
