import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  createPortfolioCandidateSnapshot,
  previewPortfolioCandidate,
  type PortfolioCandidate,
  type PortfolioCandidatePosition,
} from "../api/investment";
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
import { MetricHelp } from "../help";

const DEFAULT_CAPITAL = 100_000;
const MAX_CAPITAL = 100_000_000;

function TruncateReason({ text, limit = 140 }: { text: string; limit?: number }) {
  const [open, setOpen] = useState(false);
  if (!text) return <>—</>;
  if (text.length <= limit) return <>{text}</>;
  return (
    <>
      {open ? text : `${text.slice(0, limit).trimEnd()}…`}{" "}
      <button type="button" className="why-toggle" onClick={() => setOpen((v) => !v)}>
        {open ? "Свернуть" : "Ещё"}
      </button>
    </>
  );
}

function money(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return `${n.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽`;
}

function pct(weight: number | null | undefined): string {
  if (weight == null) return "—";
  return `${(weight * 100).toFixed(0)}%`;
}

function instrumentTypeLabel(p: PortfolioCandidatePosition): string {
  const asset = (p.asset_class || "").toLowerCase();
  if (asset.includes("bond") || asset.includes("fixed") || p.sleeve === "FIXED_INCOME") {
    return p.bond_type || "Облигация";
  }
  if (asset.includes("equity") || p.sleeve === "EQUITY_ALPHA") {
    return "Акция";
  }
  return p.asset_class || p.sleeve || "—";
}

function creditLabel(status: string | null | undefined): string | null {
  if (!status) return null;
  const raw = status.toUpperCase();
  if (raw === "UNKNOWN" || raw === "NOT_RATED") {
    return "Кредитное качество не подтверждено";
  }
  if (raw === "SOURCE_NOT_READY") {
    return "Кредитные данные недоступны";
  }
  if (raw === "GOVERNMENT_RUSSIAN_FEDERAL") {
    return "Государственный долг";
  }
  return status;
}

function riskStatusLabel(status: string): string | undefined {
  const raw = status.toUpperCase();
  if (raw === "RESEARCH_ONLY") return "Только исследование";
  if (raw === "APPROVED_WITH_WARNINGS") return "Допущено с предупреждениями";
  if (raw === "APPROVED") return "Допущено";
  if (raw === "BLOCKED") return "Заблокировано";
  if (raw === "INSUFFICIENT_DATA") return "Недостаточно данных";
  return undefined;
}

function parseCapitalInput(raw: string): number | null {
  const cleaned = raw.replace(/\s/g, "").replace(",", ".");
  if (!cleaned) return null;
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return null;
  return n;
}

function copyComposition(candidate: PortfolioCandidate) {
  const lines = [
    "Research Portfolio Candidate",
    `id=${candidate.candidate_id}`,
    `version=${candidate.version}`,
    `as_of=${candidate.as_of ?? ""}`,
    `capital=${candidate.capital}`,
    "ticker,instrument,type,lots,units,lot_size,price,amount,sleeve,status,executable",
    ...candidate.positions.map(
      (p) =>
        `${p.symbol},${p.display_name},${instrumentTypeLabel(p)},${p.lots},${p.units},${p.lot_size ?? ""},${p.reference_price},${p.estimated_notional},${p.sleeve},${p.risk_status},${p.executable}`,
    ),
  ];
  void navigator.clipboard.writeText(lines.join("\n"));
}

function PositionDetails({
  position,
  provenance,
}: {
  position: PortfolioCandidatePosition;
  provenance?: Record<string, unknown>;
}) {
  const credit = creditLabel(position.credit_status);
  return (
    <div className="position-details" style={{ padding: "0.75rem 0.5rem", whiteSpace: "normal" }}>
      <div className="card-grid" style={{ marginBottom: "0.75rem" }}>
        <div>
          <strong>Почему</strong>
          <p style={{ margin: "0.35rem 0 0" }}>
            {position.reason_ru || "Выбран текущей инвестиционной политикой Kraken"}
          </p>
          {position.warnings_ru?.length ? (
            <ul className="plain-list" style={{ marginTop: "0.5rem" }}>
              {position.warnings_ru.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
        </div>
        <div>
          <strong>Деньги</strong>
          <ul className="plain-list" style={{ marginTop: "0.35rem" }}>
            <li>Цена: {money(position.reference_price)}</li>
            {position.dirty_price != null ? <li>Dirty price: {money(position.dirty_price)}</li> : null}
            {position.nkd != null ? <li>НКД: {money(position.nkd)}</li> : null}
            <li>Сумма: {money(position.estimated_notional)}</li>
            <li>Комиссия (оценка): {money(position.estimated_fees)}</li>
            <li>
              Вес: цель {pct(position.target_weight)} → факт {pct(position.actual_weight)}
            </li>
            <li>
              Лоты: {position.lots}
              {position.lot_size != null ? ` × ${position.lot_size} шт.` : " (LOTSIZE неизвестен)"} (
              {position.units} ед.)
            </li>
          </ul>
        </div>
        <div>
          <strong>Риск и данные</strong>
          <ul className="plain-list" style={{ marginTop: "0.35rem" }}>
            <li>
              Статус:{" "}
              <StatusBadge
                status={position.risk_status}
                label={riskStatusLabel(position.risk_status)}
              />
            </li>
            <li>
              {position.executable
                ? "Исполняемая research-позиция (не приказ брокеру)"
                : "Только исследование — не язык покупки"}
            </li>
            {credit ? <li>{credit}</li> : null}
            {position.liquidity_status ? <li>Ликвидность: {position.liquidity_status}</li> : null}
            {position.confidence_label_ru ? (
              <li>Уверенность: {position.confidence_label_ru}</li>
            ) : null}
          </ul>
        </div>
        <div>
          <strong>Детали отбора</strong>
          <ul className="plain-list" style={{ marginTop: "0.35rem" }}>
            {position.selection_rank != null ? (
              <li>Ранг отбора: {position.selection_rank}</li>
            ) : null}
            {position.signal_semantic ? <li>Сигнал: {position.signal_semantic}</li> : null}
            {position.coupon_rate != null ? (
              <li>Купон: {position.coupon_rate.toFixed(2)}%</li>
            ) : null}
            {position.maturity_date ? <li>Погашение: {position.maturity_date}</li> : null}
            {position.yield_value != null ? (
              <li>
                Доходность:{" "}
                {(position.yield_value <= 1 ? position.yield_value * 100 : position.yield_value).toFixed(
                  2,
                )}
                %
              </li>
            ) : null}
            {provenance?.candidate_version ? (
              <li>Версия: {String(provenance.candidate_version)}</li>
            ) : null}
          </ul>
        </div>
      </div>
    </div>
  );
}

export function PortfolioCandidatePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialFromUrl = parseCapitalInput(searchParams.get("capital") ?? "");
  const [capitalInput, setCapitalInput] = useState(
    String(initialFromUrl && initialFromUrl > 0 ? Math.round(initialFromUrl) : DEFAULT_CAPITAL),
  );
  const [capital, setCapital] = useState(
    initialFromUrl && initialFromUrl > 0 ? Math.round(initialFromUrl) : DEFAULT_CAPITAL,
  );
  const [candidate, setCandidate] = useState<PortfolioCandidate | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [inputError, setInputError] = useState<string | null>(null);
  const [whyOpen, setWhyOpen] = useState(false);
  const [techOpen, setTechOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);

  const load = (nextCapital = capital, signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    previewPortfolioCandidate({ capital: nextCapital }, signal)
      .then(setCandidate)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(errorMessage(reason));
      })
      .finally(() => {
        if (!signal?.aborted) setLoading(false);
      });
  };

  useEffect(() => {
    const controller = new AbortController();
    load(capital, controller.signal);
    return () => controller.abort();
    // initial mount / capital apply only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [capital]);

  const applyCapital = () => {
    const parsed = parseCapitalInput(capitalInput);
    if (parsed == null || parsed <= 0) {
      setInputError("Введите сумму больше 0 ₽");
      return;
    }
    if (parsed > MAX_CAPITAL) {
      setInputError(`Максимум ${MAX_CAPITAL.toLocaleString("ru-RU")} ₽`);
      return;
    }
    setInputError(null);
    const next = Math.round(parsed);
    setCapitalInput(String(next));
    setSearchParams(
      (prev) => {
        const nextParams = new URLSearchParams(prev);
        nextParams.set("capital", String(next));
        return nextParams;
      },
      { replace: true },
    );
    setCapital(next);
  };

  const alloc = candidate?.allocation;
  const summary = candidate?.summary;
  const exportCsv = useMemo(() => {
    if (!candidate) return "";
    const header =
      "ticker,instrument,type,lots,units,lot_size,price,amount,sleeve,status,executable";
    const rows = candidate.positions.map(
      (p) =>
        `${p.symbol},"${p.display_name}","${instrumentTypeLabel(p)}",${p.lots},${p.units},${p.lot_size ?? ""},${p.reference_price},${p.estimated_notional},${p.sleeve},${p.risk_status},${p.executable}`,
    );
    return [header, ...rows].join("\n");
  }, [candidate]);

  if (loading && !candidate) {
    return <PageState kind="loading" title="Собираем портфель Kraken…" />;
  }
  if (error && !candidate) {
    return (
      <PageState
        kind="error"
        title="Не удалось собрать портфель"
        action={
          <button type="button" onClick={() => load()}>
            Повторить
          </button>
        }
      >
        {error}
      </PageState>
    );
  }
  if (!candidate) {
    return (
      <EmptyState
        title="Портфель пока недоступен"
        reason="Нажмите «Рассчитать портфель», когда данные Kraken будут готовы."
      />
    );
  }

  const positionsCount = summary?.positions_count ?? candidate.positions.length;
  const invested = candidate.money?.invested ?? null;
  const cashRub = summary?.cash_rub ?? candidate.cash.total_cash_rub;
  const equityRub = summary?.equity_rub ?? alloc?.equity.actual_rub;
  const fiRub = summary?.fixed_income_rub ?? alloc?.fixed_income.actual_rub;
  const equityW = alloc?.equity.actual_weight ?? 0;
  const fiW = alloc?.fixed_income.actual_weight ?? 0;
  const cashW = alloc?.cash.actual_weight ?? 0;
  const allCash = positionsCount === 0;

  return (
    <section className="portfolio-candidate-page page-layout-wide" data-layout="wide">
      <PageHeader
        title="Портфель Kraken"
        description="Введите сумму — Kraken соберёт lot-aware исследовательский портфель по текущей политике Candidate. Это не автоматическая сделка."
        helpPageId="portfolio_builder"
        actions={
          <Link className="why-toggle" to="/investment-decision">
            Как принимается решение
          </Link>
        }
      />

      <div className="ds-card ds-card-hero" style={{ marginBottom: "1rem" }}>
        <div className="ds-card-title">
          Сумма для инвестирования <MetricHelp metricId="portfolio_builder_capital" />
        </div>
        <div className="investment-calculator" style={{ marginTop: "0.75rem" }}>
          <label>
            Капитал, ₽{" "}
            <input
              type="text"
              inputMode="numeric"
              aria-label="Сумма для инвестирования"
              value={capitalInput}
              onChange={(e) => setCapitalInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") applyCapital();
              }}
            />
          </label>
          <button type="button" onClick={applyCapital} disabled={loading}>
            {loading ? "Считаем…" : "Рассчитать портфель"}
          </button>
        </div>
        {inputError ? <p className="banner banner-warning">{inputError}</p> : null}
        <p className="muted" style={{ marginBottom: 0 }}>
          Стартовое значение — 100 000 ₽. Сумма меняет число лотов, а не модель Prediction.
        </p>
      </div>

      {error ? <div className="banner banner-warning">{error}</div> : null}

      <div className="ds-card ds-card-quality" style={{ marginBottom: "1rem" }}>
        <strong>{candidate.readiness.mode_ru}</strong>
        <p className="muted" style={{ margin: "0.35rem 0 0.5rem" }}>
          {candidate.readiness.banner_ru}
        </p>
        <ul className="plain-list">
          {candidate.readiness.reasons_ru.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </div>

      <HeroCard
        eyebrow="Состав на ваш капитал"
        headline={`${money(candidate.capital)} · ${positionsCount} инструментов · ${candidate.status}`}
        actions={
          <>
            <button type="button" className="why-toggle" onClick={() => setWhyOpen((v) => !v)}>
              {whyOpen ? "Скрыть «Почему?»" : "Почему?"}
            </button>
            <button
              type="button"
              className="why-toggle"
              onClick={() => {
                copyComposition(candidate);
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? "Скопировано" : "Скопировать состав"}
            </button>
            <a
              className="why-toggle"
              href={`data:text/csv;charset=utf-8,${encodeURIComponent(exportCsv)}`}
              download={`kraken-portfolio-${candidate.candidate_id}.csv`}
            >
              Экспорт CSV
            </a>
          </>
        }
      >
        <p className="muted" style={{ marginTop: 0 }}>
          Данные на {candidate.as_of ?? "—"}. Сформирован {candidate.generated_at}.
          {candidate.freshness?.stale ? ` ${candidate.freshness.stale_note_ru}` : ""}
        </p>
        <div className="card-grid">
          <MetricCard label="Капитал" value={money(candidate.capital)} helpId="portfolio_builder_capital" />
          <MetricCard label="Вложено" value={money(invested)} helpId="concrete_portfolio" />
          <MetricCard
            label="Деньги (Cash)"
            value={money(cashRub)}
            helpId="unallocated_capital"
            hint={
              candidate.cash.constraint_unallocated_rub != null
                ? `Стратегический ${money(candidate.cash.strategic_target_rub)}; ограничения ${money(candidate.cash.constraint_unallocated_rub)}; лоты ${money(candidate.cash.lot_rounding_rub ?? candidate.cash.lot_remainder_rub)}`
                : `Целевой Cash ${money(candidate.cash.strategic_target_rub)}; остаток ${money(candidate.cash.lot_remainder_rub)}`
            }
          />
          <MetricCard label="Акции" value={money(equityRub)} helpId="portfolio_composition" />
          <MetricCard label="Облигации" value={money(fiRub)} helpId="instrument_selection" />
          <MetricCard
            label="Инструментов"
            value={String(positionsCount)}
            helpId="concrete_portfolio"
            hint={`Акции ${summary?.equity_positions ?? "—"} · Облигации ${summary?.fixed_income_positions ?? "—"}`}
          />
        </div>

        {alloc ? (
          <>
            <h3 style={{ marginBottom: "0.35rem" }}>
              Фактическое распределение <MetricHelp metricId="portfolio_builder_allocation" />
            </h3>
            <AllocationBars equity={equityW} fixedIncome={fiW} cash={cashW} />
          </>
        ) : null}

        <div className="reveal-panel" hidden={!whyOpen}>
          <ExplanationCard title="Простыми словами" level={1}>
            {candidate.level_explanations?.level_1_ru}
          </ExplanationCard>
          <ExplanationCard title="Подробнее" level={2}>
            {candidate.level_explanations?.level_2_ru}
          </ExplanationCard>
        </div>
      </HeroCard>

      {candidate.portfolio_explanation ? (
        <section style={{ marginTop: "1.25rem" }}>
          <h2>
            Почему именно такой портфель{" "}
            <MetricHelp metricId="portfolio_allocation_explanation" />
          </h2>
          <div className="card-grid" style={{ marginBottom: "1rem" }}>
            <div className="ds-card">
              <div className="ds-card-title">План Kraken</div>
              <AllocationBars
                equity={candidate.portfolio_explanation.target_allocation.equity_weight}
                fixedIncome={
                  candidate.portfolio_explanation.target_allocation.fixed_income_weight
                }
                cash={candidate.portfolio_explanation.target_allocation.cash_weight}
              />
              <p className="muted" style={{ marginBottom: 0 }}>
                Акции{" "}
                {pct(candidate.portfolio_explanation.target_allocation.equity_weight)} · Облигации{" "}
                {pct(candidate.portfolio_explanation.target_allocation.fixed_income_weight)} · Cash{" "}
                {pct(candidate.portfolio_explanation.target_allocation.cash_weight)}
              </p>
            </div>
            <div className="ds-card">
              <div className="ds-card-title">Что получилось</div>
              <AllocationBars
                equity={candidate.portfolio_explanation.actual_allocation.equity_weight}
                fixedIncome={
                  candidate.portfolio_explanation.actual_allocation.fixed_income_weight
                }
                cash={candidate.portfolio_explanation.actual_allocation.cash_weight}
              />
              <p className="muted" style={{ marginBottom: 0 }}>
                Акции {pct(candidate.portfolio_explanation.actual_allocation.equity_weight)} ·
                Облигации{" "}
                {pct(candidate.portfolio_explanation.actual_allocation.fixed_income_weight)} · Cash{" "}
                {pct(candidate.portfolio_explanation.actual_allocation.cash_weight)}
              </p>
            </div>
          </div>

          {candidate.portfolio_explanation.cash_breakdown ? (
            <div className="card-grid" style={{ marginBottom: "1rem" }}>
              <MetricCard
                label="Стратегический Cash"
                value={money(candidate.portfolio_explanation.cash_breakdown.strategic_cash_rub)}
                helpId="strategic_cash"
              />
              <MetricCard
                label="Не размещено из‑за ограничений"
                value={money(
                  candidate.portfolio_explanation.cash_breakdown.constraint_unallocated_rub,
                )}
                helpId="portfolio_allocation_explanation"
              />
              <MetricCard
                label="Остаток лотов"
                value={money(candidate.portfolio_explanation.cash_breakdown.lot_rounding_rub)}
                helpId="lot_rounding"
              />
            </div>
          ) : null}

          <h3 style={{ marginTop: 0 }}>Почему есть разница</h3>
          {candidate.portfolio_explanation.messages?.length ? (
            <div className="card-grid">
              {candidate.portfolio_explanation.messages
                .filter((m) => m.significance === "HIGH" || m.significance === "MEDIUM")
                .concat(
                  candidate.portfolio_explanation.messages.filter(
                    (m) => m.significance === "LOW",
                  ),
                )
                .slice(0, 4)
                .map((m) => (
                  <ExplanationCard key={m.code} title={m.title_ru} level={1}>
                    {m.body_ru}
                  </ExplanationCard>
                ))}
            </div>
          ) : (
            <EmptyState
              title="Существенных расхождений нет"
              reason={
                candidate.portfolio_explanation.summary_ru ||
                "Фактический состав близок к плану Kraken."
              }
            />
          )}
        </section>
      ) : null}

      <h2>Позиции</h2>
      {candidate.positions.length ? (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Инструмент</th>
                  <th>Тип</th>
                  <th>Лотов</th>
                  <th>Ед.</th>
                  <th>LOTSIZE</th>
                  <th>Цена</th>
                  <th>Сумма</th>
                  <th>Вес</th>
                  <th>Статус</th>
                  <th>Почему</th>
                </tr>
              </thead>
              <tbody>
                {candidate.positions.map((p) => {
                  const rowKey = `${p.symbol}-${p.sleeve}-${p.selection_rank ?? ""}`;
                  const open = expandedSymbol === rowKey;
                  const credit = creditLabel(p.credit_status);
                  const isResearch =
                    p.risk_status.toUpperCase() === "RESEARCH_ONLY" || !p.executable;
                  return (
                    <Fragment key={rowKey}>
                      <tr>
                        <td>
                          <button
                            type="button"
                            className="why-toggle"
                            style={{ display: "block", textAlign: "left" }}
                            onClick={() => setExpandedSymbol(open ? null : rowKey)}
                          >
                            <strong>{p.display_name}</strong>
                          </button>
                          <div className="muted">{p.symbol}</div>
                        </td>
                        <td>{instrumentTypeLabel(p)}</td>
                        <td>{p.lots}</td>
                        <td>{p.units}</td>
                        <td>{p.lot_size != null ? p.lot_size : "—"}</td>
                        <td>{money(p.reference_price)}</td>
                        <td>{money(p.estimated_notional)}</td>
                        <td>
                          {pct(p.actual_weight)}
                          <div className="muted">цель {pct(p.target_weight)}</div>
                        </td>
                        <td>
                          <StatusBadge
                            status={p.risk_status}
                            label={riskStatusLabel(p.risk_status)}
                          />
                          {isResearch ? (
                            <div className="muted">Только исследование</div>
                          ) : null}
                          {credit ? <div className="muted">{credit}</div> : null}
                        </td>
                        <td style={{ maxWidth: "16rem", whiteSpace: "normal" }}>
                          <TruncateReason
                            text={
                              p.reason_ru || "Выбран текущей инвестиционной политикой Kraken"
                            }
                          />
                          <div>
                            <button
                              type="button"
                              className="why-toggle"
                              onClick={() => setExpandedSymbol(open ? null : rowKey)}
                            >
                              {open ? "Скрыть детали" : "Детали"}
                            </button>
                          </div>
                        </td>
                      </tr>
                      {open ? (
                        <tr>
                          <td colSpan={10}>
                            <PositionDetails
                              position={p}
                              provenance={candidate.provenance}
                            />
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <EmptyState
          title={allCash ? "100% в деньгах" : "Нет рыночных позиций"}
          reason={
            candidate.empty_states?.all_cash_ru ||
            "Kraken оставил капитал в Cash — это нормальное решение политики, не ошибка экрана."
          }
        />
      )}

      <div className="card" style={{ marginTop: "1rem" }}>
        <p className="muted" style={{ marginTop: 0 }}>
          Исследовательский / advisory Candidate Kraken. Broker execution отсутствует. Не является
          индивидуальной инвестиционной рекомендацией.
        </p>
      </div>

      <h2>Риск и качество данных</h2>
      <div className="card-grid">
        <RiskCard title="Предупреждения">
          {candidate.warnings.length ? (
            <ul className="plain-list">
              {candidate.warnings.slice(0, 6).map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : (
            <p>Явных предупреждений нет — это не значит «без риска».</p>
          )}
        </RiskCard>
        <WarningCard title="Качество equity-сигнала">
          <p>
            <strong>{candidate.decision_quality.equity_confidence_label_ru}</strong>
          </p>
          <p className="muted">{candidate.decision_quality.equity_confidence_reason_ru}</p>
          <p>
            <Link to="/calibration">Качество прогнозов →</Link>
          </p>
        </WarningCard>
        <DataQualityCard title="CBR hurdle">
          <p>
            Ключевая ставка:{" "}
            {candidate.benchmark.cbr_hurdle_annual == null
              ? "нет данных"
              : `${(candidate.benchmark.cbr_hurdle_annual * 100).toFixed(2)}%`}
          </p>
          <p className="muted">{candidate.benchmark.note_ru}</p>
        </DataQualityCard>
      </div>

      {(candidate.reasons_ru?.length ?? 0) > 0 ? (
        <>
          <h2>Почему так</h2>
          <div className="card-grid">
            {candidate.reasons_ru.slice(0, 5).map((reason) => (
              <ExplanationCard key={reason.slice(0, 48)} title="Причина" level={1}>
                <TruncateReason text={reason} limit={220} />
              </ExplanationCard>
            ))}
          </div>
        </>
      ) : null}

      <div className="card" style={{ marginTop: "1rem" }}>
        <button
          type="button"
          className="why-toggle"
          onClick={() => setAdvancedOpen((v) => !v)}
        >
          {advancedOpen ? "Скрыть дополнительные детали" : "Дополнительные детали Candidate"}
        </button>
        <div className="reveal-panel" hidden={!advancedOpen}>
          <h3>Что Kraken не включил</h3>
          {candidate.rejected_candidates.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Инструмент</th>
                    <th>Возможность</th>
                    <th>Статус</th>
                    <th>Причина</th>
                  </tr>
                </thead>
                <tbody>
                  {candidate.rejected_candidates.map((r) => (
                    <tr key={`${r.symbol}-${r.reason_ru}`}>
                      <td>
                        <strong>{r.display_name}</strong>
                        <div className="muted">{r.symbol}</div>
                      </td>
                      <td>{r.opportunity_hint ?? "—"}</td>
                      <td>
                        <StatusBadge status={r.risk_status} />
                      </td>
                      <td style={{ whiteSpace: "normal", maxWidth: "22rem" }}>
                        <TruncateReason text={r.reason_ru} limit={180} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              title="Явных отклонений нет"
              reason="Либо кандидаты прошли gate как research-only, либо universe пуст."
            />
          )}

          <h3>Что изменилось</h3>
          <p>{candidate.diff?.summary_ru}</p>
          {candidate.diff?.changes?.length ? (
            <ul className="plain-list">
              {candidate.diff.changes.map((c) => (
                <li key={`${c.kind ?? "chg"}-${c.symbol ?? ""}-${c.text_ru}`}>
                  {c.text_ru}
                </li>
              ))}
            </ul>
          ) : null}

          <h3>Деньги (детально)</h3>
          <div className="card-grid">
            <MetricCard label="Инвестировано" value={money(candidate.money.invested)} />
            <MetricCard
              label="Комиссии (до налогов)"
              value={money(candidate.money.fees)}
              helpId="lot_rounding"
            />
            <MetricCard
              label="Целевой Cash"
              value={money(candidate.money.strategic_cash)}
              helpId="strategic_cash"
            />
            <MetricCard
              label="Остаток из-за лотов"
              value={money(candidate.money.lot_remainder)}
              helpId="lot_rounding"
            />
          </div>
          <p className="muted">
            {candidate.money.tax_note_ru} {candidate.money.broker_note_ru}
          </p>

          <div className="page-actions" style={{ marginTop: "0.75rem" }}>
            <button
              type="button"
              className="why-toggle"
              onClick={() =>
                createPortfolioCandidateSnapshot({ capital })
                  .then(setCandidate)
                  .catch((reason: unknown) => setError(errorMessage(reason)))
              }
            >
              Сохранить snapshot
            </button>
            <button type="button" className="why-toggle" onClick={() => setTechOpen((v) => !v)}>
              {techOpen ? "Скрыть technical details" : "Technical details"}
            </button>
          </div>
          <div className="reveal-panel" hidden={!techOpen}>
            <pre className="tech-block" style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(
                {
                  candidate_id: candidate.candidate_id,
                  version: candidate.version,
                  summary: candidate.summary,
                  composition: candidate.composition,
                  provenance: candidate.provenance,
                  level_3: candidate.level_explanations?.level_3,
                  risk_summary: candidate.risk_assessment_summary,
                },
                null,
                2,
              )}
            </pre>
            <p className="muted">
              Candidate ≠ Simulator ≠ Shadow.{" "}
              <Link to="/portfolio-risk">Проверка риска</Link>
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
