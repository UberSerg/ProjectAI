/** Shadow Decision Journal V4 — expandable day cards with traceable WHY (read-only). */

import { useEffect, useId, useRef, useState } from "react";

import { errorMessage } from "../../api/client";
import {
  getShadowCandidateHistory,
  getShadowJournal,
  type ShadowCandidateHistoryResponse,
  type ShadowJournalCandidateTrace,
  type ShadowJournalDay,
  type ShadowJournalResponse,
} from "../../api/shadow";
import { formatDate, formatMoney, formatPercent, formatPrice } from "../../utils/format";
import {
  buildDecisionOrderFillChains,
  candidatePlanFields,
  dayHasWhyEvidence,
  dayHistoryKind,
  dayTickers,
  dayValuationFreshness,
  drawdownQualityWarning,
  hasTrustworthyNav,
  historyKindLabel,
  JOURNAL_MISSING_REASON_RU,
  journalCandidateHumanReason,
  journalDecisionActionLabel,
  journalReasonCodeLabel,
  riskModeLabel,
  valuationFreshnessLabel,
  type JournalDayQualityView,
} from "./decisionJournalCopy";
import "./decisionJournal.css";

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

function actionChipClass(action: string): string {
  const a = action.toUpperCase();
  if (a === "BUY" || a === "ENTER") return "dj-chip dj-chip-action-buy";
  if (a === "SELL" || a === "EXIT") return "dj-chip dj-chip-action-sell";
  if (a === "HOLD" || a === "DATA_HOLD") return "dj-chip dj-chip-action-hold";
  if (a.startsWith("REVIEW")) return "dj-chip dj-chip-action-review";
  if (a.startsWith("ROTATE")) return "dj-chip dj-chip-action-rotate";
  return "dj-chip";
}

function CountChips({ day }: { day: ShadowJournalDay }) {
  const c = day.counts;
  return (
    <div className="dj-chip-row" data-testid="shadow-journal-counts">
      <span className={actionChipClass("BUY")}>BUY {c.buy}</span>
      <span className={actionChipClass("SELL")}>SELL {c.sell}</span>
      <span className={actionChipClass("HOLD")}>HOLD {c.hold}</span>
      <span className={actionChipClass("REVIEW")}>REVIEW {c.review}</span>
      <span className="dj-chip">Ордера {c.orders}</span>
      <span className="dj-chip">Исполнения {c.fills ?? day.fills.length}</span>
    </div>
  );
}

function ClosedNavRow({ day }: { day: JournalDayQualityView }) {
  if (!hasTrustworthyNav(day) || !day.nav) {
    return <span className="dj-chip dj-chip-muted" data-testid="shadow-journal-day-nav-missing">NAV нет</span>;
  }
  const ddWarn = drawdownQualityWarning(day, day.nav);
  return (
    <>
      <span className="dj-chip" data-testid="shadow-journal-day-nav">
        NAV {formatMoney(day.nav.nav)} · кэш {formatMoney(day.nav.cash)} · DD{" "}
        {formatPercent(day.nav.drawdown)}
      </span>
      {ddWarn ? (
        <span className="dj-chip dj-chip-warn" data-testid="shadow-journal-dd-warning" title={ddWarn}>
          DD: ограничено
        </span>
      ) : null}
    </>
  );
}

function ProvenanceChips({ day }: { day: JournalDayQualityView }) {
  const kind = dayHistoryKind(day);
  const kindLabel = historyKindLabel(kind);
  const freshness = dayValuationFreshness(day);
  const freshnessLabel = valuationFreshnessLabel(freshness);
  const provenanceClass =
    kind && (kind === "LIVE" || kind === "RECORDED_LIVE")
      ? "dj-chip dj-chip-provenance-live"
      : kind && (kind.includes("COUNTERFACTUAL") || kind === "REPLAY")
        ? "dj-chip dj-chip-provenance-replay"
        : kind
          ? "dj-chip dj-chip-provenance-unknown"
          : "dj-chip";

  return (
    <>
      {kindLabel ? (
        <span className={provenanceClass} data-testid="shadow-journal-history-kind">
          {kindLabel}
        </span>
      ) : null}
      {freshnessLabel ? (
        <span className="dj-chip" data-testid="shadow-journal-valuation-freshness">
          {freshnessLabel}
        </span>
      ) : null}
    </>
  );
}

function BlockA({ day }: { day: JournalDayQualityView }) {
  const decision = day.decision;
  const kind = dayHistoryKind(day);
  const kindLabel = historyKindLabel(kind);
  const freshness = valuationFreshnessLabel(dayValuationFreshness(day));
  return (
    <section className="dj-block" data-testid="shadow-journal-block-a">
      <h4 className="dj-block-title">
        <span className="dj-block-letter">A</span>
        Что знал Kraken
      </h4>
      <dl className="dj-kv">
        <dt>Дата дня</dt>
        <dd>{formatDate(day.date)}</dd>
        <dt>Сигнал as-of</dt>
        <dd>{formatDate(day.signal_as_of_date ?? day.date)}</dd>
        {decision?.decision_at ? (
          <>
            <dt>Решение at</dt>
            <dd>{decision.decision_at}</dd>
          </>
        ) : null}
        {decision?.iso_week ? (
          <>
            <dt>Неделя</dt>
            <dd>{decision.iso_week}</dd>
          </>
        ) : null}
        {decision?.policy_name ? (
          <>
            <dt>Политика</dt>
            <dd>{decision.policy_name}</dd>
          </>
        ) : null}
        {decision?.risk_name ? (
          <>
            <dt>Риск-модуль</dt>
            <dd>{decision.risk_name}</dd>
          </>
        ) : null}
        {kindLabel ? (
          <>
            <dt>Провенанс</dt>
            <dd data-testid="shadow-journal-block-a-provenance">{kindLabel}</dd>
          </>
        ) : null}
        {freshness ? (
          <>
            <dt>Свежесть оценки</dt>
            <dd data-testid="shadow-journal-block-a-freshness">{freshness}</dd>
          </>
        ) : null}
      </dl>
    </section>
  );
}

function CandidateDecisionCard({
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
  const plan = candidatePlanFields(candidate);

  return (
    <li
      className="dj-decision-item"
      data-testid={`shadow-journal-candidate-${ticker || "unknown"}`}
    >
      <div className="dj-decision-item-head">
        {ticker ? (
          <button
            type="button"
            className="dj-ticker-btn"
            data-testid={`shadow-journal-drill-${ticker}`}
            onClick={() => onOpenHistory(ticker)}
          >
            {ticker}
          </button>
        ) : (
          <strong>—</strong>
        )}
        <span className={actionChipClass(action ?? "")}>{journalDecisionActionLabel(action)}</span>
      </div>
      <p
        className="dj-why"
        data-testid={ticker ? `shadow-journal-human-reason-${ticker}` : undefined}
      >
        {human}
      </p>
      {plan.length > 0 ? (
        <div className="dj-plan" data-testid={ticker ? `shadow-journal-plan-${ticker}` : undefined}>
          {plan.map((row) => (
            <span key={row.label} className="dj-chip dj-chip-muted">
              {row.label}: {row.value}
            </span>
          ))}
        </div>
      ) : null}
    </li>
  );
}

function BlockB({
  day,
  onOpenHistory,
}: {
  day: ShadowJournalDay;
  onOpenHistory: (ticker: string) => void;
}) {
  return (
    <section className="dj-block" data-testid="shadow-journal-block-b">
      <h4 className="dj-block-title">
        <span className="dj-block-letter">B</span>
        Что решил
      </h4>
      {day.candidates.length > 0 ? (
        <ul className="dj-decision-list" data-testid="shadow-journal-candidates">
          {day.candidates.map((c, idx) => (
            <CandidateDecisionCard
              key={`${c.ticker ?? "x"}-${c.decision_action ?? "a"}-${idx}`}
              candidate={c}
              onOpenHistory={onOpenHistory}
            />
          ))}
        </ul>
      ) : day.detail_available ? (
        <p className="muted">Кандидаты за день не сохранены.</p>
      ) : (
        <p className="muted">Детализация решения за день недоступна.</p>
      )}
    </section>
  );
}

function BlockC({ day }: { day: ShadowJournalDay }) {
  const hasWhy = dayHasWhyEvidence(day);
  const decision = day.decision;
  const codeLines = day.candidates.flatMap((c) =>
    (c.reason_codes ?? []).map((code) => ({
      ticker: (c.ticker ?? "").toUpperCase() || "—",
      code,
      label: journalReasonCodeLabel(code),
    })),
  );

  return (
    <section className="dj-block" data-testid="shadow-journal-block-c">
      <h4 className="dj-block-title">
        <span className="dj-block-letter">C</span>
        Почему
      </h4>
      {!hasWhy ? (
        <p className="muted" data-testid="shadow-journal-missing-reason">
          {day.message_ru?.trim() || JOURNAL_MISSING_REASON_RU}
        </p>
      ) : (
        <>
          {(decision?.policy_name || decision?.risk_name || day.risk_mode) && (
            <dl className="dj-kv" data-testid="shadow-journal-why-policy">
              {decision?.policy_name ? (
                <>
                  <dt>Policy</dt>
                  <dd>{decision.policy_name}</dd>
                </>
              ) : null}
              {decision?.risk_name ? (
                <>
                  <dt>Risk</dt>
                  <dd>{decision.risk_name}</dd>
                </>
              ) : null}
              {day.risk_mode || decision?.risk_mode ? (
                <>
                  <dt>Режим риска</dt>
                  <dd>{riskModeLabel(day.risk_mode ?? decision?.risk_mode)}</dd>
                </>
              ) : null}
            </dl>
          )}
          {codeLines.length > 0 ? (
            <ul className="dj-decision-list" data-testid="shadow-journal-why-codes">
              {codeLines.map((row, idx) => (
                <li key={`${row.ticker}-${row.code}-${idx}`} className="dj-decision-item">
                  <div className="dj-decision-item-head">
                    <strong>{row.ticker}</strong>
                    <span className="dj-chip dj-id">{row.code}</span>
                  </div>
                  <p className="dj-why">{row.label}</p>
                </li>
              ))}
            </ul>
          ) : !decision?.policy_name && !decision?.risk_name && !day.risk_mode ? (
            <p className="muted" data-testid="shadow-journal-missing-reason">
              {JOURNAL_MISSING_REASON_RU}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}

function BlockD({ day }: { day: ShadowJournalDay }) {
  const chains = buildDecisionOrderFillChains(day);
  const costs = day.total_modeled_costs;

  if (chains.length === 0) {
    return (
      <section className="dj-block" data-testid="shadow-journal-block-d">
        <h4 className="dj-block-title">
          <span className="dj-block-letter">D</span>
          Что произошло
        </h4>
        <p className="muted" data-testid="shadow-journal-no-orders">
          Сделок и ордеров за этот день нет.
        </p>
      </section>
    );
  }

  return (
    <section className="dj-block" data-testid="shadow-journal-block-d">
      <h4 className="dj-block-title">
        <span className="dj-block-letter">D</span>
        Что произошло
      </h4>
      <ul className="dj-chain" data-testid="shadow-journal-transactions">
        {chains.map((link, idx) => {
          const order = link.order;
          const orderId = order?.id ?? link.fills[0]?.order_id;
          return (
            <li
              key={`chain-${orderId ?? "x"}-${idx}`}
              className="dj-chain-item"
              data-testid={
                order
                  ? `shadow-journal-order-${order.id}`
                  : link.fills[0]
                    ? `shadow-journal-fill-${link.fills[0].id}`
                    : undefined
              }
            >
              <div className="dj-chain-step">
                <strong>Decision</strong>
                <span className="dj-id" data-testid={order ? `shadow-journal-decision-id-${order.decision_id}` : undefined}>
                  #{link.decisionId ?? order?.decision_id ?? "—"}
                </span>
                <span aria-hidden>→</span>
                <strong>Order</strong>
                {order ? (
                  <>
                    <span className="dj-id">#{order.id}</span>
                    <span>{order.ticker}</span>
                    <span className={actionChipClass(order.side)}>{journalDecisionActionLabel(order.side)}</span>
                    <span>× {order.quantity}</span>
                    <span className="muted">{order.status}</span>
                  </>
                ) : (
                  <span className="dj-id">#{orderId ?? "—"}</span>
                )}
              </div>
              {link.fills.length > 0 ? (
                link.fills.map((f) => (
                  <div
                    key={f.id}
                    className="dj-chain-step"
                    data-testid={`shadow-journal-fill-${f.id}`}
                  >
                    <strong>Fill</strong>
                    <span className="dj-id">#{f.id}</span>
                    <span>{f.ticker}</span>
                    <span className={actionChipClass(f.side)}>{journalDecisionActionLabel(f.side)}</span>
                    <span>
                      {f.quantity} @ {formatPrice(f.fill_price)}
                    </span>
                    <span className="muted">{formatDate(f.execution_date)}</span>
                  </div>
                ))
              ) : link.pending ? (
                <div className="dj-chain-step" data-testid={order ? `shadow-journal-pending-${order.id}` : undefined}>
                  <span className="dj-pending-label">Pending</span>
                  <span className="muted">
                    статус ордера: {order?.status ?? "PENDING"} — исполнение ещё не зафиксировано
                  </span>
                </div>
              ) : order ? (
                <div
                  className="dj-chain-step"
                  data-testid={`shadow-journal-order-outcome-${order.id}`}
                >
                  <span className="muted">
                    Исполнений за этот день нет · статус ордера: {order.status}
                  </span>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
      {(costs.total > 0 || day.fills.length > 0) && (
        <p className="muted" data-testid="shadow-journal-day-costs">
          Модельные издержки дня: комиссия {formatMoney(costs.commission)}, проскальзывание{" "}
          {formatMoney(costs.slippage_cost)}, всего {formatMoney(costs.total)}.
        </p>
      )}
    </section>
  );
}

function DayCard({
  day,
  onOpenHistory,
}: {
  day: JournalDayQualityView;
  onOpenHistory: (ticker: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const tickers = dayTickers(day);
  const mode = riskModeLabel(day.risk_mode ?? day.decision?.risk_mode);
  const ddWarn = drawdownQualityWarning(day, day.nav);

  return (
    <article className="dj-day" data-testid={`shadow-journal-day-${day.date}`}>
      <div className="dj-day-closed">
        <div className="dj-day-topline">
          <strong className="dj-day-date" data-testid="shadow-journal-day-date">
            {formatDate(day.date)}
          </strong>
          <span className="dj-chip" data-testid="shadow-journal-day-mode">
            {mode}
          </span>
          <ProvenanceChips day={day} />
        </div>

        {tickers.length > 0 ? (
          <div className="dj-chip-row" data-testid="shadow-journal-day-tickers">
            {tickers.map((t) => (
              <span key={t} className="dj-chip dj-chip-ticker">
                {t}
              </span>
            ))}
          </div>
        ) : null}

        <CountChips day={day} />

        <div className="dj-chip-row">
          <ClosedNavRow day={day} />
        </div>

        <button
          type="button"
          className="dj-cta"
          aria-expanded={open}
          aria-controls={panelId}
          data-testid="shadow-journal-day-toggle"
          onClick={() => setOpen((v) => !v)}
        >
          Детали решения
          <span className="dj-chevron" aria-hidden>
            ▾
          </span>
        </button>
      </div>

      {open ? (
        <div className="dj-day-body" id={panelId} data-testid="shadow-journal-day-expanded">
          {!day.detail_available && day.message_ru ? (
            <p className="banner banner-warning" data-testid="shadow-journal-legacy-message">
              {day.message_ru}
            </p>
          ) : null}
          {ddWarn ? (
            <p className="banner banner-warning" data-testid="shadow-journal-dd-warning-body">
              {ddWarn}
            </p>
          ) : null}
          <BlockA day={day} />
          <BlockB day={day} onOpenHistory={onOpenHistory} />
          <BlockC day={day} />
          <BlockD day={day} />
        </div>
      ) : null}
    </article>
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
  const requestSeq = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    const seq = ++requestSeq.current;
    const expectedPortfolioId = String(portfolioId);
    const expectedTicker = ticker.toUpperCase();
    setLoading(true);
    setError(null);
    setData(null);
    void getShadowCandidateHistory(portfolioId, ticker, 100, controller.signal)
      .then((resp) => {
        if (controller.signal.aborted || seq !== requestSeq.current) return;
        if (String(resp.portfolio_id) !== expectedPortfolioId) return;
        if ((resp.ticker ?? "").toUpperCase() !== expectedTicker) return;
        setData(resp);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || seq !== requestSeq.current) return;
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(errorMessage(reason));
        setLoading(false);
      });
    return () => controller.abort();
  }, [portfolioId, ticker]);

  return (
    <aside className="panel dj-history" data-testid="shadow-journal-candidate-history">
      <header className="dj-history-head">
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
            <ol className="dj-timeline" data-testid="shadow-journal-timeline">
              {data.events.map((ev, idx) => (
                <li
                  key={`${ev.decision_id}-${ev.signal_as_of_date}-${idx}`}
                  data-testid={`shadow-journal-event-${ev.signal_as_of_date}`}
                >
                  <div className="dj-timeline-meta">
                    <strong>{formatDate(ev.signal_as_of_date)}</strong>
                    <span className={actionChipClass(ev.action ?? "")}>
                      {journalDecisionActionLabel(ev.action)}
                    </span>
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

type AppliedFilters = {
  dateFrom: string;
  dateTo: string;
  ticker: string;
  action: string;
};

function filtersKey(portfolioId: string | number, applied: AppliedFilters): string {
  return [
    String(portfolioId),
    applied.dateFrom,
    applied.dateTo,
    applied.ticker,
    applied.action,
  ].join("|");
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
  const [applied, setApplied] = useState<AppliedFilters>({
    dateFrom: "",
    dateTo: "",
    ticker: "",
    action: "",
  });
  const [journal, setJournal] = useState<ShadowJournalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [drillTicker, setDrillTicker] = useState<string | null>(null);
  const requestSeq = useRef(0);
  const activeKeyRef = useRef(filtersKey(portfolioId, applied));

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
    const seq = ++requestSeq.current;
    const expectedKey = filtersKey(portfolioId, applied);
    activeKeyRef.current = expectedKey;
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
        // Ignore aborted / superseded requests (portfolio OR filter changes).
        if (controller.signal.aborted || seq !== requestSeq.current) return;
        if (activeKeyRef.current !== expectedKey) return;
        if (String(resp.portfolio_id) !== expectedPortfolioId) return;
        setJournal(resp);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || seq !== requestSeq.current) return;
        if (activeKeyRef.current !== expectedKey) return;
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(errorMessage(reason));
        setLoading(false);
      });

    return () => {
      controller.abort();
    };
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
    <div className="panel shadow-journal dj-panel" data-testid="shadow-decision-journal">
      <header className="dj-head shadow-journal-head">
        <div>
          <h2 className="sim-section-title">Журнал решений</h2>
          <p className="muted">
            Decision → кандидаты → ордера → исполнения → NAV
            {portfolioLabel ? (
              <>
                {" "}
                · плечо <strong>{portfolioLabel}</strong>
              </>
            ) : null}{" "}
            · portfolio_id <code data-testid="shadow-journal-portfolio-id">{String(portfolioId)}</code>
          </p>
        </div>
      </header>

      <form
        className="form-row dj-filters shadow-journal-filters"
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

      {loading ? (
        <p className="muted" data-testid="shadow-journal-loading">
          Загрузка журнала…
        </p>
      ) : null}
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
          <div className="dj-layout shadow-journal-layout">
            <div className="dj-days shadow-journal-days" data-testid="shadow-journal-days">
              {journal.truncated ? (
                <p className="muted">Показаны последние {journal.returned_days} дней (лимит).</p>
              ) : null}
              {journal.days.map((day) => (
                <DayCard
                  key={day.date}
                  day={day as JournalDayQualityView}
                  onOpenHistory={setDrillTicker}
                />
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
