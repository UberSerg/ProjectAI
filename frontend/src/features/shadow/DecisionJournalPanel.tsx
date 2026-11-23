/** Shadow Decision Journal V4.1 — human-first expandable day cards (read-only). */

import { useEffect, useId, useRef, useState } from "react";

import { errorMessage } from "../../api/client";
import {
  getShadowCandidateHistory,
  getShadowJournal,
  type ShadowJournalDay,
  type ShadowJournalOrder,
  type ShadowJournalResponse,
} from "../../api/shadow";
import { formatDate, formatDateTime, formatMoney, formatNumber, formatPercent, formatPrice } from "../../utils/format";
import {
  dayClosedHeadline,
  dayTickers,
  dayWhatHappenedSummary,
  formatJournalDayTitle,
  hasTrustworthyNav,
  instrumentResultLabel,
  JOURNAL_MISSING_REASON_RU,
  journalCandidateHumanReason,
  journalDecisionActionLabel,
  journalOrderStatusLabel,
  journalReasonCodeLabel,
  orderLinkedFills,
  riskModeLabel,
  type JournalDayQualityView,
} from "./decisionJournalCopy";
import "./decisionJournal.css";

const ACTION_FILTER_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "Все действия" },
  { value: "BUY", label: "Покупка" },
  { value: "SELL", label: "Продажа" },
  { value: "HOLD", label: "Удержание" },
  { value: "REVIEW", label: "Проверка решения" },
  { value: "ROTATE", label: "Ротация" },
];

function CompactStats({ day }: { day: ShadowJournalDay }) {
  const c = day.counts;
  const filled = c.filled_orders ?? 0;
  const cancelled = c.cancelled_orders ?? 0;
  const pending = c.pending_orders ?? 0;
  const orders = c.orders ?? day.orders.length;
  return (
    <ul className="dj-stats" data-testid="shadow-journal-counts">
      <li>
        Заявки: <strong>{orders}</strong>
      </li>
      <li>
        Исполнено: <strong>{filled}</strong>
      </li>
      <li>
        Отменено: <strong>{cancelled}</strong>
      </li>
      {pending > 0 ? (
        <li>
          Ожидает: <strong>{pending}</strong>
        </li>
      ) : null}
    </ul>
  );
}

function PortfolioValue({ day }: { day: JournalDayQualityView }) {
  if (!hasTrustworthyNav(day) || !day.nav) {
    return (
      <p className="dj-nav-line muted" data-testid="shadow-journal-day-nav-missing">
        Общая стоимость портфеля: нет достоверной оценки на этот день
      </p>
    );
  }
  return (
    <p className="dj-nav-line" data-testid="shadow-journal-day-nav">
      Общая стоимость портфеля: <strong>{formatMoney(day.nav.nav)}</strong>
      {day.nav.drawdown != null ? (
        <span className="muted"> · просадка {formatPercent(day.nav.drawdown)}</span>
      ) : null}
    </p>
  );
}

function DataStateLine({ day }: { day: ShadowJournalDay }) {
  const level = (day.evidence_level ?? (day.detail_available ? "FULL" : "PARTIAL")).toUpperCase();
  let text = "Состояние данных: полный журнал причин";
  if (level === "PARTIAL") text = "Состояние данных: частичные исторические сведения";
  else if (level === "LIMITED") text = "Состояние данных: ограниченные сведения";
  else if (level === "NONE") text = "Состояние данных: содержательных сведений нет";
  return (
    <p className="dj-data-state muted" data-testid="shadow-journal-evidence-level">
      {text}
    </p>
  );
}

function InstrumentRow({
  day,
  order,
  expanded,
  onToggle,
}: {
  day: ShadowJournalDay;
  order: ShadowJournalOrder;
  expanded: boolean;
  onToggle: () => void;
}) {
  const fills = orderLinkedFills(order, day);
  const result = instrumentResultLabel({ ...order, fills });
  const qty = formatNumber(order.quantity);
  const panelId = `dj-instr-${order.id}`;
  const candidate = day.candidates.find(
    (c) => (c.ticker ?? "").toUpperCase() === (order.ticker ?? "").toUpperCase(),
  );
  const primaryFill = fills[0] ?? null;

  return (
    <div className="dj-instr" data-testid={`shadow-journal-order-${order.id}`}>
      <button
        type="button"
        className="dj-instr-row"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={onToggle}
        data-testid={`shadow-journal-instr-toggle-${order.ticker}`}
      >
        <span className="dj-instr-ticker">{order.ticker}</span>
        <span className="dj-instr-action">{journalDecisionActionLabel(order.side)}</span>
        <span className="dj-instr-qty">{qty} шт.</span>
        <span className={`dj-instr-result dj-tone-${result.tone}`}>{result.label}</span>
        <span className="dj-instr-chevron" aria-hidden>
          {expanded ? "▴" : "▾"}
        </span>
      </button>
      {expanded ? (
        <div id={panelId} className="dj-instr-detail" data-testid={`shadow-journal-instr-detail-${order.ticker}`}>
          <dl className="dj-kv">
            <div>
              <dt>Решение принято</dt>
              <dd>{formatDateTime(order.decision_at ?? day.decision?.decision_at)}</dd>
            </div>
            <div>
              <dt>Планируемое количество</dt>
              <dd>{qty} шт.</dd>
            </div>
            {primaryFill ? (
              <>
                <div>
                  <dt>Фактически исполнено</dt>
                  <dd>{formatNumber(primaryFill.quantity)} шт.</dd>
                </div>
                <div>
                  <dt>Цена сделки</dt>
                  <dd>{formatPrice(primaryFill.fill_price)}</dd>
                </div>
                <div>
                  <dt>Сумма</dt>
                  <dd>{formatMoney(primaryFill.notional)}</dd>
                </div>
                <div>
                  <dt>Комиссия</dt>
                  <dd>{formatMoney(primaryFill.commission)}</dd>
                </div>
                <div>
                  <dt>Дата исполнения</dt>
                  <dd>
                    {formatDate(primaryFill.execution_date)}
                    {order.execution_timing === "later" ? " · исполнено позднее даты решения" : ""}
                  </dd>
                </div>
              </>
            ) : (
              <div>
                <dt>Исполнение</dt>
                <dd>
                  {order.execution_timing === "status_fill_mismatch"
                    ? `В данных указан статус «${journalOrderStatusLabel(order.status)}», но запись исполнения не найдена.`
                    : order.status?.toUpperCase() === "CANCELLED" ||
                        order.status?.toUpperCase() === "CANCELED"
                      ? "Заявка отменена; записи исполнения нет."
                      : "Подтверждённая запись исполнения отсутствует."}
                </dd>
              </div>
            )}
            <div>
              <dt>Почему выбран инструмент</dt>
              <dd data-testid={`shadow-journal-human-reason-${order.ticker}`}>
                {candidate
                  ? journalCandidateHumanReason({
                      action: candidate.decision_action,
                      reason_codes: candidate.reason_codes,
                      replacement_ticker: candidate.replacement_ticker,
                      net_edge: candidate.net_edge,
                    })
                  : order.reason
                    ? `Сохранённый код заявки: ${journalReasonCodeLabel(order.reason)}. Подробное обоснование отбора не сохранялось.`
                    : JOURNAL_MISSING_REASON_RU}
              </dd>
            </div>
          </dl>
        </div>
      ) : null}
    </div>
  );
}

function WhyBlock({ day }: { day: ShadowJournalDay }) {
  const facts = day.recorded_facts;
  const codes = new Set<string>();
  for (const c of day.candidates) {
    for (const code of c.reason_codes ?? []) codes.add(String(code));
  }
  for (const reason of facts?.order_reasons ?? []) codes.add(String(reason));
  const targets = facts?.targets?.length ? facts.targets : day.decision?.targets ?? [];
  const hasConfirmed =
    codes.size > 0 || (targets?.length ?? 0) > 0 || (facts?.order_plan_rows?.length ?? 0) > 0;

  return (
    <section className="dj-block" data-testid="shadow-journal-block-why">
      <h4>Почему Kraken так решил</h4>
      <div className="dj-why-grid">
        <div>
          <h5>Подтверждённые причины</h5>
          {hasConfirmed ? (
            <ul className="dj-why-list">
              {Array.from(codes).map((code) => (
                <li key={code}>{journalReasonCodeLabel(code)}</li>
              ))}
              {(targets ?? []).slice(0, 12).map((t, idx) => {
                const ticker = String((t as { ticker?: string }).ticker ?? "").toUpperCase();
                const rank = (t as { rank?: number }).rank;
                const action = (t as { action?: string }).action;
                if (!ticker) return null;
                return (
                  <li key={`${ticker}-${idx}`}>
                    {ticker}
                    {rank != null ? ` · место ${rank}` : ""}
                    {action ? ` · ${journalDecisionActionLabel(action)}` : ""}
                  </li>
                );
              })}
              {facts?.policy_name ? <li>Стратегия: {facts.policy_name}</li> : null}
              {facts?.risk_name ? <li>Ограничение риска: {facts.risk_name}</li> : null}
            </ul>
          ) : (
            <p className="muted">Подтверждённых кодов причин нет.</p>
          )}
        </div>
        <div>
          <h5>Исторические ограничения</h5>
          <p data-testid="shadow-journal-missing-reason">
            {day.message_ru ||
              (day.detail_available
                ? "Доступны сохранённые факты по этому дню."
                : "Для решений этого периода не сохранялось подробное обоснование отбора каждой бумаги. При этом могли сохраниться состав заявок и параметры стратегии.")}
          </p>
        </div>
      </div>
    </section>
  );
}

function TechnicalBlock({ day, ownerMode }: { day: ShadowJournalDay; ownerMode: boolean }) {
  if (!ownerMode) return null;
  const [open, setOpen] = useState(false);
  return (
    <section className="dj-block dj-tech" data-testid="shadow-journal-block-tech">
      <button type="button" className="dj-tech-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        Технические сведения {open ? "▴" : "▾"}
      </button>
      {open ? (
        <div className="dj-tech-body">
          <dl className="dj-kv">
            <div>
              <dt>Решение Kraken (ID)</dt>
              <dd>{day.decision?.id ?? "—"}</dd>
            </div>
            <div>
              <dt>Forward Batch ID</dt>
              <dd>{day.decision?.forward_batch_id ?? "—"}</dd>
            </div>
            <div>
              <dt>Стратегия</dt>
              <dd>{day.decision?.policy_name ?? "—"}</dd>
            </div>
            <div>
              <dt>Риск-модуль</dt>
              <dd>{day.decision?.risk_name ?? "—"}</dd>
            </div>
            <div>
              <dt>ISO время решения</dt>
              <dd>{day.decision?.decision_at ?? "—"}</dd>
            </div>
          </dl>
          <ul className="dj-tech-orders">
            {day.orders.map((o) => (
              <li key={o.id}>
                {o.ticker}: заявка #{o.id}, статус {o.status}
                {(o.fills ?? []).map((f) => (
                  <span key={f.id}> · исполнение #{f.id} {f.execution_date}</span>
                ))}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function DayCard({
  day,
  expanded,
  onToggle,
  ownerMode,
}: {
  day: ShadowJournalDay;
  expanded: boolean;
  onToggle: () => void;
  ownerMode: boolean;
}) {
  const panelId = `dj-day-panel-${day.date}`;
  const tickers = dayTickers(day);
  const [openTicker, setOpenTicker] = useState<string | null>(null);
  const headline = dayClosedHeadline(day);
  const buyOrders = day.counts.buy_orders ?? day.counts.buy;

  return (
    <article className="dj-day" data-testid={`shadow-journal-day-${day.date}`}>
      <div className="dj-day-closed">
        <div className="dj-day-topline">
          <strong className="dj-day-date" data-testid="shadow-journal-day-date">
            {formatJournalDayTitle(day.date)}
          </strong>
          <span className="dj-mode" data-testid="shadow-journal-day-mode">
            {riskModeLabel(day.risk_mode ?? day.decision?.risk_mode)}
          </span>
        </div>
        <p className="dj-headline" data-testid="shadow-journal-day-headline">
          {headline}
        </p>
        {tickers.length > 0 ? (
          <p className="dj-tickers-line" data-testid="shadow-journal-day-tickers">
            Тикеры: {tickers.join(", ")}.
          </p>
        ) : null}
        <CompactStats day={day} />
        <PortfolioValue day={day} />
        <DataStateLine day={day} />
        <button
          type="button"
          className="dj-expand"
          aria-expanded={expanded}
          aria-controls={panelId}
          onClick={onToggle}
          data-testid="shadow-journal-day-expand"
        >
          {buyOrders && buyOrders > 0 ? "Почему Kraken выбрал эти бумаги?" : "Детали решения"}{" "}
          <span aria-hidden>{expanded ? "▴" : "▾"}</span>
        </button>
      </div>

      {expanded ? (
        <div id={panelId} className="dj-day-open" data-testid={`shadow-journal-day-panel-${day.date}`}>
          <section className="dj-block" data-testid="shadow-journal-block-summary">
            <h4>Что Kraken сделал?</h4>
            <p data-testid="shadow-journal-day-summary">{dayWhatHappenedSummary(day)}</p>
          </section>

          <section className="dj-block" data-testid="shadow-journal-block-instruments">
            <h4>Что произошло с бумагами</h4>
            {day.orders.length === 0 ? (
              <p className="muted" data-testid="shadow-journal-no-orders">
                Заявок за этот день нет.
              </p>
            ) : (
              <div className="dj-instr-table" role="table" aria-label="Заявки дня">
                <div className="dj-instr-head" role="row">
                  <span role="columnheader">Бумага</span>
                  <span role="columnheader">Действие</span>
                  <span role="columnheader">Количество</span>
                  <span role="columnheader">Результат</span>
                  <span aria-hidden />
                </div>
                {day.orders.map((order) => (
                  <InstrumentRow
                    key={order.id}
                    day={day}
                    order={order}
                    expanded={openTicker === order.ticker}
                    onToggle={() =>
                      setOpenTicker((cur) => (cur === order.ticker ? null : order.ticker))
                    }
                  />
                ))}
              </div>
            )}
          </section>

          <WhyBlock day={day} />
          <TechnicalBlock day={day} ownerMode={ownerMode} />
        </div>
      ) : null}
    </article>
  );
}

export function DecisionJournalPanel({
  portfolioId,
  portfolioLabel,
  ownerMode = false,
}: {
  portfolioId: number | null;
  portfolioLabel?: string;
  ownerMode?: boolean;
}) {
  const formId = useId();
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [ticker, setTicker] = useState("");
  const [action, setAction] = useState("");
  const [applied, setApplied] = useState({ dateFrom: "", dateTo: "", ticker: "", action: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [journal, setJournal] = useState<ShadowJournalResponse | null>(null);
  const [expandedDay, setExpandedDay] = useState<string | null>(null);
  const [historyTicker, setHistoryTicker] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [history, setHistory] = useState<Awaited<ReturnType<typeof getShadowCandidateHistory>> | null>(
    null,
  );
  const requestSeq = useRef(0);

  useEffect(() => {
    if (portfolioId == null) {
      setJournal(null);
      setError(null);
      setLoading(false);
      return;
    }
    const seq = ++requestSeq.current;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void getShadowJournal(
      portfolioId,
      {
        date_from: applied.dateFrom || undefined,
        date_to: applied.dateTo || undefined,
        ticker: applied.ticker || undefined,
        action: applied.action || undefined,
        limit: 60,
      },
      controller.signal,
    )
      .then((payload) => {
        if (seq !== requestSeq.current) return;
        setJournal(payload);
      })
      .catch((err) => {
        if (controller.signal.aborted || seq !== requestSeq.current) return;
        setJournal(null);
        setError(errorMessage(err));
      })
      .finally(() => {
        if (seq === requestSeq.current) setLoading(false);
      });
    return () => controller.abort();
  }, [portfolioId, applied]);

  useEffect(() => {
    setExpandedDay(null);
    setHistory(null);
    setHistoryError(null);
  }, [portfolioId]);

  if (portfolioId == null) {
    return (
      <section className="panel shadow-journal dj-panel" data-testid="shadow-decision-journal">
        <p className="muted">Выберите плечо эксперимента, чтобы открыть журнал решений.</p>
      </section>
    );
  }

  const daysDesc = [...(journal?.days ?? [])].reverse();

  return (
    <section className="panel shadow-journal dj-panel" data-testid="shadow-decision-journal">
      <header className="dj-head">
        <h2 className="sim-section-title">Журнал решений</h2>
        <p className="muted">
          Решение → заявки → исполнения → стоимость портфеля
          {portfolioLabel ? ` · ${portfolioLabel}` : ""} · portfolio_id{" "}
          <code data-testid="shadow-journal-portfolio-id">{portfolioId}</code>
        </p>
      </header>

      <form
        id={formId}
        className="dj-filters"
        data-testid="shadow-journal-filters"
        onSubmit={(e) => {
          e.preventDefault();
          setApplied({ dateFrom, dateTo, ticker: ticker.trim().toUpperCase(), action });
        }}
      >
        <label>
          С даты
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            data-testid="shadow-journal-date-from"
          />
        </label>
        <label>
          По дату
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            data-testid="shadow-journal-date-to"
          />
        </label>
        <label>
          Тикер
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="SBER"
            data-testid="shadow-journal-ticker"
          />
        </label>
        <label>
          Действие
          <select
            value={action}
            onChange={(e) => setAction(e.target.value)}
            data-testid="shadow-journal-action"
          >
            {ACTION_FILTER_OPTIONS.map((o) => (
              <option key={o.value || "all"} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" data-testid="shadow-journal-apply">
          Применить
        </button>
        <button
          type="button"
          className="secondary"
          data-testid="shadow-journal-reset"
          onClick={() => {
            setDateFrom("");
            setDateTo("");
            setTicker("");
            setAction("");
            setApplied({ dateFrom: "", dateTo: "", ticker: "", action: "" });
          }}
        >
          Сбросить
        </button>
      </form>

      {loading ? (
        <p className="muted" data-testid="shadow-journal-loading">
          Загрузка журнала…
        </p>
      ) : null}
      {error ? (
        <p className="error-text" data-testid="shadow-journal-error">
          {error}
        </p>
      ) : null}
      {!loading && !error && daysDesc.length === 0 ? (
        <p className="muted" data-testid="shadow-journal-empty">
          Нет дней журнала для выбранных фильтров.
        </p>
      ) : null}

      <div className="dj-days" data-testid="shadow-journal-days">
        {daysDesc.map((day) => (
          <DayCard
            key={day.date}
            day={day}
            expanded={expandedDay === day.date}
            onToggle={() => setExpandedDay((cur) => (cur === day.date ? null : day.date))}
            ownerMode={ownerMode}
          />
        ))}
      </div>

      <div className="dj-history" data-testid="shadow-journal-history">
        <h3>История по бумаге</h3>
        <form
          className="dj-filters"
          onSubmit={(e) => {
            e.preventDefault();
            const t = historyTicker.trim().toUpperCase();
            if (!t || portfolioId == null) return;
            setHistoryLoading(true);
            setHistoryError(null);
            void getShadowCandidateHistory(portfolioId, t)
              .then((payload) => setHistory(payload))
              .catch((err) => {
                setHistory(null);
                setHistoryError(errorMessage(err));
              })
              .finally(() => setHistoryLoading(false));
          }}
        >
          <label>
            Тикер
            <input
              value={historyTicker}
              onChange={(e) => setHistoryTicker(e.target.value)}
              placeholder="MGNT"
              data-testid="shadow-journal-history-ticker"
            />
          </label>
          <button type="submit" data-testid="shadow-journal-history-load">
            Показать
          </button>
        </form>
        {historyLoading ? <p className="muted">Загрузка…</p> : null}
        {historyError ? <p className="error-text">{historyError}</p> : null}
        {history ? (
          <ul data-testid="shadow-journal-history-events">
            {history.events.map((ev, idx) => (
              <li key={`${ev.decision_id}-${idx}`}>
                {formatDate(ev.signal_as_of_date)} · {journalDecisionActionLabel(ev.action)}
                {ev.order ? ` · заявка ${ev.order.ticker}` : ""}
                {ev.fill ? ` · исполнение ${formatDate(ev.fill.execution_date)}` : ""}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  );
}
