import { useEffect, useRef, useState } from "react";
import {
  getDailyPersonalDecision,
  type DailyPersonalDecision,
  type DecisionScenario,
} from "../../api/dailyPersonalDecision";
import { EmptyState, MetricCard, StatusBadge } from "../../components/Ui";

function pct(w: number | null | undefined): string {
  if (w == null || Number.isNaN(w)) return "—";
  return `${(w * 100).toFixed(1)}%`;
}

function money(v: string | number | null | undefined): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return `${n.toLocaleString("ru-RU")} ₽`;
}

function statusForBadge(status: string): string {
  if (status === "NO_ACTION" || status === "READY") return "ok";
  if (status === "PARTIAL" || status === "LEGACY_PENDING" || status === "NEEDS_SETUP" || status === "DRAFT_ANALYSIS") {
    return "warning";
  }
  if (status === "UNAVAILABLE") return "error";
  return "unknown";
}

function ScenarioCard({ scenario }: { scenario: DecisionScenario }) {
  const unavailable = scenario.status === "unavailable" || scenario.status === "degraded";
  return (
    <li className="decision-action-item" data-testid={`decision-scenario-${scenario.id}`}>
      <div className="row-between">
        <strong>{scenario.title}</strong>
        <span className="chip">{scenario.status}</span>
      </div>
      {unavailable && scenario.reason ? <p className="muted">{scenario.reason}</p> : null}
      {!unavailable ? (
        <>
          <p className="muted">
            Целевой объём: {money(scenario.target_allocation_rub ?? scenario.deployed_rub)}
            {" · "}
            Можно оценить по лотам: {money(scenario.executable_notional_rub ?? "0")}
            {scenario.advisory_only_rub != null && Number(scenario.advisory_only_rub) > 0
              ? ` · Только ориентир: ${money(scenario.advisory_only_rub)}`
              : ""}
            {" · "}
            Остаётся: {money(
              scenario.id === "DO_NOTHING"
                ? scenario.external_unallocated_rub
                : scenario.residual_cash_rub,
            )}
            {scenario.cash_share != null ? ` · кэш ≈ ${pct(scenario.cash_share)}` : ""}
          </p>
          {scenario.purchases && scenario.purchases.length > 0 ? (
            <ul className="muted" data-testid={`decision-scenario-purchases-${scenario.id}`}>
              {scenario.purchases.map((p, idx) => (
                <li key={`${p.symbol || p.sleeve || "row"}-${idx}`}>
                  {p.symbol || p.sleeve || "план"}: Целевой объём {money(p.target_rub)}
                  {p.lots != null ? ` · лотов ${p.lots}` : p.limitations?.includes("LOT_SIZE_UNKNOWN") ? " · лот неизвестен" : ""}
                  {p.executable_estimated_notional_rub || p.estimated_notional
                    ? ` · Можно оценить по лотам ${money(p.executable_estimated_notional_rub || p.estimated_notional)}`
                    : ""}
                  {p.limitations?.includes("ADVISORY_ONLY_BOND_TRADE") || p.execution_status === "ADVISORY_ONLY"
                    ? " · Только ориентир"
                    : ""}
                  {p.residual_cash_rub || p.residual_unexecuted_rub
                    ? ` · Остаётся ${money(p.residual_unexecuted_rub || p.residual_cash_rub)}`
                    : ""}
                </li>
              ))}
            </ul>
          ) : null}
          {scenario.facts?.length ? (
            <ul className="muted">
              {scenario.facts.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
      {scenario.limitations?.length ? (
        <p className="muted">Ограничения: {scenario.limitations.join(", ")}</p>
      ) : null}
      {scenario.cbr_context?.wording ? <p className="muted">{scenario.cbr_context.wording}</p> : null}
    </li>
  );
}

export function DailyDecisionPanel({
  decision,
  owner = false,
  portfolioId,
  onDecisionChange,
}: {
  decision: DailyPersonalDecision | null;
  owner?: boolean;
  portfolioId?: number | null;
  onDecisionChange?: (next: DailyPersonalDecision | null) => void;
}) {
  const [cashInput, setCashInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [view, setView] = useState<DailyPersonalDecision | null>(decision);
  const reqSeq = useRef(0);
  const portfolioRef = useRef(portfolioId);

  useEffect(() => {
    setView(decision);
  }, [decision]);

  useEffect(() => {
    if (portfolioRef.current !== portfolioId) {
      // Portfolio switch: clear prior plan and in-flight calculation.
      reqSeq.current += 1;
      setCashInput("");
      setLocalError(null);
      setBusy(false);
      setView(decision);
      portfolioRef.current = portfolioId;
    }
  }, [portfolioId, decision]);

  async function calculate() {
    if (portfolioId == null) return;
    const raw = cashInput.trim() === "" ? "0" : cashInput.trim();
    const amount = Number(raw.replace(",", "."));
    if (!Number.isFinite(amount) || amount < 0) {
      setLocalError("Введите неотрицательную сумму в рублях");
      return;
    }
    const seq = ++reqSeq.current;
    const controller = new AbortController();
    setBusy(true);
    setLocalError(null);
    try {
      const next = await getDailyPersonalDecision(portfolioId, {
        signal: controller.signal,
        newCashRub: amount > 0 ? amount : null,
      });
      if (seq !== reqSeq.current) return;
      setView(next);
      onDecisionChange?.(next);
    } catch (err) {
      if (seq !== reqSeq.current) return;
      setLocalError(err instanceof Error ? err.message : "Не удалось рассчитать сценарии");
    } finally {
      if (seq === reqSeq.current) setBusy(false);
    }
  }

  if (!view) {
    return (
      <EmptyState
        title="Решение пока недоступно"
        reason="Kraken не смог собрать персональное решение. Обновите страницу или откройте состав портфеля."
      />
    );
  }

  const scenarios = view.scenario_comparison || [];

  return (
    <div className="stack-lg" data-testid="daily-decision-panel">
      <div className="panel">
        <div className="row-between">
          <div>
            <h2 data-testid="daily-decision-headline">{view.headline}</h2>
            <p className="muted">{view.summary}</p>
          </div>
          <StatusBadge status={statusForBadge(view.status)} label={view.status} />
        </div>
        <div className="metric-grid" style={{ marginTop: "1rem" }}>
          <MetricCard label="NAV" value={money(view.portfolio.nav_rub)} />
          <MetricCard label="Кэш" value={money(view.portfolio.cash_rub)} />
          <MetricCard label="Оценка" value={view.data_quality.valuation_label || "—"} />
        </div>
        {view.data_quality.valuation_partial ? (
          <p className="warning-text" data-testid="daily-decision-partial">
            Частичная оценка: точные веса и инвестиционный результат недоступны. Неизвестная цена не
            считается нулём.
          </p>
        ) : null}
      </div>

      {portfolioId != null ? (
        <div className="panel" data-testid="daily-decision-new-cash">
          <h3>Новый капитал</h3>
          <p className="muted">
            Гипотетический капитал для сравнения сценариев. Не создаёт депозит и не меняет журнал.
          </p>
          <div className="row-between" style={{ gap: "0.75rem", flexWrap: "wrap" }}>
            <label className="stack-sm" style={{ flex: "1 1 220px" }}>
              <span>Новый капитал для распределения, ₽</span>
              <input
                data-testid="daily-decision-new-cash-input"
                inputMode="decimal"
                value={cashInput}
                onChange={(e) => setCashInput(e.target.value)}
                placeholder="например 30000"
              />
            </label>
            <button
              type="button"
              className="btn primary"
              data-testid="daily-decision-calculate"
              disabled={busy}
              onClick={() => void calculate()}
            >
              {busy ? "Считаем…" : "Рассчитать"}
            </button>
          </div>
          {localError ? (
            <p className="page-state error" data-testid="daily-decision-local-error">
              {localError}
            </p>
          ) : null}
          {view.new_cash_plan ? (
            <div className="metric-grid" style={{ marginTop: "1rem" }} data-testid="daily-decision-new-cash-plan">
              <MetricCard label="Запрошено" value={money(view.new_cash_plan.requested_new_cash_rub)} />
              <MetricCard label="Текущий NAV" value={money(view.new_cash_plan.current_nav_rub)} />
              <MetricCard
                label="Гипотетический контекст"
                value={money(view.new_cash_plan.hypothetical_total_capital_rub)}
              />
            </div>
          ) : null}
          {view.data_confidence ? (
            <p className="muted" data-testid="daily-decision-confidence">
              Уверенность данных: {view.data_confidence.status}
              {view.data_confidence.reasons?.length
                ? ` (${view.data_confidence.reasons.join(", ")})`
                : ""}
            </p>
          ) : null}
        </div>
      ) : null}

      {scenarios.length > 0 ? (
        <div className="panel" data-testid="daily-decision-scenarios">
          <h3>Варианты</h3>
          <ul className="decision-action-list">
            {scenarios.map((s) => (
              <ScenarioCard key={s.id} scenario={s} />
            ))}
          </ul>
        </div>
      ) : null}

      {view.limitations && view.limitations.length > 0 ? (
        <div className="panel" data-testid="daily-decision-limitations">
          <h3>Ограничения</h3>
          <ul className="muted">
            {view.limitations.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="panel">
        <h3>Действия</h3>
        {view.actions.length === 0 ? (
          <p className="muted">Нет действий</p>
        ) : (
          <ul className="decision-action-list" data-testid="daily-decision-actions">
            {view.actions.map((a) => (
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

      {view.risks.length > 0 ? (
        <div className="panel">
          <h3>Риски и предупреждения</h3>
          <ul data-testid="daily-decision-risks">
            {view.risks.map((r, i) => (
              <li key={`${r.code}-${i}`}>
                {r.symbol ? <strong>{r.symbol}: </strong> : null}
                {r.message || r.code}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="panel">
        <h3>Почему / контекст</h3>
        <p className="muted">
          Кандидат: {view.context.candidate_source || "—"}
          {view.context.candidate_id ? ` · ${view.context.candidate_id}` : ""}
        </p>
        <p className="muted">На дату: {view.as_of}</p>
        {view.context.what_can_change_decision?.length ? (
          <div>
            <p>Что может изменить решение:</p>
            <ul className="muted">
              {view.context.what_can_change_decision.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <p className="muted" data-testid="daily-decision-disclaimer">
          {view.disclaimer}
        </p>
      </div>
    </div>
  );
}
