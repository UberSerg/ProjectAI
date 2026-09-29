/** Shadow Decision Journal — day view + candidate drill-down (read-only). */

import { useEffect, useId, useState } from "react";

import { errorMessage } from "../../api/client";
import {
  getShadowCandidateHistory,
  getShadowJournal,
  type ShadowCandidateHistoryResponse,
  type ShadowJournalCandidateTrace,
  type ShadowJournalDay,
  type ShadowJournalFill,
  type ShadowJournalOrder,
  type ShadowJournalResponse,
} from "../../api/shadow";
import { formatDate, formatMoney, formatPercent, formatPrice } from "../../utils/format";
import {
  journalCandidateHumanReason,
  journalDecisionActionLabel,
  journalReasonCodeLabel,
  riskModeLabel,
} from "./helpers";

const ACTION_FILTER_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "Все действия" },
  { value: "BUY", label: "Покупка / вход" },
  { value: "SELL", label: "Продажа / выход" },
  { value: "HOLD", label: "Удержание" },
  { value: "REVIEW", label: "Ревизия" },
  { value: "ROTATE", label: "Ротация" },
  { value: "ENTER", label: "ENTER" },
  { value: "EXIT", label: "EXIT" },
];

function CountChips({ day }: { day: ShadowJournalDay }) {
  const c = day.counts;
  return (
    <div className="shadow-journal-counts" data-testid="shadow-journal-counts">
      <span className="sim-meta-chip">BUY {c.buy}</span>
      <span className="sim-meta-chip">SELL {c.sell}</span>
      <span className="sim-meta-chip">HOLD {c.hold}</span>
      <span className="sim-meta-chip">REVIEW {c.review}</span>
      <span className="sim-meta-chip">Ордера {c.orders}</span>
      <span className="sim-meta-chip">Исполнения {c.fills ?? day.fills.length}</span>
    </div>
  );
}

function TransactionsTable({
  fills,
  orders,
}: {
  fills: ShadowJournalFill[];
  orders: ShadowJournalOrder[];
}) {
  const fillOrderIds = new Set(fills.map((f) => f.order_id));
  const pendingOrders = orders.filter((o) => !fillOrderIds.has(o.id));

  if (!fills.length && !pendingOrders.length) {
    return <p className="muted">Сделок и ордеров за этот день нет.</p>;
  }

  return (
    <div className="table-wrap" data-testid="shadow-journal-transactions">
      <table className="data-table">
        <thead>
          <tr>
            <th>Тип</th>
            <th>Тикер</th>
            <th>Сторона</th>
            <th>Кол-во</th>
            <th>Цена</th>
            <th>Нотионал</th>
            <th>Комиссия</th>
            <th>Проскальз.</th>
            <th>Дата</th>
            <th>Статус</th>
          </tr>
        </thead>
        <tbody>
          {fills.map((f) => (
            <tr key={`fill-${f.id}`} data-testid={`shadow-journal-fill-${f.id}`}>
              <td>Исполнение</td>
              <td>{f.ticker}</td>
              <td>{journalDecisionActionLabel(f.side)}</td>
              <td>{f.quantity}</td>
              <td>{formatPrice(f.fill_price)}</td>
              <td>{formatMoney(f.notional)}</td>
              <td>{formatMoney(f.commission)}</td>
              <td>{formatMoney(f.slippage_cost)}</td>
              <td>{formatDate(f.execution_date)}</td>
              <td>FILLED</td>
            </tr>
          ))}
          {pendingOrders.map((o) => (
            <tr key={`order-${o.id}`} data-testid={`shadow-journal-order-${o.id}`}>
              <td>Ордер</td>
              <td>{o.ticker}</td>
              <td>{journalDecisionActionLabel(o.side)}</td>
              <td>{o.quantity}</td>
              <td>—</td>
              <td>{formatMoney(o.target_notional)}</td>
              <td>—</td>
              <td>—</td>
              <td>{formatDate(o.execution_date ?? o.min_execution_date)}</td>
              <td>{o.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CandidateRow({
  candidate,
  onOpenHistory,
}: {
  candidate: ShadowJournalCandidateTrace;
  onOpenHistory: (ticker: string) => void;
}) {
  const ticker = (candidate.ticker ?? "").toUpperCase();
  const action = candidate.decision_action ?? null;
  const human = journalCandidateHumanReason({
    action,
    reason_codes: candidate.reason_codes,
    replacement_ticker: candidate.replacement_ticker,
    net_edge: candidate.net_edge,
  });
  const showHuman =
    (action ?? "").toUpperCase().startsWith("REVIEW") ||
    (action ?? "").toUpperCase().startsWith("ROTATE");

  return (
    <tr data-testid={`shadow-journal-candidate-${ticker || "unknown"}`}>
      <td>
        {ticker ? (
          <button
            type="button"
            className="shadow-journal-ticker-btn"
            data-testid={`shadow-journal-drill-${ticker}`}
            onClick={() => onOpenHistory(ticker)}
          >
            {ticker}
          </button>
        ) : (
          "—"
        )}
      </td>
      <td>{journalDecisionActionLabel(action)}</td>
      <td>{candidate.rank ?? "—"}</td>
      <td>
        {candidate.net_edge != null && Number.isFinite(candidate.net_edge)
          ? formatPercent(candidate.net_edge)
          : "—"}
      </td>
      <td className="shadow-journal-reason-cell">
        {showHuman ? (
          <span data-testid={`shadow-journal-human-reason-${ticker}`}>{human}</span>
        ) : (
          <span className="muted">
            {(candidate.reason_codes ?? []).map(journalReasonCodeLabel).join("; ") || "—"}
          </span>
        )}
      </td>
    </tr>
  );
}

function DayCard({
  day,
  onOpenHistory,
}: {
  day: ShadowJournalDay;
  onOpenHistory: (ticker: string) => void;
}) {
  const costs = day.total_modeled_costs;
  const decision = day.decision;

  return (
    <details className="shadow-journal-day" data-testid={`shadow-journal-day-${day.date}`}>
      <summary className="shadow-journal-day-summary">
        <div className="shadow-journal-day-head">
          <strong data-testid="shadow-journal-day-date">{formatDate(day.date)}</strong>
          <span className="muted">
            Сигнал: {formatDate(day.signal_as_of_date ?? day.date)}
            {decision?.iso_week ? ` · ${decision.iso_week}` : ""}
          </span>
          <span className="sim-meta-chip">{riskModeLabel(day.risk_mode ?? decision?.risk_mode)}</span>
          {day.nav ? (
            <span className="sim-meta-chip" data-testid="shadow-journal-day-nav">
              NAV {formatMoney(day.nav.nav)} · кэш {formatMoney(day.nav.cash)} · DD{" "}
              {formatPercent(day.nav.drawdown)}
            </span>
          ) : (
            <span className="sim-meta-chip muted">NAV нет</span>
          )}
        </div>
        <CountChips day={day} />
      </summary>

      <div className="shadow-journal-day-body">
        {!day.detail_available && day.message_ru ? (
          <p className="banner banner-warning" data-testid="shadow-journal-legacy-message">
            {day.message_ru}
          </p>
        ) : null}

        {day.candidates.length > 0 ? (
          <>
            <h4 className="shadow-subheading">Кандидаты решения</h4>
            <div className="table-wrap">
              <table className="data-table" data-testid="shadow-journal-candidates">
                <thead>
                  <tr>
                    <th>Тикер</th>
                    <th>Действие</th>
                    <th>Ранг</th>
                    <th>Net edge</th>
                    <th>Причина</th>
                  </tr>
                </thead>
                <tbody>
                  {day.candidates.map((c, idx) => (
                    <CandidateRow
                      key={`${c.ticker ?? "x"}-${c.decision_action ?? "a"}-${idx}`}
                      candidate={c}
                      onOpenHistory={onOpenHistory}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : day.detail_available ? (
          <p className="muted">Кандидаты за день не сохранены.</p>
        ) : null}

        <h4 className="shadow-subheading">Сделки и ордера</h4>
        <TransactionsTable fills={day.fills} orders={day.orders} />

        {(costs.total > 0 || day.fills.length > 0) && (
          <p className="muted" data-testid="shadow-journal-day-costs">
            Модельные издержки дня: комиссия {formatMoney(costs.commission)}, проскальзывание{" "}
            {formatMoney(costs.slippage_cost)}, всего {formatMoney(costs.total)}.
          </p>
        )}
      </div>
    </details>
  );
}

function CandidateHistoryPanel({
  portfolioId,
  ticker,
  onClose,
}: {
  portfolioId: string | number;
  ticker: string;
  onClose: () => void;
}) {
  const [data, setData] = useState<ShadowCandidateHistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setData(null);
    void getShadowCandidateHistory(portfolioId, ticker, 100, controller.signal)
      .then((resp) => {
        setData(resp);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(errorMessage(reason));
        setLoading(false);
      });
    return () => controller.abort();
  }, [portfolioId, ticker]);

  return (
    <aside className="shadow-journal-history panel" data-testid="shadow-journal-candidate-history">
      <header className="shadow-journal-history-head">
        <h3 className="sim-section-title" style={{ margin: 0 }}>
          История кандидата {ticker}
        </h3>
        <button type="button" className="secondary" onClick={onClose} data-testid="shadow-journal-history-close">
          Закрыть
        </button>
      </header>
      {loading ? <p className="muted">Загрузка истории…</p> : null}
      {error ? <p className="banner banner-warning">{error}</p> : null}
      {data && !data.detail_available && data.message_ru ? (
        <p className="banner banner-warning" data-testid="shadow-journal-history-legacy">
          {data.message_ru}
        </p>
      ) : null}
      {data ? (
        <>
          <p className="muted" data-testid="shadow-journal-history-summary">
            Событий: {data.summary.event_count}
            {data.summary.first_seen ? ` · с ${formatDate(data.summary.first_seen)}` : ""}
            {data.summary.last_seen ? ` · по ${formatDate(data.summary.last_seen)}` : ""}
          </p>
          {data.events.length === 0 ? (
            <p className="muted">Событий по тикеру нет.</p>
          ) : (
            <ol className="shadow-journal-timeline" data-testid="shadow-journal-timeline">
              {data.events.map((ev, idx) => (
                <li
                  key={`${ev.decision_id}-${ev.signal_as_of_date}-${idx}`}
                  data-testid={`shadow-journal-event-${ev.signal_as_of_date}`}
                >
                  <div className="shadow-journal-timeline-meta">
                    <strong>{formatDate(ev.signal_as_of_date)}</strong>
                    <span className="sim-meta-chip">{journalDecisionActionLabel(ev.action)}</span>
                    {ev.rank != null ? <span className="muted">ранг {ev.rank}</span> : null}
                  </div>
                  {!ev.detail_available && ev.message_ru ? (
                    <p className="muted">{ev.message_ru}</p>
                  ) : (
                    <p data-testid={`shadow-journal-event-reason-${ev.signal_as_of_date}`}>
                      {journalCandidateHumanReason({
                        action: ev.action,
                        reason_codes: ev.reason_codes,
                        replacement_ticker: ev.replacement_ticker,
                        net_edge: ev.net_edge,
                      })}
                    </p>
                  )}
                  {ev.fill ? (
                    <p className="muted">
                      Исполнение: {journalDecisionActionLabel(ev.fill.side)} {ev.fill.quantity} @{" "}
                      {formatPrice(ev.fill.fill_price)} ({formatDate(ev.fill.execution_date)})
                    </p>
                  ) : ev.order ? (
                    <p className="muted">
                      Ордер: {journalDecisionActionLabel(ev.order.side)} {ev.order.quantity} ·{" "}
                      {ev.order.status}
                    </p>
                  ) : null}
                </li>
              ))}
            </ol>
          )}
        </>
      ) : null}
    </aside>
  );
}

export function DecisionJournalPanel({
  portfolioId,
  portfolioLabel,
}: {
  portfolioId: string | number;
  portfolioLabel?: string | null;
}) {
  const formId = useId();
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [ticker, setTicker] = useState("");
  const [action, setAction] = useState("");
  const [applied, setApplied] = useState({ dateFrom: "", dateTo: "", ticker: "", action: "" });
  const [journal, setJournal] = useState<ShadowJournalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [drillTicker, setDrillTicker] = useState<string | null>(null);

  // Clear drill-down / filters when portfolio arm changes (no stale cross-portfolio journal).
  useEffect(() => {
    setDrillTicker(null);
    setJournal(null);
    setError(null);
    setLoading(true);
    setDateFrom("");
    setDateTo("");
    setTicker("");
    setAction("");
    setApplied({ dateFrom: "", dateTo: "", ticker: "", action: "" });
  }, [portfolioId]);

  useEffect(() => {
    const controller = new AbortController();
    const expectedPortfolioId = String(portfolioId);
    setLoading(true);
    setError(null);
    void getShadowJournal(
      portfolioId,
      {
        date_from: applied.dateFrom || undefined,
        date_to: applied.dateTo || undefined,
        ticker: applied.ticker.trim() || undefined,
        action: applied.action || undefined,
        limit: 60,
      },
      controller.signal,
    )
      .then((resp) => {
        // Ignore late responses if portfolio already switched.
        if (String(resp.portfolio_id) !== expectedPortfolioId) return;
        setJournal(resp);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        if (String(portfolioId) !== expectedPortfolioId) return;
        setError(errorMessage(reason));
        setLoading(false);
      });
    return () => controller.abort();
  }, [portfolioId, applied]);

  const applyFilters = () => {
    setDrillTicker(null);
    setApplied({
      dateFrom,
      dateTo,
      ticker: ticker.trim().toUpperCase(),
      action,
    });
  };

  const resetFilters = () => {
    setDateFrom("");
    setDateTo("");
    setTicker("");
    setAction("");
    setDrillTicker(null);
    setApplied({ dateFrom: "", dateTo: "", ticker: "", action: "" });
  };

  return (
    <div className="panel shadow-journal" data-testid="shadow-decision-journal">
      <header className="shadow-journal-head">
        <div>
          <h2 className="sim-section-title">Журнал решений</h2>
          <p className="muted">
            Факты Decision → кандидаты → ордера → исполнения → NAV
            {portfolioLabel ? (
              <>
                {" "}
                · плечо <strong>{portfolioLabel}</strong>
              </>
            ) : null}
            {" "}
            · portfolio_id <code data-testid="shadow-journal-portfolio-id">{String(portfolioId)}</code>
          </p>
        </div>
      </header>

      <form
        className="form-row shadow-journal-filters"
        data-testid="shadow-journal-filters"
        onSubmit={(e) => {
          e.preventDefault();
          applyFilters();
        }}
      >
        <label htmlFor={`${formId}-from`}>
          С даты
          <input
            id={`${formId}-from`}
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            data-testid="shadow-journal-date-from"
          />
        </label>
        <label htmlFor={`${formId}-to`}>
          По дату
          <input
            id={`${formId}-to`}
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            data-testid="shadow-journal-date-to"
          />
        </label>
        <label htmlFor={`${formId}-ticker`}>
          Тикер
          <input
            id={`${formId}-ticker`}
            type="text"
            value={ticker}
            placeholder="SBER"
            autoComplete="off"
            onChange={(e) => setTicker(e.target.value)}
            data-testid="shadow-journal-ticker"
          />
        </label>
        <label htmlFor={`${formId}-action`}>
          Действие
          <select
            id={`${formId}-action`}
            value={action}
            onChange={(e) => setAction(e.target.value)}
            data-testid="shadow-journal-action"
          >
            {ACTION_FILTER_OPTIONS.map((opt) => (
              <option key={opt.value || "all"} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" data-testid="shadow-journal-apply">
          Применить
        </button>
        <button type="button" className="secondary" onClick={resetFilters} data-testid="shadow-journal-reset">
          Сбросить
        </button>
      </form>

      {loading ? <p className="muted" data-testid="shadow-journal-loading">Загрузка журнала…</p> : null}
      {error ? (
        <p className="banner banner-warning" data-testid="shadow-journal-error">
          {error}
        </p>
      ) : null}

      {!loading && !error && journal ? (
        journal.days.length === 0 ? (
          <p className="muted" data-testid="shadow-journal-empty">
            За выбранный период дней журнала нет.
          </p>
        ) : (
          <div className="shadow-journal-layout">
            <div className="shadow-journal-days" data-testid="shadow-journal-days">
              {journal.truncated ? (
                <p className="muted">Показаны последние {journal.returned_days} дней (лимит).</p>
              ) : null}
              {journal.days.map((day) => (
                <DayCard key={day.date} day={day} onOpenHistory={setDrillTicker} />
              ))}
            </div>
            {drillTicker ? (
              <CandidateHistoryPanel
                key={`${portfolioId}-${drillTicker}`}
                portfolioId={portfolioId}
                ticker={drillTicker}
                onClose={() => setDrillTicker(null)}
              />
            ) : null}
          </div>
        )
      ) : null}
    </div>
  );
}
