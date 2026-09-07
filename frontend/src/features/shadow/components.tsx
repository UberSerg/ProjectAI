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
import { formatDate, formatMoney, formatPercent, formatPrice, formatRelativeTime } from "../../utils/format";
import { labels } from "../../utils/labels";
import {
  buildDailyLifecycleSteps,
  formatLotsUnits,
  operationalStages,
  orderActionLabel,
  orderLotsFromMeta,
  readinessHeadline,
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
            <span>Причина</span>
            <strong>
              {labels.shadowReadinessStatus(ops.blocker_code ?? ops.status_code)}
            </strong>
          </div>
          <div className="key-value">
            <span>EOD цикл</span>
            <strong>
              {ops.last_eod_cycle?.status ?? "—"}
              {ops.last_eod_cycle?.stale ? " · stale" : ""}
            </strong>
          </div>
        </>
      )}
    </article>
  );
}
