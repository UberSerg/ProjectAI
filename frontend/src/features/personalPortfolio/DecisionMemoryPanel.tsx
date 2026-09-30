import { useCallback, useEffect, useRef, useState } from "react";
import {
  captureDecisionMemory,
  getDecisionMemory,
  getPossibleMatches,
  linkOperation,
  listDecisionMemory,
  refreshDecisionOutcomes,
  unlinkOperation,
  type DecisionMemoryAction,
  type DecisionMemoryOutcome,
  type DecisionMemoryRecord,
  type DecisionMemoryRecordSummary,
  type PossibleMatchesResponse,
} from "../../api/decisionMemory";
import { errorMessage } from "../../api/client";

const ACTION_LABELS: Record<string, string> = {
  CONSIDER_INCREASE: "Рассмотреть увеличение",
  CONSIDER_REDUCE: "Рассмотреть сокращение",
  KEEP_CASH: "Держать кэш",
  HOLD: "Держать",
  REVIEW: "Проверить",
  DATA_QUALITY: "Проверить данные",
  SETUP: "Настроить",
  ACTIVATE_JOURNAL: "Включить журнал",
};

const OUTCOME_STATUS_LABELS: Record<string, string> = {
  PENDING: "Ожидает",
  READY: "Готово",
  DATA_UNAVAILABLE: "Нет данных о цене",
  BASELINE_UNAVAILABLE: "Нет базовой цены",
};

const ALIGNMENT_LABELS: Record<string, string> = {
  ALIGNED: "Цена двигалась в сторону рекомендации",
  NOT_ALIGNED: "Цена двигалась против рекомендации",
};

const LINKABLE_ACTIONS = new Set(["CONSIDER_INCREASE", "CONSIDER_REDUCE"]);
const HORIZONS = [5, 20, 60];

/** Only ever render primitives; objects never reach the DOM as "[object Object]". */
function text(value: unknown, fallback = "—"): string {
  if (typeof value === "string") return value.trim() || fallback;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return fallback;
}

function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((x): x is string => typeof x === "string" && x.trim() !== "");
}

function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ru-RU");
}

function plainDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(`${value.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("ru-RU");
}

function price(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n.toLocaleString("ru-RU", { maximumFractionDigits: 4 })} ₽`;
}

function returnPct(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  const n = Number(value) * 100;
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function actionTitle(a: DecisionMemoryAction): string {
  const payloadTitle = a.action_payload && typeof a.action_payload.title === "string" ? a.action_payload.title : "";
  const label = ACTION_LABELS[a.action] ?? a.action;
  const head = payloadTitle.trim() || label;
  return a.symbol && !head.includes(a.symbol) ? `${a.symbol}: ${head}` : head;
}

function actionRationale(a: DecisionMemoryAction): string {
  return a.action_payload && typeof a.action_payload.rationale === "string" ? a.action_payload.rationale : "";
}

function activeLinks(a: DecisionMemoryAction) {
  return (a.links ?? []).filter((l) => l.active);
}

function OutcomeRow({ outcome, horizon }: { outcome: DecisionMemoryOutcome | undefined; horizon: number }) {
  if (!outcome) {
    return (
      <li data-testid={`memory-outcome-${horizon}`}>
        <strong>{horizon} торговых сессий:</strong> <span className="muted">нет данных</span>
      </li>
    );
  }
  const ready = outcome.status === "READY";
  return (
    <li data-testid={`memory-outcome-${horizon}`}>
      <strong>{horizon} торговых сессий:</strong> {OUTCOME_STATUS_LABELS[outcome.status] ?? text(outcome.status)}
      <span className="muted">
        {" · "}базовая цена {price(outcome.baseline_price)}
        {ready ? ` · цена на ${plainDate(outcome.observed_session_date)} ${price(outcome.observed_price)}` : ""}
        {outcome.status === "PENDING" && outcome.target_session_date
          ? ` · оценка после ${plainDate(outcome.target_session_date)}`
          : ""}
      </span>
      {ready ? (
        <>
          {" · "}
          <span>
            {text(outcome.return_type, "PRICE_RETURN")} {returnPct(outcome.forward_return)}
          </span>
          {outcome.directional_alignment && ALIGNMENT_LABELS[outcome.directional_alignment] ? (
            <span className="muted"> · {ALIGNMENT_LABELS[outcome.directional_alignment]}</span>
          ) : null}
        </>
      ) : null}
    </li>
  );
}

export function DecisionMemoryPanel({
  portfolioId,
  test = false,
  newCashRub = null,
  decisionFingerprint = null,
}: {
  portfolioId: number | null | undefined;
  test?: boolean;
  newCashRub?: number | string | null;
  /** Fingerprint of the Daily Decision currently shown to the user. */
  decisionFingerprint?: string | null;
}) {
  const [items, setItems] = useState<DecisionMemoryRecordSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const [detail, setDetail] = useState<DecisionMemoryRecord | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const [matches, setMatches] = useState<Record<number, PossibleMatchesResponse | null>>({});
  const [linkBusy, setLinkBusy] = useState<string | null>(null);
  const seq = useRef(0);

  const loadList = useCallback(async () => {
    if (portfolioId == null) return;
    const my = ++seq.current;
    try {
      const res = await listDecisionMemory(portfolioId, { test });
      if (my !== seq.current) return;
      setItems(Array.isArray(res.items) ? res.items : []);
      setError(null);
    } catch (err) {
      if (my !== seq.current) return;
      setError(errorMessage(err));
    } finally {
      if (my === seq.current) setLoaded(true);
    }
  }, [portfolioId, test]);

  // Read-only load of history. Never captures anything.
  useEffect(() => {
    setItems([]);
    setLoaded(false);
    setError(null);
    setNotice(null);
    setOpenId(null);
    setDetail(null);
    setMatches({});
    void loadList();
    return () => {
      seq.current += 1;
    };
  }, [loadList]);

  const loadMatches = useCallback(
    async (record: DecisionMemoryRecord) => {
      if (portfolioId == null) return;
      const targets = (record.actions ?? []).filter(
        (a) => LINKABLE_ACTIONS.has(a.action) && a.instrument_id != null && activeLinks(a).length === 0,
      );
      const entries = await Promise.all(
        targets.map(async (a) => {
          try {
            return [a.id, await getPossibleMatches(portfolioId, a.id, { test })] as const;
          } catch {
            return [a.id, null] as const;
          }
        }),
      );
      setMatches((prev) => ({ ...prev, ...Object.fromEntries(entries) }));
    },
    [portfolioId, test],
  );

  const openDecision = useCallback(
    async (id: number) => {
      if (portfolioId == null) return;
      setOpenId(id);
      setDetailBusy(true);
      setError(null);
      setMatches({});
      try {
        const rec = await getDecisionMemory(portfolioId, id, { test });
        setDetail(rec);
        await loadMatches(rec);
      } catch (err) {
        setDetail(null);
        setError(errorMessage(err));
      } finally {
        setDetailBusy(false);
      }
    },
    [portfolioId, test, loadMatches],
  );

  function toggleDecision(id: number) {
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
      setMatches({});
      return;
    }
    void openDecision(id);
  }

  async function reopen(id: number) {
    if (portfolioId == null) return;
    const rec = await getDecisionMemory(portfolioId, id, { test });
    setDetail(rec);
    setMatches({});
    await loadMatches(rec);
  }

  async function capture() {
    if (portfolioId == null || capturing) return;
    const fp = typeof decisionFingerprint === "string" ? decisionFingerprint.trim() : "";
    if (!fp) {
      setError("Сначала обновите расчёт решения, затем зафиксируйте актуальную версию.");
      return;
    }
    setCapturing(true);
    setError(null);
    setNotice(null);
    try {
      const rec = await captureDecisionMemory(portfolioId, {
        test,
        newCashRub,
        expectedDecisionFingerprint: fp,
      });
      const summary: DecisionMemoryRecordSummary = {
        ...rec,
        actions_count: rec.actions_count ?? rec.actions?.length ?? 0,
      };
      setItems((prev) => [summary, ...prev.filter((x) => x.id !== summary.id)]);
      setLoaded(true);
      setNotice(
        rec.idempotent_replay ? "Это решение уже было сохранено." : "Решение зафиксировано. Подтверждения сделки это не означает.",
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCapturing(false);
    }
  }

  async function refreshOutcomes() {
    if (portfolioId == null || refreshing) return;
    setRefreshing(true);
    setError(null);
    setNotice(null);
    try {
      const res = await refreshDecisionOutcomes(portfolioId, { test });
      setNotice(
        `Результаты обновлены: оценено ${res.evaluated}, готово ${res.ready}, ожидают ${res.still_pending}, нет данных ${res.data_unavailable}.`,
      );
      if (openId != null) await reopen(openId);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRefreshing(false);
    }
  }

  async function confirmLink(actionId: number, operationId: number) {
    if (portfolioId == null || openId == null) return;
    setLinkBusy(`link:${actionId}:${operationId}`);
    setError(null);
    try {
      await linkOperation(portfolioId, actionId, operationId, { test });
      await reopen(openId);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLinkBusy(null);
    }
  }

  async function removeLink(linkId: number) {
    if (portfolioId == null || openId == null) return;
    setLinkBusy(`unlink:${linkId}`);
    setError(null);
    try {
      await unlinkOperation(portfolioId, linkId, { test });
      await reopen(openId);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLinkBusy(null);
    }
  }

  if (portfolioId == null) return null;

  const actions = detail?.actions ?? [];

  return (
    <div className="stack-lg" data-testid="decision-memory-panel">
      <div className="panel">
        <div className="row-between" style={{ gap: "0.75rem", flexWrap: "wrap" }}>
          <div>
            <h3>Память решений</h3>
            <p className="muted">
              Фиксирует рекомендацию и цены для последующей оценки. Это не подтверждение сделки и не доходность портфеля.
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button
              type="button"
              className="btn primary"
              data-testid="memory-capture"
              disabled={capturing}
              onClick={() => void capture()}
            >
              {capturing ? "Фиксируем…" : "Зафиксировать решение"}
            </button>
            <button
              type="button"
              className="btn secondary"
              data-testid="memory-refresh"
              disabled={refreshing}
              onClick={() => void refreshOutcomes()}
            >
              {refreshing ? "Обновляем…" : "Обновить результаты"}
            </button>
          </div>
        </div>
        {error ? (
          <p className="page-state error" data-testid="memory-error">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p className="muted" data-testid="memory-notice">
            {notice}
          </p>
        ) : null}
      </div>

      <div className="panel" data-testid="memory-history">
        <h3>История решений</h3>
        {!loaded ? (
          <p className="muted">Загрузка…</p>
        ) : items.length === 0 ? (
          <p className="muted" data-testid="memory-empty">
            История решений раньше не сохранялась.
          </p>
        ) : (
          <ul className="decision-action-list">
            {items.map((it) => (
              <li key={it.id} className="decision-action-item" data-testid={`memory-item-${it.id}`}>
                <div className="row-between">
                  <div>
                    <strong>{text(it.headline, "Решение без заголовка")}</strong>
                    <p className="muted">
                      {dateTime(it.captured_at)}
                      {it.status ? ` · ${text(it.status)}` : ""}
                      {` · действий: ${it.actions_count ?? 0}`}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="btn secondary"
                    data-testid={`memory-open-${it.id}`}
                    onClick={() => toggleDecision(it.id)}
                  >
                    {openId === it.id ? "Скрыть" : "Подробнее"}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {openId != null ? (
        <div className="stack-lg" data-testid="memory-detail">
          {detailBusy && !detail ? <p className="muted">Загрузка решения…</p> : null}
          {detail ? (
            <>
              <div className="panel" data-testid="memory-block-recommendation">
                <h3>Что Kraken рекомендовала</h3>
                <p className="muted">
                  Зафиксировано: {dateTime(detail.captured_at)}
                  {detail.decision_as_of ? ` · на дату ${plainDate(detail.decision_as_of)}` : ""}
                </p>
                {detail.headline ? <p>{text(detail.headline)}</p> : null}
                {actions.length === 0 ? (
                  <p className="muted">В решении нет действий.</p>
                ) : (
                  <ul className="decision-action-list">
                    {actions.map((a) => (
                      <li key={a.id} className="decision-action-item" data-testid={`memory-action-${a.id}`}>
                        <div className="row-between">
                          <strong>{actionTitle(a)}</strong>
                          {a.priority ? <span className="chip">{text(a.priority)}</span> : null}
                        </div>
                        {actionRationale(a) ? <p>{actionRationale(a)}</p> : null}
                        {textList(a.reason_codes).length > 0 ? (
                          <p className="muted">Причины: {textList(a.reason_codes).join(", ")}</p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="panel" data-testid="memory-block-happened">
                <h3>Что произошло</h3>
                {actions.length === 0 ? (
                  <p className="muted">Нет действий для сопоставления.</p>
                ) : (
                  <ul className="decision-action-list">
                    {actions.map((a) => {
                      const links = activeLinks(a);
                      const found = matches[a.id];
                      const candidates = (found?.matches ?? []).filter((m) => !m.already_linked);
                      return (
                        <li key={a.id} className="decision-action-item" data-testid={`memory-happened-${a.id}`}>
                          <strong>{actionTitle(a)}</strong>
                          {links.length > 0 ? (
                            <ul>
                              {links.map((l) => (
                                <li key={l.id} data-testid={`memory-link-${l.id}`}>
                                  Связано с операцией №{l.personal_operation_id}
                                  <span className="muted"> · подтверждено пользователем {dateTime(l.linked_at)}</span>{" "}
                                  <button
                                    type="button"
                                    className="btn ghost"
                                    data-testid={`memory-unlink-${l.id}`}
                                    disabled={linkBusy === `unlink:${l.id}`}
                                    onClick={() => void removeLink(l.id)}
                                  >
                                    Отвязать
                                  </button>
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <p className="muted" data-testid={`memory-unconfirmed-${a.id}`}>
                              Действие пользователя не подтверждено
                            </p>
                          )}
                          {candidates.length > 0 ? (
                            <ul data-testid={`memory-matches-${a.id}`}>
                              {candidates.map((m) => (
                                <li key={m.personal_operation_id}>
                                  <span className="chip">{text(m.label, "POSSIBLE_MATCH")}</span>{" "}
                                  Операция №{m.personal_operation_id}: {m.operation_type === "BUY" ? "покупка" : m.operation_type === "SELL" ? "продажа" : text(m.operation_type)}
                                  <span className="muted">
                                    {" · "}
                                    {dateTime(m.occurred_at)}
                                    {m.lots ? ` · лотов ${text(m.lots)}` : ""}
                                    {m.price ? ` · цена ${price(m.price)}` : ""}
                                  </span>{" "}
                                  <button
                                    type="button"
                                    className="btn secondary"
                                    data-testid={`memory-confirm-${a.id}-${m.personal_operation_id}`}
                                    disabled={linkBusy === `link:${a.id}:${m.personal_operation_id}`}
                                    onClick={() => void confirmLink(a.id, m.personal_operation_id)}
                                  >
                                    Связать с операцией
                                  </button>
                                </li>
                              ))}
                            </ul>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>

              <div className="panel" data-testid="memory-block-outcomes">
                <h3>Результат после решения</h3>
                <p className="muted">Изменение цены; дивиденды не включены</p>
                {actions.length === 0 ? (
                  <p className="muted">Нет действий для оценки.</p>
                ) : (
                  <ul className="decision-action-list">
                    {actions.map((a) => (
                      <li key={a.id} className="decision-action-item" data-testid={`memory-outcomes-${a.id}`}>
                        <strong>{actionTitle(a)}</strong>
                        <ul>
                          {HORIZONS.map((h) => (
                            <OutcomeRow
                              key={h}
                              horizon={h}
                              outcome={(a.outcomes ?? []).find((o) => o.horizon_sessions === h)}
                            />
                          ))}
                        </ul>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
