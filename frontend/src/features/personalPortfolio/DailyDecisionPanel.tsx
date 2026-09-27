import type { DailyPersonalDecision } from "../../api/dailyPersonalDecision";
import { EmptyState, MetricCard, StatusBadge } from "../../components/Ui";

function pct(w: number | null | undefined): string {
  if (w == null || Number.isNaN(w)) return "—";
  return `${(w * 100).toFixed(1)}%`;
}

function statusForBadge(status: string): string {
  if (status === "NO_ACTION" || status === "READY") return "ok";
  if (status === "PARTIAL" || status === "LEGACY_PENDING" || status === "NEEDS_SETUP") return "warning";
  if (status === "UNAVAILABLE") return "error";
  return "unknown";
}

export function DailyDecisionPanel({
  decision,
  owner = false,
}: {
  decision: DailyPersonalDecision | null;
  owner?: boolean;
}) {
  if (!decision) {
    return (
      <EmptyState
        title="Решение пока недоступно"
        reason="Kraken не смог собрать персональное решение. Обновите страницу или откройте состав портфеля."
      />
    );
  }

  return (
    <div className="stack-lg" data-testid="daily-decision-panel">
      <div className="panel">
        <div className="row-between">
          <div>
            <h2 data-testid="daily-decision-headline">{decision.headline}</h2>
            <p className="muted">{decision.summary}</p>
          </div>
          <StatusBadge status={statusForBadge(decision.status)} label={decision.status} />
        </div>
        <div className="metric-grid" style={{ marginTop: "1rem" }}>
          <MetricCard label="NAV" value={`${Number(decision.portfolio.nav_rub).toLocaleString("ru-RU")} ₽`} />
          <MetricCard label="Кэш" value={`${Number(decision.portfolio.cash_rub).toLocaleString("ru-RU")} ₽`} />
          <MetricCard
            label="Оценка"
            value={decision.data_quality.valuation_label || "—"}
          />
        </div>
        {decision.data_quality.valuation_partial ? (
          <p className="warning-text" data-testid="daily-decision-partial">
            Частичная оценка: точные веса и инвестиционный результат недоступны. Неизвестная цена не считается нулём.
          </p>
        ) : null}
      </div>

      <div className="panel">
        <h3>Действия</h3>
        {decision.actions.length === 0 ? (
          <p className="muted">Нет действий</p>
        ) : (
          <ul className="decision-action-list" data-testid="daily-decision-actions">
            {decision.actions.map((a) => (
              <li key={a.id} className="decision-action-item" data-testid={`daily-action-${a.action}`}>
                <div className="row-between">
                  <strong>{a.title}</strong>
                  <span className="chip">{a.priority}</span>
                </div>
                <p>{a.rationale}</p>
                <ul className="muted">
                  {a.facts.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
                {(a.current_weight != null || a.target_weight != null) && (
                  <p className="muted">
                    Вес: {pct(a.current_weight)} → {pct(a.target_weight)}
                  </p>
                )}
                {owner && a.reason_codes?.length ? (
                  <p className="muted" data-testid="daily-action-codes">
                    codes: {a.reason_codes.join(", ")}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      {decision.risks.length > 0 ? (
        <div className="panel">
          <h3>Риски и предупреждения</h3>
          <ul data-testid="daily-decision-risks">
            {decision.risks.map((r, i) => (
              <li key={`${r.code}-${i}`}>
                {r.symbol ? <strong>{r.symbol}: </strong> : null}
                {r.message || r.code}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="panel">
        <h3>Контекст</h3>
        <p className="muted">
          Кандидат: {decision.context.candidate_source || "—"}
          {decision.context.candidate_id ? ` · ${decision.context.candidate_id}` : ""}
        </p>
        <p className="muted">На дату: {decision.as_of}</p>
        {decision.context.what_can_change_decision?.length ? (
          <div>
            <p>Что может изменить решение:</p>
            <ul className="muted">
              {decision.context.what_can_change_decision.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <p className="muted" data-testid="daily-decision-disclaimer">
          {decision.disclaimer}
        </p>
      </div>
    </div>
  );
}
