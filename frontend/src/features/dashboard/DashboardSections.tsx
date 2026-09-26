import type { CSSProperties, ReactNode } from "react";
import { Link } from "react-router-dom";
import type { KrakenActionCard } from "./recommendations";
import type { AllocationWeights } from "./allocation";
import { formatMoney } from "../../utils/format";

export function CockpitSection({
  title,
  children,
  className = "",
  testId,
  action,
}: {
  title: string;
  children: ReactNode;
  className?: string;
  testId?: string;
  action?: ReactNode;
}) {
  return (
    <section className={`cockpit-card ${className}`.trim()} data-testid={testId}>
      <div className="cockpit-card-head">
        <h2 className="cockpit-card-title">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export function AllocationDonut({ weights }: { weights: AllocationWeights }) {
  const eq = Math.max(0, weights.equity);
  const fi = Math.max(0, weights.fixedIncome);
  const cash = Math.max(0, weights.cash);
  const sum = eq + fi + cash || 1;
  const eqP = (eq / sum) * 100;
  const fiP = (fi / sum) * 100;
  const style: CSSProperties = {
    background: `conic-gradient(
      var(--equity) 0 ${eqP}%,
      var(--fi) ${eqP}% ${eqP + fiP}%,
      var(--cash) ${eqP + fiP}% 100%
    )`,
  };
  return (
    <div className="cockpit-donut-wrap" data-testid="cockpit-allocation">
      <div className="cockpit-donut" style={style} aria-hidden>
        <div className="cockpit-donut-hole">
          <strong>100%</strong>
          <span>всего</span>
        </div>
      </div>
      <div className="cockpit-legend">
        <div className="cockpit-legend-row">
          <i className="cockpit-swatch equity" />
          <span>Акции</span>
          <strong>{(eq * 100).toFixed(0)}%</strong>
        </div>
        <div className="cockpit-legend-row">
          <i className="cockpit-swatch fi" />
          <span>Облигации</span>
          <strong>{(fi * 100).toFixed(0)}%</strong>
        </div>
        <div className="cockpit-legend-row">
          <i className="cockpit-swatch cash" />
          <span>Кэш</span>
          <strong>{(cash * 100).toFixed(0)}%</strong>
        </div>
      </div>
    </div>
  );
}

/** Honest empty — no invented NAV history curve. */
export function PerformancePanel({
  nav,
  invested,
}: {
  nav: number | null;
  invested: number | null;
}) {
  return (
    <div data-testid="cockpit-performance">
      <div className="cockpit-empty-panel">
        <strong>История стоимости пока недоступна</strong>
        {nav == null ? (
          <span>Нет текущей оценки портфеля для отображения.</span>
        ) : (
          <span>
            Текущая стоимость: {formatMoney(nav)}
            {invested != null ? ` · вложено ${formatMoney(invested)}` : ""}. График динамики
            появится после накопления истории NAV в системе.
          </span>
        )}
      </div>
    </div>
  );
}

export function ActionCards({ cards }: { cards: KrakenActionCard[] }) {
  return (
    <div className="cockpit-actions" data-testid="cockpit-actions">
      {cards.map((card) => (
        <article key={card.id} className="cockpit-action" data-testid={`cockpit-action-${card.id}`}>
          <div className="cockpit-action-body">
            <div className="cockpit-action-meta">
              <span className={`cockpit-action-tone ${card.tone}`}>{card.actionLabel}</span>
              {card.ticker ? <code className="cockpit-action-ticker">{card.ticker}</code> : null}
            </div>
            <h3>{card.title}</h3>
            <p className="cockpit-action-rationale">{card.rationale}</p>
            {card.bullets.length ? (
              <ul className="cockpit-action-bullets">
                {card.bullets.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            ) : null}
            {(card.currentWeight != null || card.targetWeight != null) && (
              <p className="cockpit-action-effect">
                {card.currentWeight != null
                  ? `Сейчас ${(card.currentWeight * 100).toFixed(1)}%`
                  : null}
                {card.currentWeight != null && card.targetWeight != null ? " → " : null}
                {card.targetWeight != null
                  ? `цель ${(card.targetWeight * 100).toFixed(1)}%`
                  : null}
              </p>
            )}
            {card.currentWeight == null && card.targetWeight == null && card.effect ? (
              <p className="cockpit-action-effect">{card.effect}</p>
            ) : null}
          </div>
          <Link className="button secondary cockpit-action-cta" to={card.href}>
            {card.cta}
          </Link>
        </article>
      ))}
    </div>
  );
}

export function RelationsPreview({
  pairCount,
  available,
  avgAbs,
  strongest,
  loading,
  error,
}: {
  pairCount: number | null;
  available: number | null;
  avgAbs: number | null;
  strongest: string | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return <div className="cockpit-empty">Загружаем связи позиций…</div>;
  }
  if (error) {
    return <div className="cockpit-empty">{error}</div>;
  }
  if (pairCount == null || available == null || available === 0) {
    return (
      <div className="cockpit-empty">
        Корреляции для текущего набора позиций пока недоступны. Это не ноль — данных нет.
      </div>
    );
  }

  const sparse = available < Math.max(3, Math.floor(pairCount * 0.4));

  return (
    <div data-testid="cockpit-relations">
      <div className="cockpit-rel-summary">
        <div className="cockpit-stat">
          <span>Пар с данными</span>
          <strong>
            {available}/{pairCount}
          </strong>
        </div>
        <div className="cockpit-stat">
          <span>Средняя |корреляция|</span>
          <strong>{avgAbs == null ? "—" : avgAbs.toFixed(2)}</strong>
        </div>
        <div className="cockpit-stat">
          <span>Сильнейшая связь</span>
          <strong title={strongest ?? undefined}>{strongest ?? "—"}</strong>
        </div>
      </div>
      {sparse ? (
        <div className="cockpit-rel-coverage">
          Покрытие связей частичное ({available} из {pairCount} пар). Полноценная матрица будет
          информативнее после большего числа рассчитанных корреляций.
        </div>
      ) : null}
      <p className="cockpit-stat-note">
        Краткая сводка по рассчитанным парам. Полная матрица — в разделе «Связи».
      </p>
      <div className="cockpit-footer-links">
        <Link className="button secondary" to="/relations">
          Открыть связи
        </Link>
      </div>
    </div>
  );
}
