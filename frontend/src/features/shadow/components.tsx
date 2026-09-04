import type { ShadowOrder } from "../../api/shadow";
import { operationalStages } from "./helpers";

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
            {idx < items.length - 1 ? <span className="shadow-stage-arrow" aria-hidden>↓</span> : null}
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
