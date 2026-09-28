import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { errorMessage } from "../../api/client";
import {
  searchCatalogInstruments,
  type CatalogInstrument,
} from "../../api/instruments";
import {
  activatePersonalPortfolio,
  clearDraftPortfolio,
  createPersonalOperation,
  getPersonalPortfolio,
  resetPersonalPortfolio,
  type CreatePersonalOperationBody,
  type PersonalOperationType,
  type PersonalSummary,
} from "../../api/personalPortfolios";
import { EmptyState, MetricCard, PageState, StatusBadge } from "../../components/Ui";
import { useKrakenRole } from "../../role/KrakenRoleContext";

export const OP_LABELS: Record<PersonalOperationType, string> = {
  DEPOSIT: "Пополнение",
  WITHDRAWAL: "Вывод",
  BUY: "Покупка",
  SELL: "Продажа",
  COMMISSION: "Комиссия",
  OPENING_CASH: "Открытие: кэш",
  OPENING_POSITION: "Открытие: позиция",
};

function money(v: string | null | undefined): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return v;
  return `${n.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `op-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function canonicalPayloadKey(body: CreatePersonalOperationBody): string {
  const normalized = {
    operation_type: body.operation_type,
    occurred_at: body.occurred_at,
    instrument_id: body.instrument_id ?? null,
    lots: body.lots ?? null,
    units: body.units ?? null,
    price: body.price ?? null,
    amount: body.amount ?? null,
    commission: body.commission ?? "0",
    note: body.note ?? null,
    non_standard_lot: body.non_standard_lot ?? false,
    supersedes_operation_id: body.supersedes_operation_id ?? null,
  };
  return JSON.stringify(normalized);
}

const BOND_TRADE_USER_MSG =
  "Операции с облигациями пока нельзя вносить через обычную цену: биржевая цена облигации указывается в процентах от номинала. Kraken не будет считать её рублёвой ценой.";

export function portfolioLifecycleState(data: PersonalSummary): "DRAFT" | "ACTIVE" {
  const lc = data.portfolio.lifecycle_state;
  if (lc === "DRAFT" || lc === "ACTIVE") return lc;
  const js = data.portfolio.journal_state;
  if (js === "ACTIVE" || (data.portfolio.has_operations && js !== "EMPTY")) return "ACTIVE";
  return "DRAFT";
}

function costBasisCounts(positions: PersonalSummary["positions"]): {
  known: number;
  unknown: number;
} {
  let known = 0;
  let unknown = 0;
  for (const p of positions) {
    if ((p.asset_class || "").toLowerCase() === "bond" && p.cost_basis_status !== "KNOWN") {
      unknown += 1;
      continue;
    }
    if (p.cost_basis_status === "KNOWN") known += 1;
    else if (p.cost_basis_status === "UNKNOWN") unknown += 1;
    else if (p.average_price != null || p.cost_basis_total_rub != null) known += 1;
    else unknown += 1;
  }
  return { known, unknown };
}

function PositionsTable({ positions }: { positions: PersonalSummary["positions"] }) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Тикер</th>
          <th>Кол-во</th>
          <th>Средняя</th>
          <th>Цена</th>
          <th>Стоимость</th>
          <th>P&amp;L</th>
        </tr>
      </thead>
      <tbody>
        {positions.map((p) => {
          const isBond = (p.asset_class || "").toLowerCase() === "bond";
          const basisUnknown = p.cost_basis_status === "UNKNOWN" || (!isBond && p.average_price == null);
          return (
            <tr key={p.instrument_id}>
              <td>
                <strong>{p.secid}</strong>
                <div className="muted">{p.name}</div>
              </td>
              <td>
                {p.units}
                {p.lots ? <div className="muted">{p.lots} лот(ов)</div> : null}
              </td>
              <td>
                {isBond || p.average_price == null ? (
                  <span className="muted">—</span>
                ) : (
                  money(p.average_price)
                )}
              </td>
              <td>
                {p.price_available ? money(p.current_price) : "Цена недоступна"}
                {p.price_date ? <div className="muted">{p.price_date}</div> : null}
              </td>
              <td>{p.market_value != null ? money(p.market_value) : "—"}</td>
              <td>
                {isBond && p.cost_basis_status !== "KNOWN" ? (
                  <span className="muted" title={p.pnl_unavailable_reason || undefined}>
                    Нет себестоимости — P&amp;L недоступен
                  </span>
                ) : basisUnknown ? (
                  <span className="muted">Нет себестоимости — P&amp;L недоступен</span>
                ) : p.unrealized_pnl != null ? (
                  money(p.unrealized_pnl)
                ) : isBond ? (
                  <span className="muted" title={p.pnl_unavailable_reason || undefined}>
                    Недоступно
                  </span>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** Local wall time for datetime-local; second precision for post-activation operations. */
export function defaultOccurredLocal(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}

/** datetime-local (local wall, second precision) → ISO-8601 UTC for the API. */
export function toIsoOccurredAt(localValue: string): string {
  // datetime-local → interpret as local wall time, send ISO with offset via Date.
  const dt = new Date(localValue);
  if (Number.isNaN(dt.getTime())) return localValue;
  return dt.toISOString();
}

function AddOperationModal({
  open,
  onClose,
  onSaved,
  portfolioId,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  portfolioId: number;
}) {
  const titleId = useId();
  const [type, setType] = useState<PersonalOperationType>("DEPOSIT");
  const [occurredAt, setOccurredAt] = useState(defaultOccurredLocal);
  const [amount, setAmount] = useState("");
  const [lots, setLots] = useState("");
  const [units, setUnits] = useState("");
  const [price, setPrice] = useState("");
  const [commission, setCommission] = useState("0");
  const [note, setNote] = useState("");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<CatalogInstrument[]>([]);
  const [instrumentId, setInstrumentId] = useState<number | null>(null);
  const [instrumentLabel, setInstrumentLabel] = useState("");
  const [instrumentAssetClass, setInstrumentAssetClass] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lotSize, setLotSize] = useState<number | null>(null);
  const [lastAttempt, setLastAttempt] = useState<{ payloadKey: string; key: string } | null>(null);

  const bondTradeBlocked =
    (type === "BUY" || type === "SELL" || type === "OPENING_POSITION") &&
    (instrumentAssetClass || "").toLowerCase() === "bond";

  useEffect(() => {
    if (!open) return;
    setError(null);
    setOccurredAt(defaultOccurredLocal());
  }, [open, type]);

  useEffect(() => {
    if (!open || query.trim().length < 1) {
      setHits([]);
      return;
    }
    const ctrl = new AbortController();
    const t = window.setTimeout(() => {
      searchCatalogInstruments({ search: query.trim(), page_size: 8 }, ctrl.signal)
        .then((page) => setHits(page.items ?? []))
        .catch(() => setHits([]));
    }, 200);
    return () => {
      ctrl.abort();
      window.clearTimeout(t);
    };
  }, [open, query]);

  const tradePreview = useMemo(() => {
    const u = Number(units || (lots && lotSize ? Number(lots) * lotSize : NaN));
    const p = Number(price);
    const c = Number(commission || 0);
    if (!Number.isFinite(u) || !Number.isFinite(p)) return null;
    const notional = u * p;
    if (type === "BUY") return { units: u, notional, cashImpact: -(notional + c) };
    if (type === "SELL") return { units: u, notional, cashImpact: notional - c };
    return null;
  }, [units, lots, lotSize, price, commission, type]);

  if (!open) return null;

  async function submit() {
    if (bondTradeBlocked) {
      setError(BOND_TRADE_USER_MSG);
      return;
    }
    setBusy(true);
    setError(null);
    const body: CreatePersonalOperationBody = {
      operation_type: type,
      occurred_at: toIsoOccurredAt(occurredAt),
      note: note || undefined,
      commission: commission || "0",
    };
    try {
      if (type === "DEPOSIT" || type === "WITHDRAWAL" || type === "OPENING_CASH" || type === "COMMISSION") {
        body.amount = amount;
      } else {
        if (!instrumentId) throw new Error("Выберите инструмент");
        body.instrument_id = instrumentId;
        body.price = price;
        if (lots) body.lots = lots;
        if (units) body.units = units;
      }
      const payloadKey = canonicalPayloadKey(body);
      const key =
        lastAttempt && lastAttempt.payloadKey === payloadKey
          ? lastAttempt.key
          : newIdempotencyKey();
      setLastAttempt({ payloadKey, key });
      body.idempotency_key = key;
      await createPersonalOperation(portfolioId, body, { idempotencyKey: key });
      setLastAttempt(null);
      onSaved();
      onClose();
    } catch (e) {
      const msg = errorMessage(e);
      try {
        const parsed = JSON.parse(msg) as { message?: string; detail?: { message?: string } };
        setError(parsed.detail?.message || parsed.message || msg);
      } catch {
        setError(msg);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal panel"
        role="dialog"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
        data-testid="add-operation-modal"
      >
        <h2 id={titleId}>Добавить операцию</h2>
        <label className="field">
          <span>Тип</span>
          <select
            value={type}
            onChange={(e) => setType(e.target.value as PersonalOperationType)}
            data-testid="op-type"
          >
            {(Object.keys(OP_LABELS) as PersonalOperationType[]).map((k) => (
              <option key={k} value={k}>
                {OP_LABELS[k]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Дата и время</span>
          <input
            type="datetime-local"
            step={1}
            value={occurredAt}
            onChange={(e) => setOccurredAt(e.target.value)}
            data-testid="op-occurred-at"
          />
        </label>
        {type === "DEPOSIT" ||
        type === "WITHDRAWAL" ||
        type === "OPENING_CASH" ||
        type === "COMMISSION" ? (
          <label className="field">
            <span>Сумма, ₽</span>
            <input
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              inputMode="decimal"
              data-testid="op-amount"
            />
          </label>
        ) : (
          <>
            <label className="field">
              <span>Инструмент</span>
              <input
                value={query || instrumentLabel}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setInstrumentId(null);
                  setInstrumentLabel("");
                  setInstrumentAssetClass(null);
                  setLotSize(null);
                }}
                placeholder="SBER, GAZP…"
                data-testid="op-instrument"
              />
            </label>
            {bondTradeBlocked ? (
              <p className="form-error" data-testid="bond-trade-blocked">
                {BOND_TRADE_USER_MSG}
              </p>
            ) : null}
            {hits.length > 0 && !instrumentId ? (
              <ul className="search-hits" data-testid="op-instrument-hits">
                {hits.map((h) => (
                  <li key={h.id}>
                    <button
                      type="button"
                      onClick={() => {
                        setInstrumentId(h.id);
                        setInstrumentLabel(`${h.symbol} · ${h.name || ""}`);
                        setInstrumentAssetClass(h.asset_class || null);
                        setQuery("");
                        setHits([]);
                        setLotSize(null);
                      }}
                    >
                      {h.symbol} — {h.name}
                      {(h.asset_class || "").toLowerCase() === "bond" ? " · облигация" : ""}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            <div className="field-row">
              <label className="field">
                <span>Лоты</span>
                <input value={lots} onChange={(e) => setLots(e.target.value)} inputMode="decimal" />
              </label>
              <label className="field">
                <span>Штуки</span>
                <input
                  value={units}
                  onChange={(e) => setUnits(e.target.value)}
                  inputMode="decimal"
                  data-testid="op-units"
                />
              </label>
              <label className="field">
                <span>Цена</span>
                <input
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  inputMode="decimal"
                  data-testid="op-price"
                />
              </label>
            </div>
            <label className="field">
              <span>Комиссия в этой сделке, ₽</span>
              <input
                value={commission}
                onChange={(e) => setCommission(e.target.value)}
                inputMode="decimal"
              />
            </label>
            {lotSize ? <p className="muted">LOTSIZE: {lotSize}</p> : null}
            {tradePreview ? (
              <p className="trade-preview" data-testid="trade-preview">
                Сделка: {tradePreview.units} шт · номинал {money(String(tradePreview.notional))} ·
                влияние на кэш {money(String(tradePreview.cashImpact))}
              </p>
            ) : null}
          </>
        )}
        <label className="field">
          <span>Комментарий</span>
          <input value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {error ? (
          <p className="form-error" data-testid="op-error">
            {error}
          </p>
        ) : null}
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={() => void submit()}
            disabled={busy || bondTradeBlocked}
            data-testid="op-submit"
          >
            {busy ? "Сохранение…" : "Подтвердить"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function PersonalPortfolioPanel({
  portfolioId,
  onChanged,
}: {
  portfolioId: number;
  onChanged?: () => void;
}) {
  const { isUser } = useKrakenRole();
  const [data, setData] = useState<PersonalSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [activating, setActivating] = useState(false);
  const [activateError, setActivateError] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const row = await getPersonalPortfolio(portfolioId, { owner: !isUser });
      setData(row);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [isUser, portfolioId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const notifyChanged = () => {
    onChanged?.();
  };

  async function onActivate() {
    if (!data) return;
    const { known, unknown } = costBasisCounts(data.positions);
    const lines = [
      "Начать учёт операций с текущего состояния?",
      "",
      `Кэш: ${money(data.summary.cash_rub)}`,
      `Позиций: ${data.positions.length}`,
      `С известной себестоимостью: ${known}`,
      `Без себестоимости: ${unknown}`,
    ];
    if (unknown > 0) {
      lines.push("", "Позиции без себестоимости останутся без P&L — это не блокирует начало учёта.");
    }
    if (!window.confirm(lines.join("\n"))) return;

    setActivating(true);
    setActivateError(null);
    try {
      const row = await activatePersonalPortfolio(portfolioId);
      setData(row);
      notifyChanged();
    } catch (e) {
      const msg = errorMessage(e);
      try {
        const parsed = JSON.parse(msg) as { message?: string; detail?: { message?: string } };
        setActivateError(parsed.detail?.message || parsed.message || msg);
      } catch {
        setActivateError(msg);
      }
    } finally {
      setActivating(false);
    }
  }

  async function onClearDraft() {
    if (!data) return;
    if (!window.confirm("Очистить портфель?\nВсе черновые позиции и кэш будут сброшены.")) return;
    setClearing(true);
    setActionError(null);
    try {
      const row = await clearDraftPortfolio(portfolioId);
      setData(row);
      notifyChanged();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setClearing(false);
    }
  }

  async function onResetPortfolio() {
    if (!data) return;
    const name = data.portfolio.name;
    if (
      !window.confirm(
        `Сбросить портфель «${name}» и начать заново?\nЖурнал операций будет удалён, портфель вернётся в режим настройки.`,
      )
    ) {
      return;
    }
    if (!window.confirm(`Подтвердите сброс портфеля «${name}». Это необратимо.`)) return;
    setResetting(true);
    setActionError(null);
    try {
      const row = await resetPersonalPortfolio(portfolioId);
      setData(row);
      notifyChanged();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setResetting(false);
    }
  }

  if (loading && !data) return <PageState kind="loading" title="Портфель" />;
  if (error && !data)
    return (
      <PageState kind="error" title="Портфель">
        {error}
      </PageState>
    );
  if (!data) return null;

  const lifecycle = portfolioLifecycleState(data);
  const draft = lifecycle === "DRAFT";
  const active = lifecycle === "ACTIVE";

  return (
    <div className="personal-portfolio-panel" data-testid="personal-portfolio-panel">
      <div className="page-header-row">
        <div>
          <h2 data-testid="personal-portfolio-name">{data.portfolio.name}</h2>
          <p className="muted">{data.summary.valuation_label}</p>
        </div>
        {active ? (
          <button
            type="button"
            className="btn primary"
            onClick={() => setModalOpen(true)}
            data-testid="add-operation-btn"
          >
            Добавить операцию
          </button>
        ) : null}
      </div>

      {draft ? (
        <>
          <div className="warning-banner" data-testid="draft-setup-banner">
            <strong>Настройка</strong>
            <span> · История операций ещё не начата.</span>
          </div>
          <div className="metric-grid" data-testid="draft-summary">
            <MetricCard label="Кэш" value={money(data.summary.cash_rub)} />
            <MetricCard label="Бумаги" value={money(data.summary.securities_value_rub)} />
            <MetricCard label="Текущая стоимость" value={money(data.summary.nav_rub)} />
            <MetricCard label="Позиций" value={String(data.positions.length)} />
          </div>
          {activateError ? (
            <p className="form-error" data-testid="activate-error">
              {activateError}
            </p>
          ) : null}
          {actionError ? (
            <p className="form-error" data-testid="portfolio-action-error">
              {actionError}
            </p>
          ) : null}
          <div className="modal-actions" style={{ marginBottom: "1rem" }}>
            <button
              type="button"
              className="btn primary"
              onClick={() => void onActivate()}
              disabled={activating}
              data-testid="activate-journal-btn"
            >
              {activating ? "Запуск…" : "Начать учёт"}
            </button>
            <button
              type="button"
              className="btn ghost"
              onClick={() => void onClearDraft()}
              disabled={clearing}
              data-testid="clear-draft-btn"
            >
              {clearing ? "Очистка…" : "Очистить портфель"}
            </button>
          </div>
          <section className="panel" data-testid="personal-positions">
            <h3>Позиции</h3>
            {data.positions.length === 0 ? (
              <EmptyState
                title="Пока нет позиций"
                reason="Добавьте кэш и инструменты на вкладке «Состав» — затем начните учёт."
              />
            ) : (
              <PositionsTable positions={data.positions} />
            )}
          </section>
        </>
      ) : null}

      {active ? (
        <>
          <div className="metric-grid" data-testid="personal-summary">
            <MetricCard label="Текущая стоимость" value={money(data.summary.nav_rub)} />
            <MetricCard label="Внесено" value={money(data.summary.contributed_rub)} />
            <MetricCard label="Выведено" value={money(data.summary.withdrawn_rub)} />
            <MetricCard label="Кэш" value={money(data.summary.cash_rub)} />
            <MetricCard label="Бумаги" value={money(data.summary.securities_value_rub)} />
            <MetricCard
              label="Инвестиционный результат"
              value={
                data.summary.investment_pnl_rub == null
                  ? "Результат недоступен — не хватает цены по части позиций"
                  : money(data.summary.investment_pnl_rub)
              }
              hint="Без учёта пополнений и выводов как «прибыли»"
            />
          </div>
          {data.summary.valuation_partial ? (
            <p className="warning-banner" data-testid="valuation-partial">
              {data.summary.valuation_label}
            </p>
          ) : null}

          <section className="panel" data-testid="personal-positions">
            <h3>Позиции</h3>
            {data.positions.length === 0 ? (
              <p className="muted">Нет позиций</p>
            ) : (
              <PositionsTable positions={data.positions} />
            )}
          </section>

          <section className="panel" data-testid="personal-operations">
            <h3>Недавние операции</h3>
            {data.operations.filter((o) => o.status === "ACTIVE").length === 0 ? (
              <p className="muted">Пока нет операций — полный журнал на вкладке «История».</p>
            ) : (
              <ul className="ops-list">
                {data.operations
                  .filter((o) => o.status === "ACTIVE")
                  .slice(0, 8)
                  .map((o) => (
                    <li key={o.id}>
                      <strong>
                        {OP_LABELS[o.operation_type as PersonalOperationType] || o.operation_type}
                      </strong>
                      <span className="muted">
                        {" "}
                        · {o.occurred_at?.slice(0, 10)}
                        {o.amount ? ` · ${money(o.amount)}` : ""}
                        {o.units && o.price ? ` · ${o.units} × ${money(o.price)}` : ""}
                      </span>
                      {!isUser && o.idempotency_key ? (
                        <div className="muted owner-meta">
                          #{o.id} · {o.source}
                          {o.occurred_at ? ` · ${o.occurred_at}` : ""}
                        </div>
                      ) : null}
                    </li>
                  ))}
              </ul>
            )}
          </section>

          {actionError ? (
            <p className="form-error" data-testid="portfolio-action-error">
              {actionError}
            </p>
          ) : null}
          <p style={{ marginTop: "1rem" }}>
            <button
              type="button"
              className="btn ghost"
              onClick={() => void onResetPortfolio()}
              disabled={resetting}
              data-testid="reset-portfolio-btn"
            >
              {resetting ? "Сброс…" : "Сбросить портфель и начать заново"}
            </button>
          </p>

          {!isUser && data.reconciliation ? (
            <section className="panel" data-testid="owner-reconciliation">
              <h3>Reconciliation</h3>
              <StatusBadge
                status={data.reconciliation.status === "OK" ? "ok" : "warning"}
                label={`Reconciliation: ${data.reconciliation.status}`}
              />
            </section>
          ) : null}
        </>
      ) : null}

      <AddOperationModal
        portfolioId={portfolioId}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSaved={() => {
          void reload();
          notifyChanged();
        }}
      />
    </div>
  );
}
