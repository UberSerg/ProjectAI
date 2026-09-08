import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  getBondsCatalog,
  type BondCatalogItem,
  type BondsCatalogResponse,
} from "../api/investment";
import { errorMessage } from "../api/client";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { MetricHelp } from "../help";

function badgeTone(state: string): "ok" | "warning" | "info" | "danger" {
  if (state === "ready") return "ok";
  if (state === "source_not_ready") return "warning";
  if (state === "missing") return "info";
  return "info";
}

export function BondsPage() {
  const navigate = useNavigate();
  const [catalog, setCatalog] = useState<BondsCatalogResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [qDraft, setQDraft] = useState("");
  const [subtype, setSubtype] = useState("");
  const [valuationOnly, setValuationOnly] = useState(false);
  const [cashflowOnly, setCashflowOnly] = useState(false);
  const [activeOnly, setActiveOnly] = useState(true);
  const pageSize = 25;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    getBondsCatalog(
      {
        page,
        page_size: pageSize,
        q: q || undefined,
        subtype: subtype || undefined,
        active: activeOnly ? true : undefined,
        valuation_available: valuationOnly ? true : undefined,
        cashflow_available: cashflowOnly ? true : undefined,
      },
      controller.signal,
    )
      .then(setCatalog)
      .catch((reason: unknown) => setError(errorMessage(reason)))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, q, subtype, valuationOnly, cashflowOnly, activeOnly]);

  const openBond = (symbol: string) => navigate(`/bonds/${encodeURIComponent(symbol)}`);

  if (loading && !catalog) return <PageState kind="loading" title="Загрузка каталога облигаций…" />;
  if (error && !catalog) return <PageState kind="error">{error}</PageState>;
  if (!catalog) return <PageState kind="empty" title="Каталог пуст" />;

  const summary = catalog.summary;
  const totalPages = Math.max(1, Math.ceil(catalog.total / catalog.page_size));

  return (
    <div data-testid="bonds-catalog-v2">
      <PageHeader
        title="Облигации"
        subtitle="Каталог Instrument Master с обогащением FI (цена / выплаты / кредит)"
        helpPageId="bonds"
      />

      <div className="card-grid" data-testid="bonds-summary-cards">
        <MetricCard label="Активные" value={summary.active} helpId="research_universe" />
        <MetricCard label="С оценкой" value={summary.valuation_ready} helpId="bond_dirty_value" />
        <MetricCard label="С выплатами" value={summary.cashflow_ready} helpId="portfolio_cashflows" />
        <MetricCard label="С кредитом" value={summary.credit_ready} helpId="credit_data_coverage" />
        <MetricCard label="ОФЗ / госдолг" value={summary.ofz} helpId="government_debt" />
        <MetricCard label="Корпоративные" value={summary.corporate} helpId="credit_rating" />
      </div>

      <article className="panel" style={{ marginTop: "1rem" }}>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "0.75rem",
            alignItems: "flex-end",
            marginBottom: "1rem",
          }}
        >
          <label>
            Поиск
            <input
              data-testid="bonds-search"
              value={qDraft}
              onChange={(e) => setQDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  setPage(1);
                  setQ(qDraft.trim());
                }
              }}
              placeholder="SECID, название, эмитент"
            />
          </label>
          <button
            type="button"
            onClick={() => {
              setPage(1);
              setQ(qDraft.trim());
            }}
          >
            Найти
          </button>
          <label>
            Тип
            <select
              data-testid="bonds-subtype-filter"
              value={subtype}
              onChange={(e) => {
                setPage(1);
                setSubtype(e.target.value);
              }}
            >
              <option value="">Все</option>
              <option value="ofz_gov">ОФЗ / госдолг</option>
              <option value="corporate_bond">Корпоративные</option>
              <option value="municipal_bond">Муниципальные</option>
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={activeOnly}
              onChange={(e) => {
                setPage(1);
                setActiveOnly(e.target.checked);
              }}
            />{" "}
            Только активные
          </label>
          <label>
            <input
              type="checkbox"
              checked={valuationOnly}
              onChange={(e) => {
                setPage(1);
                setValuationOnly(e.target.checked);
              }}
            />{" "}
            С оценкой
          </label>
          <label>
            <input
              type="checkbox"
              checked={cashflowOnly}
              onChange={(e) => {
                setPage(1);
                setCashflowOnly(e.target.checked);
              }}
            />{" "}
            С выплатами
          </label>
          <MetricHelp metricId="credit_data_coverage" />
        </div>

        {error ? <p className="muted">{error}</p> : null}

        <div className="table-wrap">
          <table data-testid="bonds-catalog-table">
            <thead>
              <tr>
                <th>SECID</th>
                <th>Название</th>
                <th>Тип</th>
                <th>Статусы</th>
                <th>Цена %</th>
              </tr>
            </thead>
            <tbody>
              {catalog.items.map((bond: BondCatalogItem) => (
                <tr
                  key={bond.instrument_id}
                  data-testid={`bond-row-${bond.symbol}`}
                  style={{ cursor: "pointer" }}
                  onClick={() => openBond(bond.symbol)}
                >
                  <td>
                    <strong>{bond.symbol}</strong>
                    {bond.master_only ? (
                      <div className="muted" style={{ fontSize: "0.8rem" }}>
                        только master
                      </div>
                    ) : null}
                  </td>
                  <td>{bond.name || "—"}</td>
                  <td>
                    {bond.is_government_debt
                      ? "Госдолг"
                      : bond.bond_type || bond.instrument_subtype || "—"}
                  </td>
                  <td>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
                      {(bond.badges || []).map((b) => (
                        <StatusBadge
                          key={b.id}
                          status={badgeTone(b.state)}
                          label={b.label}
                        />
                      ))}
                    </div>
                  </td>
                  <td>
                    {bond.clean_price_percent != null
                      ? bond.clean_price_percent.toFixed(2)
                      : "—"}
                  </td>
                </tr>
              ))}
              {catalog.items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="muted">
                    Нет облигаций по текущим фильтрам
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div
          data-testid="bonds-pagination"
          style={{
            display: "flex",
            gap: "1rem",
            alignItems: "center",
            marginTop: "1rem",
          }}
        >
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Назад
          </button>
          <span>
            Стр. {page} / {totalPages} · всего {catalog.total}
          </span>
          <button
            type="button"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            Вперёд
          </button>
        </div>
      </article>
    </div>
  );
}
