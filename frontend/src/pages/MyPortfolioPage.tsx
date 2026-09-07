import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  getCatalogInstrument,
  searchCatalogInstruments,
  type CatalogInstrument,
  type CatalogInstrumentDetail,
} from "../api/instruments";
import {
  addPrimaryPosition,
  deletePrimaryPosition,
  getPrimaryAnalysis,
  getPrimaryCashflows,
  getPrimaryCompareCandidate,
  getPrimaryRebalance,
  updatePrimaryCash,
  type ManualCompareCandidate,
  type ManualPortfolioAnalysis,
  type ManualRebalancePlan,
  type PortfolioCashflows,
} from "../api/manualPortfolios";
import {
  AllocationBars,
  DataQualityCard,
  EmptyState,
  ExplanationCard,
  HeroCard,
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
  isOfz,
  moneyRub,
  pctWeight,
  qualityLabel,
  suggestedActionLabel,
  subtypeLabel,
} from "../features/manualPortfolio/labels";
import { MetricHelp } from "../help";

type Tab = "holdings" | "analysis" | "payments" | "compare" | "rebalance";

function unrealizedPnl(analysis: ManualPortfolioAnalysis): number | null {
  const byId = new Map(analysis.portfolio.positions.map((p) => [p.id, p]));
  let cost = 0;
  let hasCost = false;
  let mv = 0;
  let hasMv = false;
  for (const row of analysis.positions) {
    const pos = byId.get(row.position_id);
    if (pos?.average_price != null) {
      cost += pos.average_price * pos.units;
      hasCost = true;
    }
    if (row.market_value != null) {
      mv += row.market_value;
      hasMv = true;
    }
  }
  if (!hasCost || !hasMv) return null;
  return mv - cost;
}

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
  const [analysis, setAnalysis] = useState<ManualPortfolioAnalysis | null>(null);
  const [catalogBySymbol, setCatalogBySymbol] = useState<Record<string, CatalogInstrumentDetail>>({});
  const [compare, setCompare] = useState<ManualCompareCandidate | null>(null);
  const [rebalance, setRebalance] = useState<ManualRebalancePlan | null>(null);
  const [tab, setTab] = useState<Tab>("holdings");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [cashDraft, setCashDraft] = useState("");
  const [cashBusy, setCashBusy] = useState(false);
  const [cashflows, setCashflows] = useState<PortfolioCashflows | null>(null);

  const reload = useCallback(async (signal?: AbortSignal) => {
    const next = await getPrimaryAnalysis(signal);
    setAnalysis(next);
    setCashDraft(String(next.cash_rub));
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

  const empty = useMemo(() => {
    if (!analysis) return false;
    return analysis.positions.length === 0 && analysis.cash_rub <= 0;
  }, [analysis]);

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

  const pnl = analysis ? unrealizedPnl(analysis) : null;

  async function saveCash() {
    const value = Number(cashDraft);
    if (!Number.isFinite(value) || value < 0) {
      setError("Кэш должен быть ≥ 0");
      return;
    }
    setCashBusy(true);
    try {
      await updatePrimaryCash(value);
      await reload();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setCashBusy(false);
    }
  }

  async function removePosition(id: number) {
    try {
      await deletePrimaryPosition(id);
      await reload();
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }

  if (loading) return <PageState kind="loading" title="Загрузка портфеля…" />;
  if (error && !analysis) return <PageState kind="error">{error}</PageState>;
  if (!analysis) return <PageState kind="empty" title="Портфель недоступен" />;

  if (empty) {
    return (
      <section data-testid="my-portfolio-page">
        <PageHeader
          title="Мой портфель"
          description="Ручной портфель инвестора: оценка, анализ и сравнение с кандидатом Kraken."
          helpPageId="manual_portfolio"
        />
        <EmptyState
          title="Портфель пока пуст"
          reason="Добавьте позиции и кэш вручную. Kraken не подключается к брокеру — это ваш снимок."
          action={
            <button type="button" data-testid="empty-add-cta" onClick={() => setModalOpen(true)}>
              Добавить инструмент
            </button>
          }
        />
        <AddInstrumentModal open={modalOpen} onClose={() => setModalOpen(false)} onAdded={() => void reload()} />
      </section>
    );
  }

  const avgById = new Map(analysis.portfolio.positions.map((p) => [p.id, p]));

  return (
    <section data-testid="my-portfolio-page">
      <PageHeader
        title="Мой портфель"
        description="Ручной портфель: оценка по рыночным данным, без брокера и без исполнения сделок."
        helpPageId="manual_portfolio"
        actions={
          <button type="button" onClick={() => setModalOpen(true)} data-testid="add-position-btn">
            Добавить инструмент
          </button>
        }
      />

      {error ? (
        <WarningCard title="Сообщение">
          <p style={{ margin: 0 }}>{error}</p>
        </WarningCard>
      ) : null}

      <HeroCard
        eyebrow="Источник: введён вручную"
        headline={moneyRub(analysis.nav)}
        actions={
          <StatusBadge
            status={analysis.quality === "LIVE" ? "ok" : analysis.quality === "PARTIAL" ? "warning" : "info"}
            label={qualityLabel(analysis.quality)}
          />
        }
      >
        <div className="card-grid" data-testid="my-portfolio-hero">
          <MetricCard label="Стоимость (NAV)" value={moneyRub(analysis.nav)} helpId="current_value" />
          <MetricCard
            label="Нереализованный P&L"
            value={pnl == null ? "—" : moneyRub(pnl)}
            hint={pnl == null ? "Нужна средняя цена покупки" : undefined}
            helpId="unrealized_pnl"
          />
          <MetricCard label="Кэш" value={moneyRub(analysis.cash_rub)} helpId="manual_portfolio_source" />
          <MetricCard label="Позиций" value={analysis.positions.length} />
          <MetricCard
            label="Покрытие оценки"
            value={`${analysis.coverage_pct.toFixed(0)}%`}
            helpId="model_coverage"
          />
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>
          Источник «Введён вручную». Цены — рыночные данные (LIVE / EOD). Не приказы брокеру.
        </p>
      </HeroCard>

      <div className="tabs" role="tablist" style={{ marginTop: "1rem" }}>
        {(
          [
            ["holdings", "Состав"],
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
            onClick={() => setTab(id)}
            data-testid={`tab-${id}`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "holdings" ? (
        <div data-testid="tab-holdings-panel">
          <div className="filters" style={{ marginTop: "0.75rem", gridTemplateColumns: "200px auto" }}>
            <label>
              Кэш, ₽
              <input data-testid="cash-input" value={cashDraft} onChange={(e) => setCashDraft(e.target.value)} />
            </label>
            <div className="page-actions" style={{ alignItems: "end" }}>
              <button type="button" className="secondary" disabled={cashBusy} onClick={() => void saveCash()}>
                Сохранить кэш
              </button>
            </div>
          </div>

          <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
            <table>
              <thead>
                <tr>
                  <th>Инструмент</th>
                  <th>Кол-во</th>
                  <th>
                    Ср. цена <MetricHelp metricId="average_purchase_price" />
                  </th>
                  <th>
                    Оценка <MetricHelp metricId="current_value" />
                  </th>
                  <th>
                    Вес <MetricHelp metricId="portfolio_weight" />
                  </th>
                  <th>Качество</th>
                  <th>Действие</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {analysis.positions.map((row) => {
                  const cat = catalogBySymbol[row.symbol.toUpperCase()];
                  const bond = isBondLike(cat?.asset_class, cat?.instrument_subtype, row.detail);
                  const ofz = isOfz(cat?.instrument_subtype, row.symbol);
                  const avg = avgById.get(row.position_id)?.average_price;
                  const dirty = row.detail?.dirty_total as number | undefined;
                  const nkd = row.detail?.accrued_interest_per_bond as number | undefined;
                  return (
                    <tr key={row.position_id}>
                      <td>
                        <Link to={`/instruments/${encodeURIComponent(row.symbol)}`} className="mono">
                          {row.symbol}
                        </Link>
                        {ofz ? <span className="badge badge-info" style={{ marginLeft: 6 }}>ОФЗ</span> : null}
                        {bond && !ofz ? (
                          <span className="badge" style={{ marginLeft: 6 }}>
                            Облигация
                          </span>
                        ) : null}
                        {cat?.instrument_subtype ? (
                          <div className="muted">{subtypeLabel(cat.instrument_subtype)}</div>
                        ) : null}
                        {bond ? (
                          <div className="muted">
                            <Link to={`/bonds/${encodeURIComponent(row.symbol)}`}>Карточка облигации</Link>
                            {nkd != null ? ` · НКД ${moneyRub(nkd, 2)}` : ""}
                            {dirty != null ? ` · dirty ${moneyRub(dirty)}` : ""}
                          </div>
                        ) : null}
                      </td>
                      <td>{row.units}</td>
                      <td>{avg == null ? "—" : moneyRub(avg, 2)}</td>
                      <td>{moneyRub(row.market_value)}</td>
                      <td>{pctWeight(row.weight)}</td>
                      <td>
                        <StatusBadge
                          status={row.quality === "LIVE" ? "ok" : row.supported ? "warning" : "error"}
                          label={qualityLabel(row.quality)}
                        />
                      </td>
                      <td>{suggestedActionLabel(row.suggested_action)}</td>
                      <td>
                        <button type="button" className="secondary" onClick={() => void removePosition(row.position_id)}>
                          Удалить
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {tab === "analysis" ? (
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

      {tab === "compare" ? (
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

      {tab === "rebalance" ? (
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
                  label="Cash-safe"
                  value={rebalance.cash_safe ? "Да" : "Нет"}
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
                      <tr key={`${row.ticker}-${row.action}`}>
                        <td className="mono">{row.ticker}</td>
                        <td>{row.action}</td>
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
