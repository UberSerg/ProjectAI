import type {
  ShadowDailyOperations,
  ShadowLivePosition,
  ShadowOrder,
  ShadowOrderPlanSkipped,
  ShadowPendingOrderReason,
  ShadowPortfolioSummary,
} from "../../api/shadow";
import { MetricCard } from "../../components/Ui";
import { MetricHelp } from "../../help";
import {
  formatDate,
  formatDateTime,
  formatMoney,
  formatPercent,
  formatPrice,
  formatRelativeTime,
} from "../../utils/format";
import { labels } from "../../utils/labels";
import {
  automationWarningText,
  buildDailyLifecycleSteps,
  earliestActivationIso,
  formatLotsUnits,
  isMidSessionActivation,
  mapNextSessionStage,
  nextSessionPrepCode,
  nextSessionStageTone,
  operationalStages,
  orderActionLabel,
  orderLotsFromMeta,
  pipelineWatermarks,
  readinessHeadline,
  sessionOpenIsoForDate,
  todaySessionHeadline,
} from "./helpers";

export function OperationalStage({ status }: { status?: string | null }) {
  const { items, current } = operationalStages(status);
  return (
    <div className="shadow-stage panel">
      <h2 className="sim-section-title">Текущий этап</h2>
      <ol className="shadow-stage-list">
        {items.map((item, idx) => (
          <li
            key={item.key}
            className={`shadow-stage-item${item.done ? " done" : ""}${item.current ? " current" : ""}`}
          >
            <span className="shadow-stage-marker" aria-hidden>
              {item.done ? "✓" : item.current ? "●" : "○"}
            </span>
            <span className="shadow-stage-label">{item.label}</span>
            {idx < items.length - 1 ? (
              <span className="shadow-stage-arrow" aria-hidden>
                ↓
              </span>
            ) : null}
          </li>
        ))}
      </ol>
      <p className="shadow-stage-current muted">
        Сейчас: <strong>{items.find((i) => i.key === current)?.label}</strong>
      </p>
    </div>
  );
}

export function PendingZeroState({ pendingCount }: { pendingCount: number }) {
  return (
    <div className="shadow-zero panel">
      <h2 className="sim-section-title">Сделок пока нет</h2>
      <p>
        {pendingCount > 0
          ? `Первый набор ордеров уже сформирован (${pendingCount}), но система принципиально не использует исторические цены задним числом.`
          : "Ордера ещё не сформированы."}
      </p>
      <p className="muted">
        Ордера будут исполнены только после появления первого допустимого будущего открытия рынка.
      </p>
    </div>
  );
}

export function EmptyNavHistory() {
  return (
    <div className="shadow-zero panel">
      <h2 className="sim-section-title">История NAV</h2>
      <p>
        История NAV начнёт строиться после первого реального исполнения и появления новых рыночных
        данных.
      </p>
      <p className="muted">Синтетическая или ретроспективная кривая намеренно не строится.</p>
    </div>
  );
}

export function orderSelectedTickers(orders: ShadowOrder[]): Set<string> {
  return new Set(orders.map((o) => o.ticker));
}

export function ReadinessBanner({
  ops,
  error,
}: {
  ops?: ShadowDailyOperations | null;
  error?: string | null;
}) {
  const headline = readinessHeadline(ops);
  const reasonCode = ops?.blocker_code ?? ops?.status_code;
  const reasonText = reasonCode ? labels.shadowReadinessStatus(reasonCode) : headline.short;
  const tone = headline.ready ? "success" : "warning";

  return (
    <div
      className={`panel shadow-readiness shadow-readiness-${tone}`}
      data-testid="shadow-readiness"
    >
      <div className="shadow-readiness-main">
        <span className={`badge badge-${tone}`} data-testid="shadow-readiness-badge">
          {headline.ready ? "READY" : "NOT READY"}
        </span>
        <div>
          <h2 className="sim-section-title" style={{ margin: 0 }}>
            К следующей сессии{" "}
            <MetricHelp metricId="ready_for_next_session" />
          </h2>
          <p className="shadow-readiness-reason" data-testid="shadow-readiness-reason">
            {error
              ? `Статус временно недоступен: ${error}`
              : headline.ready
                ? reasonCode === "PENDING_ORDERS_AWAITING_OPEN"
                  ? labels.shadowReadinessStatus("PENDING_ORDERS_AWAITING_OPEN")
                  : "Готов к следующей сессии"
                : reasonText}
          </p>
        </div>
      </div>
      {ops ? (
        <dl className="sim-dl shadow-readiness-meta">
          <div>
            <dt>EOD дата</dt>
            <dd>{formatDate(ops.latest_complete_eod_date)}</dd>
          </div>
          <div>
            <dt>След. сессия</dt>
            <dd>{formatDate(ops.next_execution_session)}</dd>
          </div>
          <div>
            <dt>
              Цикл <MetricHelp metricId="eod_cycle" />
            </dt>
            <dd>
              {ops.last_eod_cycle?.status ?? "—"}
              {ops.last_eod_cycle?.stale ? " · устарел" : ""}
            </dd>
          </div>
          <div>
            <dt>
              План ордеров <MetricHelp metricId="order_plan" />
            </dt>
            <dd>{ops.order_plan_status ?? "—"}</dd>
          </div>
        </dl>
      ) : null}
    </div>
  );
}

export function DailyLifecycleStrip({
  ops,
  primary,
}: {
  ops?: ShadowDailyOperations | null;
  primary?: ShadowPortfolioSummary | null;
}) {
  const steps = buildDailyLifecycleSteps({ ops, primary });
  return (
    <div className="panel shadow-lifecycle" data-testid="shadow-lifecycle-strip">
      <h2 className="sim-section-title" style={{ marginTop: 0 }}>
        Дневной цикл <MetricHelp metricId="eod_cycle" />
      </h2>
      <ol className="shadow-lifecycle-list">
        {steps.map((step, idx) => (
          <li key={step.key} className={`shadow-lifecycle-item state-${step.state}`}>
            <span className="shadow-lifecycle-label">{step.label}</span>
            {idx < steps.length - 1 ? (
              <span className="shadow-lifecycle-arrow" aria-hidden>
                →
              </span>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}

export function CashCard({ portfolio }: { portfolio: ShadowPortfolioSummary }) {
  const cash = portfolio.live?.cash ?? portfolio.cash_breakdown?.cash ?? portfolio.cash;
  const strategic = portfolio.order_plan?.strategic_cash_reserve;
  const remainder = portfolio.order_plan?.rounding_remainder;
  return (
    <div className="panel" data-testid="shadow-cash-card">
      <h2 className="sim-section-title">
        Денежные средства <MetricHelp metricId="strategic_cash" />
      </h2>
      <dl className="sim-dl">
        <div>
          <dt>Всего cash</dt>
          <dd>{formatMoney(cash)}</dd>
        </div>
        <div>
          <dt>Стратегический резерв</dt>
          <dd>{strategic == null ? "—" : formatMoney(strategic)}</dd>
        </div>
        <div>
          <dt>Остаток после лотов</dt>
          <dd>{remainder == null ? "—" : formatMoney(remainder)}</dd>
        </div>
      </dl>
    </div>
  );
}

export function PnLCards({ portfolio }: { portfolio: ShadowPortfolioSummary }) {
  const live = portfolio.live;
  const breakdown = portfolio.cash_breakdown;
  const nav = portfolio.live_nav ?? live?.nav ?? portfolio.nav;
  const initial = portfolio.initial_capital;
  const totalPnl =
    nav != null && initial != null
      ? nav - initial
      : breakdown?.realized_pnl != null && breakdown?.unrealized_pnl != null
        ? breakdown.realized_pnl + breakdown.unrealized_pnl
        : live?.unrealized_pnl;
  const unrealized = live?.unrealized_pnl ?? breakdown?.unrealized_pnl;
  const realized = live?.realized_pnl ?? breakdown?.realized_pnl;
  const fees = live?.fees_paid ?? breakdown?.fees_paid;

  return (
    <div className="card-grid sim-metrics-grid" data-testid="shadow-pnl-cards">
      <MetricCard
        label="P&L всего"
        value={totalPnl == null ? "—" : formatMoney(totalPnl)}
        helpId="realized_pnl"
      />
      <MetricCard
        label="Нереализованный"
        value={unrealized == null ? "—" : formatMoney(unrealized)}
      />
      <MetricCard
        label="Реализованный"
        value={realized == null ? "—" : formatMoney(realized)}
        helpId="realized_pnl"
      />
      <MetricCard label="Комиссии" value={fees == null ? "—" : formatMoney(fees)} />
    </div>
  );
}

export function LivePortfolioTable({
  positions,
  nav,
  quoteFallbackAt,
}: {
  positions: ShadowLivePosition[];
  nav?: number | null;
  quoteFallbackAt?: string | null;
}) {
  if (!positions.length) {
    return <p className="muted">Открытых позиций сейчас нет.</p>;
  }
  return (
    <div className="table-wrap">
      <table data-testid="shadow-live-positions">
        <thead>
          <tr>
            <th>Тикер</th>
            <th className="numeric">
              Лоты <MetricHelp metricId="lot" />
            </th>
            <th className="numeric">
              Единицы <MetricHelp metricId="lot_size" />
            </th>
            <th className="numeric">Средний вход</th>
            <th className="numeric">
              Оценка <MetricHelp metricId="live_mark" />
            </th>
            <th className="numeric">Рын. стоимость</th>
            <th className="numeric">P&amp;L</th>
            <th className="numeric">Вес</th>
            <th>Время котировки</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((row) => {
            const stale = (row.freshness ?? "").toUpperCase() === "STALE";
            const quoteAt = row.quote_time ?? row.observed_at ?? quoteFallbackAt;
            const avgEntry = row.avg_entry ?? row.entry_price;
            const weight =
              row.market_value != null && nav != null && nav !== 0
                ? row.market_value / nav
                : null;
            return (
              <tr key={`${row.instrument_id}-${row.ticker}`}>
                <td>
                  {row.ticker || "—"}
                  {stale ? (
                    <span className="shadow-badge shadow-badge-stale" data-testid="stale-badge">
                      {" "}
                      Устарела
                    </span>
                  ) : null}
                </td>
                <td className="numeric">{row.lots == null ? "—" : row.lots}</td>
                <td className="numeric">
                  {formatLotsUnits({
                    lots: row.lots,
                    lot_size: row.lot_size,
                    quantity: row.quantity,
                  })}
                </td>
                <td className="numeric">{formatPrice(avgEntry)}</td>
                <td className="numeric">{formatPrice(row.mark_price)}</td>
                <td className="numeric">{formatMoney(row.market_value)}</td>
                <td className="numeric">
                  {row.unrealized_pnl == null ? "—" : formatMoney(row.unrealized_pnl)}
                </td>
                <td className="numeric">{weight == null ? "—" : formatPercent(weight)}</td>
                <td>{quoteAt ? formatRelativeTime(quoteAt) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function PendingOrdersTable({
  orders,
  reasons,
  onSelect,
}: {
  orders: ShadowOrder[];
  reasons?: ShadowPendingOrderReason[];
  onSelect?: (order: ShadowOrder) => void;
}) {
  const pending = orders.filter((o) => o.status === "PENDING");
  const reasonById = new Map((reasons ?? []).map((r) => [r.order_id, r]));
  if (!pending.length) {
    return <p className="muted">Нет ожидающих ордеров.</p>;
  }
  return (
    <div className="table-wrap" data-testid="shadow-pending-orders">
      <table>
        <thead>
          <tr>
            <th>Тикер</th>
            <th>Действие</th>
            <th className="numeric">Лоты / единицы</th>
            <th>Сессия</th>
            <th>Статус / причина</th>
            <th>Earliest</th>
          </tr>
        </thead>
        <tbody>
          {pending.map((order) => {
            const meta = orderLotsFromMeta(order);
            const reason = reasonById.get(order.id);
            return (
              <tr
                key={order.id}
                className={onSelect ? "clickable" : undefined}
                onClick={onSelect ? () => onSelect(order) : undefined}
              >
                <td>{order.ticker}</td>
                <td>{orderActionLabel(order.side, order.status)}</td>
                <td className="numeric">
                  {formatLotsUnits({
                    lots: meta.lots,
                    lot_size: meta.lot_size,
                    quantity: meta.units ?? order.quantity,
                  })}
                </td>
                <td>
                  {reason?.session_date
                    ? formatDate(reason.session_date)
                    : formatDate(order.min_execution_date)}
                </td>
                <td>
                  {reason
                    ? labels.shadowPendingReason(reason.reason)
                    : order.status}
                </td>
                <td>{formatDate(order.min_execution_date)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function SkippedReasonsList({ skipped }: { skipped?: ShadowOrderPlanSkipped[] | null }) {
  if (!skipped?.length) {
    return <p className="muted">Пропусков по плану ордеров нет.</p>;
  }
  return (
    <ul className="plain-list" data-testid="shadow-skipped-reasons">
      {skipped.map((row, idx) => (
        <li key={`${row.ticker}-${row.reason}-${idx}`}>
          <strong>{row.ticker}</strong>: {labels.shadowSkipReason(row.reason)}
          {row.lot_size != null ? (
            <span className="muted"> · lot_size {row.lot_size}</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export function PendingReasonsList({ reasons }: { reasons: ShadowPendingOrderReason[] }) {
  if (!reasons.length) {
    return <p className="muted">Нет ожидающих ордеров с причиной ожидания.</p>;
  }
  return (
    <ul className="plain-list" data-testid="shadow-pending-reasons">
      {reasons.map((r) => (
        <li key={r.order_id}>
          <strong>{r.ticker}</strong>: {labels.shadowPendingReason(r.reason)}
          {r.session_date ? (
            <span className="muted"> · сессия {formatDate(r.session_date)}</span>
          ) : null}
          {r.delayed_observation ? (
            <span className="muted">
              {" "}
              · <MetricHelp metricId="delayed_observation" /> позднее наблюдение
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export function CompactReadinessCard({
  ops,
  error,
}: {
  ops?: ShadowDailyOperations | null;
  error?: string | null;
}) {
  const headline = readinessHeadline(ops);
  const prep = nextSessionPrepCode(ops);
  const stage = mapNextSessionStage(prep);
  const warning = automationWarningText(ops);
  const stageTone = nextSessionStageTone(stage);
  return (
    <article className="panel shadow-quotes-card" data-testid="system-shadow-readiness">
      <h2>
        Shadow · следующая сессия <MetricHelp metricId="ready_for_next_session" />
      </h2>
      {error ? (
        <p className="muted">Статус временно недоступен.</p>
      ) : !ops ? (
        <p className="muted">Загрузка…</p>
      ) : (
        <>
          <div className="key-value">
            <span>Готовность</span>
            <strong>{headline.ready ? "готов" : "требует внимания"}</strong>
          </div>
          <div className="key-value">
            <span>Стадия</span>
            <strong>
              <span className={`badge badge-${stageTone}`}>{labels.nextSessionStage(stage)}</span>
            </strong>
          </div>
          <div className="key-value">
            <span>Причина</span>
            <strong>
              {labels.shadowReadinessStatus(ops.blocker_code ?? prep)}
            </strong>
          </div>
          <div className="key-value">
            <span>EOD цикл</span>
            <strong>
              {ops.last_eod_cycle?.status ?? "—"}
              {ops.last_eod_cycle?.stale ? " · stale" : ""}
            </strong>
          </div>
          {warning ? (
            <p className="banner banner-warning" data-testid="system-automation-warning">
              {warning}
            </p>
          ) : null}
        </>
      )}
    </article>
  );
}

export function AutomationWarningBanner({ ops }: { ops?: ShadowDailyOperations | null }) {
  const warning = automationWarningText(ops);
  if (!warning) return null;
  return (
    <p className="banner banner-warning" data-testid="shadow-automation-warning">
      {warning}{" "}
      <MetricHelp metricId="research_live_mode" />
    </p>
  );
}

export function TodaySessionPanel({
  ops,
  marketSession,
  primary,
  error,
}: {
  ops?: ShadowDailyOperations | null;
  marketSession?: string | null;
  primary?: ShadowPortfolioSummary | null;
  error?: string | null;
}) {
  const today = todaySessionHeadline(ops);
  const mid = today.midSession || isMidSessionActivation(ops);
  const positions =
    primary?.live?.positions?.length ?? primary?.position_count ?? 0;
  const marks =
    (primary?.live?.positions ?? []).filter((p) => p.mark_price != null).length;
  const sessionLabel = marketSession ? labels.marketSession(marketSession) : "—";
  const activationAt =
    earliestActivationIso(ops) ?? primary?.activated_at ?? null;
  const todayOpen = sessionOpenIsoForDate(
    activationAt?.slice(0, 10) ?? ops?.latest_complete_eod_date ?? null,
  );
  const nextEligible = ops?.next_execution_session ?? null;
  const pending = ops?.pending_orders ?? primary?.pending_orders ?? 0;

  return (
    <section
      className={`panel shadow-session-panel${mid ? " shadow-session-mid" : ""}`}
      data-testid="shadow-today-session"
    >
      <header className="shadow-session-head">
        <h2 className="sim-section-title" style={{ margin: 0 }}>
          Сегодня <MetricHelp metricId="today_vs_next_session" />
        </h2>
        {mid ? (
          <span className="badge badge-warning" data-testid="shadow-today-badge">
            Mid-session
          </span>
        ) : (
          <span className="badge badge-info" data-testid="shadow-today-badge">
            Current session
          </span>
        )}
      </header>

      {error ? (
        <p className="muted">Статус сегодняшней сессии временно недоступен: {error}</p>
      ) : (
        <>
          <p className="shadow-session-title" data-testid="shadow-today-title">
            {today.title}
          </p>
          {mid ? (
            <p className="shadow-session-reason" data-testid="shadow-mid-session-reason">
              Эксперимент запущен сегодня после открытия рынка. Kraken не использует уже известную
              цену открытия задним числом.
            </p>
          ) : today.messageRu ? (
            <p className="muted" data-testid="shadow-today-message">
              {today.messageRu}
            </p>
          ) : null}

          <dl className="sim-dl shadow-session-meta">
            <div>
              <dt>Рынок</dt>
              <dd data-testid="shadow-today-market">{sessionLabel}</dd>
            </div>
            <div>
              <dt>План / ордера</dt>
              <dd>
                {pending > 0 ? `ожидают: ${pending}` : ops?.order_plan_status ?? "—"}
              </dd>
            </div>
            <div>
              <dt>Позиции / marks</dt>
              <dd>
                {positions} / {marks}
              </dd>
            </div>
            {mid ? (
              <>
                <div>
                  <dt>Активация</dt>
                  <dd data-testid="shadow-mid-activation">{formatDateTime(activationAt)}</dd>
                </div>
                <div>
                  <dt>OPEN сегодня</dt>
                  <dd data-testid="shadow-mid-today-open">{formatDateTime(todayOpen)}</dd>
                </div>
                <div>
                  <dt>Первая допустимая сессия</dt>
                  <dd data-testid="shadow-mid-next-eligible">{formatDate(nextEligible)}</dd>
                </div>
              </>
            ) : null}
          </dl>

          {mid || today.code ? (
            <details className="shadow-tech-details" data-testid="shadow-today-details">
              <summary>Технические коды</summary>
              <dl className="sim-dl">
                <div>
                  <dt>current_session_status</dt>
                  <dd>
                    <code>{today.code ?? "—"}</code>
                  </dd>
                </div>
                <div>
                  <dt>mid_session_activation</dt>
                  <dd>
                    <code>{String(Boolean(ops?.mid_session_activation ?? ops?.pipeline?.mid_session_activation))}</code>
                  </dd>
                </div>
                {today.messageRu ? (
                  <div>
                    <dt>message_ru</dt>
                    <dd>{today.messageRu}</dd>
                  </div>
                ) : null}
              </dl>
            </details>
          ) : null}
        </>
      )}
    </section>
  );
}

export function NextSessionPanel({
  ops,
  error,
}: {
  ops?: ShadowDailyOperations | null;
  error?: string | null;
}) {
  const prep = nextSessionPrepCode(ops);
  const stage = mapNextSessionStage(prep);
  const tone = nextSessionStageTone(stage);
  const summary = ops?.next_session_summary ?? ops?.pipeline?.next_session_summary;
  const marks = pipelineWatermarks(ops);
  const ready = Boolean(ops?.ready_for_next_session);

  return (
    <section
      className={`panel shadow-session-panel shadow-session-next shadow-readiness-${tone === "error" ? "warning" : tone === "success" ? "success" : "warning"}`}
      data-testid="shadow-next-session"
    >
      <header className="shadow-session-head">
        <h2 className="sim-section-title" style={{ margin: 0 }}>
          Следующая сессия <MetricHelp metricId="today_vs_next_session" />
        </h2>
        <span className={`badge badge-${tone}`} data-testid="shadow-next-stage">
          {stage}
        </span>
      </header>

      {error ? (
        <p className="muted">Статус подготовки временно недоступен: {error}</p>
      ) : !ops ? (
        <p className="muted">Загрузка…</p>
      ) : (
        <>
          <p className="shadow-session-title" data-testid="shadow-next-title">
            {labels.nextSessionStage(stage)}
          </p>
          <p className="muted" data-testid="shadow-next-message">
            {summary?.message_ru ??
              labels.shadowReadinessStatus(ops.blocker_code ?? prep) ??
              (ready ? "Готов к следующей сессии" : "Требует внимания")}
          </p>

          <dl className="sim-dl shadow-session-meta">
            <div>
              <dt>EOD дата</dt>
              <dd>{formatDate(ops.latest_complete_eod_date)}</dd>
            </div>
            <div>
              <dt>След. сессия</dt>
              <dd>{formatDate(ops.next_execution_session)}</dd>
            </div>
            <div>
              <dt>
                Цикл <MetricHelp metricId="eod_cycle" />
              </dt>
              <dd>
                {ops.last_eod_cycle?.status ?? "—"}
                {ops.last_eod_cycle?.stale ? " · устарел" : ""}
              </dd>
            </div>
            <div>
              <dt>
                План <MetricHelp metricId="order_plan" />
              </dt>
              <dd>{ops.order_plan_status ?? "—"}</dd>
            </div>
          </dl>

          <h3 className="shadow-subheading">Watermarks</h3>
          <dl className="sim-dl shadow-watermarks" data-testid="shadow-next-watermarks">
            {marks.map((m) => (
              <div key={m.key}>
                <dt>{m.label}</dt>
                <dd>{formatDate(m.value)}</dd>
              </div>
            ))}
          </dl>

          <details className="shadow-tech-details" data-testid="shadow-next-details">
            <summary>Технические коды</summary>
            <dl className="sim-dl">
              <div>
                <dt>next_session_preparation_status</dt>
                <dd>
                  <code>{prep ?? "—"}</code>
                </dd>
              </div>
              <div>
                <dt>status_code / blocker</dt>
                <dd>
                  <code>{ops.status_code ?? "—"}</code>
                  {ops.blocker_code ? (
                    <>
                      {" / "}
                      <code>{ops.blocker_code}</code>
                    </>
                  ) : null}
                </dd>
              </div>
            </dl>
          </details>
        </>
      )}
    </section>
  );
}

export function EodPipelineCard({
  ops,
  error,
}: {
  ops?: ShadowDailyOperations | null;
  error?: string | null;
}) {
  const prep = nextSessionPrepCode(ops);
  const stage = mapNextSessionStage(prep);
  const tone = nextSessionStageTone(stage);
  const marks = pipelineWatermarks(ops);
  const warning = automationWarningText(ops);

  return (
    <article className="panel shadow-quotes-card" data-testid="system-eod-pipeline">
      <h2>
        EOD pipeline <MetricHelp metricId="eod_cycle" />
      </h2>
      {error ? (
        <p className="muted">Статус временно недоступен.</p>
      ) : !ops ? (
        <p className="muted">Загрузка…</p>
      ) : (
        <>
          <div className="key-value">
            <span>Стадия</span>
            <strong>
              <span className={`badge badge-${tone}`}>{stage}</span>{" "}
              {labels.nextSessionStage(stage)}
            </strong>
          </div>
          <div className="key-value">
            <span>Код</span>
            <strong>{labels.shadowReadinessStatus(prep)}</strong>
          </div>
          <div className="key-value">
            <span>Цикл</span>
            <strong>
              {ops.last_eod_cycle?.status ?? "—"}
              {ops.last_eod_cycle?.covers_latest_eod === false ? " · не покрывает EOD" : ""}
              {ops.last_eod_cycle?.stale ? " · stale" : ""}
            </strong>
          </div>
          <h3 className="shadow-subheading" style={{ marginTop: "0.75rem" }}>
            Watermarks
          </h3>
          {marks.map((m) => (
            <div className="key-value" key={m.key}>
              <span>{m.label}</span>
              <strong>{formatDate(m.value)}</strong>
            </div>
          ))}
          {warning ? (
            <p className="banner banner-warning" data-testid="system-eod-automation-warning">
              {warning}
            </p>
          ) : null}
        </>
      )}
    </article>
  );
}
