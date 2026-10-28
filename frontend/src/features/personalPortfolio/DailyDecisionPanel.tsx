import { useEffect, useRef, useState } from "react";
import {
  getDailyPersonalDecision,
  type DailyPersonalDecision,
  type DecisionScenario,
  type DecisionScenarioId,
} from "../../api/dailyPersonalDecision";
import { EmptyState, MetricCard, StatusBadge } from "../../components/Ui";

const DEFAULT_NEW_CASH_RUB = 100_000;

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

const LIMITATION_COPY: Record<string, string> = {
  CANDIDATE_STALE: "Сохранённый кандидат устарел.",
  CANDIDATE_FRESHNESS_UNKNOWN: "Свежесть сохранённого кандидата не подтверждена.",
  CANDIDATE_OR_VALUATION_UNAVAILABLE: "Нет надёжного сравнения с кандидатом или оценка неполная.",
  ADVISORY_ONLY_BOND_TRADE: "Только ориентир по fixed-income — учёт облигаций не исполняет сделку.",
  READ_ONLY_HYPOTHETICAL: "Гипотетический план без записи в журнал и без депозита.",
  LOT_SIZE_UNKNOWN: "Размер лота неизвестен — целые лоты посчитать нельзя.",
};

function humanLimitation(code: string): string {
  return LIMITATION_COPY[code] || code;
}

function statusForBadge(status: string): string {
  if (status === "NO_ACTION" || status === "READY") return "ok";
  if (status === "PARTIAL" || status === "LEGACY_PENDING" || status === "NEEDS_SETUP" || status === "DRAFT_ANALYSIS") {
    return "warning";
  }
  if (status === "UNAVAILABLE") return "error";
  return "unknown";
}

const SCENARIO_EXPLAIN: Record<string, string> = {
  DO_NOTHING:
    "Не зачислять новый капитал в портфель: сумма остаётся вне учёта, состав и кэш не меняются.",
  HOLD_CASH:
    "Гипотетически оставить весь новый капитал кэшем — без покупок акций и облигаций.",
  TARGET_UNDERWEIGHTS:
    "Направить капитал в позиции ниже целевого веса. Покупки только целыми лотами, где размер лота известен.",
  KRAKEN_ALLOCATION:
    "Следовать текущему плану распределения Kraken по рукавам и позициям кандидата.",
  FIXED_INCOME_ALTERNATIVE:
    "Ориентир по fixed-income / облигациям. Только advisory — сделка и брокер не вызываются.",
};

function scenarioTitle(scenario: DecisionScenario): string {
  if (scenario.title?.trim()) return scenario.title;
  switch (scenario.id as DecisionScenarioId) {
    case "DO_NOTHING":
      return "Ничего не делать";
    case "HOLD_CASH":
      return "Держать кэш";
    case "TARGET_UNDERWEIGHTS":
      return "Докупить недовесы";
    case "KRAKEN_ALLOCATION":
      return "План Kraken";
    case "FIXED_INCOME_ALTERNATIVE":
      return "Альтернатива: fixed-income";
    default:
      return scenario.id;
  }
}

function scenarioStatusLabel(status: string): string {
  const s = status.toLowerCase();
  if (s === "available") return "Доступен";
  if (s === "advisory") return "Только ориентир";
  if (s === "degraded") return "Частично";
  if (s === "unavailable") return "Недоступен";
  return status;
}

function scenarioCashLeft(scenario: DecisionScenario): string | number | null | undefined {
  if (scenario.id === "DO_NOTHING") {
    return scenario.external_unallocated_rub ?? scenario.residual_cash_rub;
  }
  return scenario.residual_cash_rub ?? scenario.residual_unexecuted_rub;
}

function ScenarioCard({ scenario }: { scenario: DecisionScenario }) {
  const unavailable = scenario.status === "unavailable" || scenario.status === "degraded";
  const explain = SCENARIO_EXPLAIN[scenario.id] || null;
  const allocated = scenario.executable_notional_rub ?? scenario.deployed_rub;
  const target = scenario.target_allocation_rub ?? scenario.deployed_rub;
  const cashLeft = scenarioCashLeft(scenario);
  const advisory =
    scenario.advisory_only_rub != null && Number(scenario.advisory_only_rub) > 0
      ? scenario.advisory_only_rub
      : null;

  return (
    <li className="decision-action-item" data-testid={`decision-scenario-${scenario.id}`}>
      <div className="row-between">
        <strong>{scenarioTitle(scenario)}</strong>
        <span className="chip">{scenarioStatusLabel(scenario.status)}</span>
      </div>
      {explain ? (
        <p className="muted" data-testid={`decision-scenario-explain-${scenario.id}`}>
          {explain}
        </p>
      ) : null}
      {unavailable && scenario.reason ? (
        <p className="muted" data-testid={`decision-scenario-blocked-${scenario.id}`}>
          Почему недоступно: {humanLimitation(scenario.reason)}
        </p>
      ) : null}
      {!unavailable || scenario.status === "degraded" || scenario.status === "advisory" ? (
        <>
          <ul className="muted" data-testid={`decision-scenario-metrics-${scenario.id}`}>
            {target != null ? <li>Целевой объём: {money(target)}</li> : null}
            {allocated != null ? <li>Можно оценить целыми лотами: {money(allocated)}</li> : null}
            {advisory != null ? <li>Только ориентир (не исполняется): {money(advisory)}</li> : null}
            {cashLeft != null ? <li>Остаётся кэшем / не распределено: {money(cashLeft)}</li> : null}
            {scenario.cash_share != null ? <li>Доля кэша ≈ {pct(scenario.cash_share)}</li> : null}
          </ul>
          {scenario.purchases && scenario.purchases.length > 0 ? (
            <ul className="muted" data-testid={`decision-scenario-purchases-${scenario.id}`}>
              {scenario.purchases.map((p, idx) => (
                <li key={`${p.symbol || p.sleeve || "row"}-${idx}`}>
                  {p.symbol || p.sleeve || "план"}: целевой объём {money(p.target_rub)}
                  {p.lots != null
                    ? ` · целых лотов ${p.lots}`
                    : p.limitations?.includes("LOT_SIZE_UNKNOWN")
                      ? " · размер лота неизвестен"
                      : ""}
                  {p.executable_estimated_notional_rub || p.estimated_notional
                    ? ` · по лотам ${money(p.executable_estimated_notional_rub || p.estimated_notional)}`
                    : ""}
                  {p.limitations?.includes("ADVISORY_ONLY_BOND_TRADE") ||
                  p.execution_status === "ADVISORY_ONLY"
                    ? " · только ориентир"
                    : ""}
                  {p.residual_cash_rub || p.residual_unexecuted_rub
                    ? ` · остаётся ${money(p.residual_unexecuted_rub || p.residual_cash_rub)}`
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
        <p className="muted">
          Ограничения: {scenario.limitations.map(humanLimitation).join("; ")}
        </p>
      ) : null}
      {scenario.cbr_context?.wording ? <p className="muted">{scenario.cbr_context.wording}</p> : null}
    </li>
  );
}

function parseCashInput(raw: string): number | null {
  const trimmed = raw.trim().replace(/\s/g, "").replace(",", ".");
  if (!trimmed) return 0;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n < 0) return null;
  return n;
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
  const [appliedCash, setAppliedCash] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [showDetails, setShowDetails] = useState(false);
  const [view, setView] = useState<DailyPersonalDecision | null>(decision);
  const reqSeq = useRef(0);
  const portfolioRef = useRef(portfolioId);
  const onDecisionChangeRef = useRef(onDecisionChange);
  onDecisionChangeRef.current = onDecisionChange;

  const decisionSyncKey = `${decision?.decision_fingerprint ?? ""}|${decision?.as_of ?? ""}|${decision?.new_cash_rub ?? ""}|${decision?.engine_version ?? ""}`;

  useEffect(() => {
    // Syncing the tab's base decision replaces whatever calculated plan was on screen.
    setView(decision);
    if (decision?.new_cash_rub != null && Number(decision.new_cash_rub) > 0) {
      setAppliedCash(Number(decision.new_cash_rub));
    } else {
      setAppliedCash(null);
    }
    onDecisionChangeRef.current?.(null);
    // decisionSyncKey captures the base payload identity; `decision` is applied above.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional sync-key gate
  }, [decisionSyncKey]);

  useEffect(() => {
    if (portfolioRef.current !== portfolioId) {
      // Portfolio switch: clear prior plan and in-flight calculation.
      reqSeq.current += 1;
      setCashInput("");
      setAppliedCash(null);
      setLocalError(null);
      setBusy(false);
      setShowDetails(false);
      setView(decision);
      portfolioRef.current = portfolioId;
      onDecisionChangeRef.current?.(null);
    }
  }, [portfolioId, decision]);

  function clearCaptureEligibility(
    localView?: DailyPersonalDecision | null,
    options?: { dropInFlight?: boolean },
  ) {
    // Never leave a stale fingerprint available for Decision Memory capture.
    if (options?.dropInFlight) {
      reqSeq.current += 1;
      setBusy(false);
    }
    onDecisionChangeRef.current?.(null);
    if (localView) {
      setView({ ...localView, decision_fingerprint: undefined });
    } else if (view) {
      setView({ ...view, decision_fingerprint: undefined });
    }
  }

  function invalidateFingerprintForDirtyCapital(nextInput: string) {
    const trimmed = nextInput.trim();
    const parsed = trimmed === "" ? null : parseCashInput(trimmed);
    const hadCalculatedPlan =
      appliedCash != null || Boolean(view?.decision_fingerprint) || Boolean(view?.new_cash_plan) || busy;
    if (!hadCalculatedPlan) return;
    // Empty / invalid / different from last applied amount → capture must wait.
    if (trimmed !== "" && parsed == null) {
      clearCaptureEligibility(undefined, { dropInFlight: true });
      return;
    }
    if (parsed != null && appliedCash != null && parsed === appliedCash && !busy) return;
    if (parsed == null && appliedCash == null && trimmed === "" && !busy) return;
    // Drop in-flight calc so a late response cannot restore an outdated fingerprint.
    clearCaptureEligibility(undefined, { dropInFlight: true });
  }

  async function calculate(amountOverride?: number) {
    if (portfolioId == null) return;
    const amount =
      amountOverride != null
        ? amountOverride
        : parseCashInput(cashInput.trim() === "" ? "0" : cashInput);
    if (amount == null) {
      setLocalError("Введите неотрицательную сумму в рублях");
      clearCaptureEligibility();
      return;
    }
    if (amountOverride != null) {
      setCashInput(String(amountOverride));
    }
    // Invalidate immediately so an in-flight older response cannot restore capture.
    const seq = ++reqSeq.current;
    clearCaptureEligibility();
    setBusy(true);
    setLocalError(null);
    const requestPortfolioId = portfolioId;
    try {
      const next = await getDailyPersonalDecision(requestPortfolioId, {
        newCashRub: amount > 0 ? amount : null,
      });
      if (seq !== reqSeq.current || portfolioRef.current !== requestPortfolioId) return;
      setAppliedCash(amount > 0 ? amount : null);
      setView(next);
      onDecisionChange?.(next);
    } catch (err) {
      if (seq !== reqSeq.current || portfolioRef.current !== requestPortfolioId) return;
      setLocalError(err instanceof Error ? err.message : "Не удалось рассчитать сценарии");
      clearCaptureEligibility();
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
  const plan = view.new_cash_plan;
  const capitalConsidered =
    plan?.requested_new_cash_rub ??
    (appliedCash != null && appliedCash > 0 ? String(appliedCash) : view.new_cash_rub);

  return (
    <div className="stack-lg" data-testid="daily-decision-panel">
      {/* 1. Summary */}
      <div className="panel" data-testid="daily-decision-summary">
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
        <p className="muted" data-testid="daily-decision-advisory-note">
          Это advisory-рекомендация: портфель, депозит и брокер не изменяются.
        </p>
      </div>

      {portfolioId != null ? (
        <div className="panel" data-testid="daily-decision-new-cash">
          <h3>Новый капитал (гипотеза)</h3>
          <p className="muted">
            Сравнение сценариев через GET daily-decision?new_cash_rub=… Без депозита и без мутации
            журнала.
          </p>
          <div className="row-between" style={{ gap: "0.75rem", flexWrap: "wrap" }}>
            <label className="stack-sm" style={{ flex: "1 1 220px" }}>
              <span>Новый капитал для распределения, ₽</span>
              <input
                data-testid="daily-decision-new-cash-input"
                inputMode="decimal"
                value={cashInput}
                onChange={(e) => {
                  const next = e.target.value;
                  setCashInput(next);
                  invalidateFingerprintForDirtyCapital(next);
                }}
                placeholder={`например ${DEFAULT_NEW_CASH_RUB}`}
              />
            </label>
            <button
              type="button"
              className="btn secondary"
              data-testid="daily-decision-preset-100k"
              disabled={busy}
              onClick={() => void calculate(DEFAULT_NEW_CASH_RUB)}
            >
              100 000 ₽
            </button>
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
          {plan || capitalConsidered ? (
            <div className="metric-grid" style={{ marginTop: "1rem" }} data-testid="daily-decision-new-cash-plan">
              <MetricCard label="Учтённый капитал" value={money(capitalConsidered)} />
              <MetricCard label="Текущий NAV" value={money(plan?.current_nav_rub ?? view.portfolio.nav_rub)} />
              <MetricCard
                label="Гипотетический контекст"
                value={money(
                  plan?.hypothetical_total_capital_rub ??
                    (capitalConsidered != null
                      ? Number(view.portfolio.nav_rub) + Number(capitalConsidered)
                      : null),
                )}
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

      {/* 2. Scenario comparison */}
      {scenarios.length > 0 ? (
        <div className="panel" data-testid="daily-decision-scenarios">
          <h3>Сравнение сценариев</h3>
          <p className="muted">
            Пять вариантов «что делать» с гипотетическим капиталом. Покупки считаются целыми лотами;
            advisory-only не означает сделку.
          </p>
          <ul className="decision-action-list">
            {scenarios.map((s) => (
              <ScenarioCard key={s.id} scenario={s} />
            ))}
          </ul>
        </div>
      ) : null}

      {/* 3. Explanation */}
      <div className="panel" data-testid="daily-decision-explanation">
        <h3>Пояснение</h3>
        {view.actions.length === 0 ? (
          <p className="muted">Нет отдельных действий</p>
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
        <p className="muted">
          Кандидат: {view.context.candidate_source || "—"}
          {view.context.candidate_id ? ` · ${view.context.candidate_id}` : ""}
          {" · "}
          на дату {view.as_of}
        </p>
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

      {/* 4. Risks / limitations */}
      {(view.risks.length > 0 || (view.limitations && view.limitations.length > 0)) && (
        <div className="panel" data-testid="daily-decision-risks-block">
          <h3>Риски и ограничения</h3>
          {view.limitations && view.limitations.length > 0 ? (
            <ul className="muted" data-testid="daily-decision-limitations">
              {view.limitations.map((x) => (
                <li key={x}>{humanLimitation(x)}</li>
              ))}
            </ul>
          ) : null}
          {view.risks.length > 0 ? (
            <ul data-testid="daily-decision-risks">
              {view.risks.map((r, i) => (
                <li key={`${r.code}-${i}`}>
                  {r.symbol ? <strong>{r.symbol}: </strong> : null}
                  {r.message || r.code}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}

      {/* 5. Details on request */}
      <div className="panel" data-testid="daily-decision-details">
        <button
          type="button"
          className="btn ghost"
          data-testid="daily-decision-toggle-details"
          onClick={() => setShowDetails((v) => !v)}
        >
          {showDetails ? "Скрыть технические детали" : "Показать технические детали"}
        </button>
        {showDetails ? (
          <div style={{ marginTop: "0.75rem" }} data-testid="daily-decision-details-body">
            <p className="muted">
              Версия движка: {view.engine_version || "—"}
              {view.decision_fingerprint
                ? ` · fingerprint ${view.decision_fingerprint.slice(0, 12)}…`
                : " · fingerprint отсутствует"}
            </p>
            <p className="muted">
              Journal: {view.portfolio.journal_state}
              {" · "}
              valuation_complete: {String(view.data_quality.valuation_complete)}
              {" · "}
              missing_price_count: {view.data_quality.missing_price_count}
            </p>
            {view.degradations?.length ? (
              <ul className="muted">
                {view.degradations.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            ) : null}
            {owner && view.context.candidate_freshness_reason ? (
              <p className="muted">Freshness: {view.context.candidate_freshness_reason}</p>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
