import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { errorMessage } from "../../api/client";
import {
  searchCatalogInstruments,
  type CatalogInstrument,
} from "../../api/instruments";
import {
  createPersonalOperation,
  getPersonalPrimary,
  type CreatePersonalOperationBody,
  type PersonalOperationType,
  type PersonalSummary,
} from "../../api/personalPortfolios";
import { EmptyState, MetricCard, PageState, StatusBadge } from "../../components/Ui";
import { useKrakenRole } from "../../role/KrakenRoleContext";

const OP_LABELS: Record<PersonalOperationType, string> = {
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

function AddOperationModal({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const titleId = useId();
  const [type, setType] = useState<PersonalOperationType>("DEPOSIT");
  const [occurredAt, setOccurredAt] = useState(() => new Date().toISOString().slice(0, 10));
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
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lotSize, setLotSize] = useState<number | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
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
    setBusy(true);
    setError(null);
    const key = newIdempotencyKey();
    const body: CreatePersonalOperationBody = {
      operation_type: type,
      occurred_at: occurredAt,
      note: note || undefined,
      idempotency_key: key,
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
      await createPersonalOperation(body, { idempotencyKey: key });
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
          <span>Дата</span>
          <input type="date" value={occurredAt} onChange={(e) => setOccurredAt(e.target.value)} />
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
                  setLotSize(null);
                }}
                placeholder="SBER, GAZP…"
                data-testid="op-instrument"
              />
            </label>
            {hits.length > 0 && !instrumentId ? (
              <ul className="search-hits" data-testid="op-instrument-hits">
                {hits.map((h) => (
                  <li key={h.id}>
                    <button
                      type="button"
                      onClick={() => {
                        setInstrumentId(h.id);
                        setInstrumentLabel(`${h.symbol} · ${h.name || ""}`);
                        setQuery("");
                        setHits([]);
                        setLotSize(null);
                      }}
                    >
                      {h.symbol} — {h.name}
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
            disabled={busy}
            data-testid="op-submit"
          >
            {busy ? "Сохранение…" : "Подтвердить"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function PersonalPortfolioPanel() {
  const { isUser } = useKrakenRole();
  const [data, setData] = useState<PersonalSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const row = await getPersonalPrimary({ owner: !isUser });
      setData(row);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [isUser]);

  useEffect(() => {
    void reload();
  }, [reload]);

  if (loading && !data) return <PageState kind="loading" title="Портфель" />;
  if (error && !data)
    return (
      <PageState kind="error" title="Портфель">
        {error}
      </PageState>
    );
  if (!data) return null;

  const empty = !data.portfolio.has_operations;

  return (
    <div className="personal-portfolio-panel" data-testid="personal-portfolio-panel">
      <div className="page-header-row">
        <div>
          <h2 data-testid="personal-portfolio-name">{data.portfolio.name}</h2>
          <p className="muted">{data.summary.valuation_label}</p>
        </div>
        <button
          type="button"
          className="btn primary"
          onClick={() => setModalOpen(true)}
          data-testid="add-operation-btn"
        >
          Добавить операцию
        </button>
      </div>

      {empty ? (
        <EmptyState
          title="Личный портфель ещё пуст"
          reason="Добавьте первое пополнение или текущие позиции — без выдуманных сделок."
          action={
            <button type="button" className="btn primary" onClick={() => setModalOpen(true)}>
              Добавить операцию
            </button>
          }
        />
      ) : (
        <>
          <div className="metric-grid" data-testid="personal-summary">
            <MetricCard label="Текущая стоимость" value={money(data.summary.nav_rub)} />
            <MetricCard label="Внесено" value={money(data.summary.contributed_rub)} />
            <MetricCard label="Выведено" value={money(data.summary.withdrawn_rub)} />
            <MetricCard label="Кэш" value={money(data.summary.cash_rub)} />
            <MetricCard label="Бумаги" value={money(data.summary.securities_value_rub)} />
            <MetricCard
              label="Инвестиционный результат"
              value={money(data.summary.investment_pnl_rub)}
              hint="Без учёта пополнений и выводов как «прибыли»"
            />
          </div>
          {data.summary.valuation_partial ? (
            <p className="warning-banner" data-testid="valuation-partial">
              Оценка частичная: для части позиций цена недоступна (не подставляем ноль).
            </p>
          ) : null}

          <section className="panel" data-testid="personal-positions">
            <h3>Позиции</h3>
            {data.positions.length === 0 ? (
              <p className="muted">Нет позиций</p>
            ) : (
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
                  {data.positions.map((p) => (
                    <tr key={p.instrument_id}>
                      <td>
                        <strong>{p.secid}</strong>
                        <div className="muted">{p.name}</div>
                      </td>
                      <td>
                        {p.units}
                        {p.lots ? <div className="muted">{p.lots} лот(ов)</div> : null}
                      </td>
                      <td>{p.average_price != null ? money(p.average_price) : "—"}</td>
                      <td>
                        {p.price_available ? money(p.current_price) : "Цена недоступна"}
                        {p.price_date ? <div className="muted">{p.price_date}</div> : null}
                      </td>
                      <td>{p.market_value != null ? money(p.market_value) : "—"}</td>
                      <td>{p.unrealized_pnl != null ? money(p.unrealized_pnl) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="panel" data-testid="personal-operations">
            <h3>Недавние операции</h3>
            <ul className="ops-list">
              {data.operations
                .filter((o) => o.status === "ACTIVE")
                .slice(0, 20)
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
                      <div className="muted owner-meta">#{o.id} · {o.source}</div>
                    ) : null}
                  </li>
                ))}
            </ul>
          </section>

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
      )}

      <AddOperationModal open={modalOpen} onClose={() => setModalOpen(false)} onSaved={() => void reload()} />
    </div>
  );
}
