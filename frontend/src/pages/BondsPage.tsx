import { useEffect, useState } from "react";
import {
  getBonds,
  getHurdle,
  getInvestmentReadiness,
  previewAllocation,
  type BondInstrument,
  type HurdleQuote,
  type ReadinessCheck,
} from "../api/investment";
import { errorMessage } from "../api/client";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";

const readinessLabels: Record<string, string> = {
  CBR_HURDLE_READY: "Порог ключевой ставки ЦБ РФ",
  FIXED_INCOME_DATA_READY: "Данные облигаций",
  BOND_CASHFLOWS_READY: "Денежные потоки облигаций",
  REALISTIC_LOTS_READY: "Реалистичные целые лоты",
  TRANSACTION_COSTS_READY: "Профиль торговых издержек",
  ASSET_ALLOCATION_RESEARCH_READY: "Research asset allocation",
  TAX_MODEL_NOT_READY: "Налоги (ещё не моделируются)",
  CREDIT_QUALITY_NOT_READY: "Кредитное качество (нет рейтинга)",
  DIVIDEND_TOTAL_RETURN_NOT_READY: "Total return по дивидендам",
  REAL_MONEY_NOT_READY: "Реальные деньги",
};

export function BondsPage() {
  const [hurdle, setHurdle] = useState<HurdleQuote | null>(null);
  const [checks, setChecks] = useState<ReadinessCheck[]>([]);
  const [bonds, setBonds] = useState<BondInstrument[]>([]);
  const [capital, setCapital] = useState(100000);
  const [price, setPrice] = useState(980);
  const [lotSize, setLotSize] = useState(1);
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof previewAllocation>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getHurdle(controller.signal),
      getInvestmentReadiness(controller.signal),
      getBonds(controller.signal),
    ])
      .then(([h, r, b]) => {
        setHurdle(h);
        setChecks(r.checks);
        setBonds(b.items);
      })
      .catch((reason: unknown) => setError(errorMessage(reason)))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  if (loading) return <PageState kind="loading" title="Загрузка инвестиционного контура…" />;

  return (
    <div className="bonds-page">
      <PageHeader
        title="Облигации"
        description="Ключевая ставка как экономический порог, готовность данных и реалистичный расчёт целых лотов."
        helpPageId="investment"
      />
      {error ? <div className="banner banner-warning">{error}</div> : null}

      <div className="card-grid">
        <MetricCard
          label="Ключевая ставка ЦБ РФ"
          value={hurdle?.annual_rate == null ? "Нет данных" : `${(hurdle.annual_rate * 100).toFixed(2)}%`}
          hint="Это порог сравнения, а не безрисковая депозитная ставка."
          helpId="cbr_hurdle"
        />
        <MetricCard label="Дата ставки" value={hurdle?.as_of ?? "—"} helpId="known_at_quality" />
        <MetricCard
          label="Порог 20 торговых дней"
          value={
            hurdle?.hurdle_20d == null ? "—" : `${(hurdle.hurdle_20d * 100).toFixed(3)}%`
          }
          helpId="excess_return"
        />
        <MetricCard
          label="Порог 1 год"
          value={hurdle?.hurdle_1y == null ? "—" : `${(hurdle.hurdle_1y * 100).toFixed(2)}%`}
          helpId="cbr_hurdle"
        />
        <MetricCard label="Облигаций в контуре" value={bonds.length} />
      </div>

      <div className="card">
        <h3>Готовность инвестиционного контура</h3>
        <ul className="plain-list">
          {checks.map((check) => (
            <li key={check.code}>
              {readinessLabels[check.code] ?? check.code}:{" "}
              <StatusBadge status={check.status.toLowerCase()} />
            </li>
          ))}
        </ul>
      </div>

      <div className="card">
        <h3>Калькулятор портфеля 100 000 ₽</h3>
        <p className="muted">Исследовательский preview: целые лоты, комиссии и остаток денег.</p>
        <div className="investment-calculator">
          <label>Капитал, ₽ <input type="number" value={capital} onChange={(e) => setCapital(Number(e.target.value))} /></label>
          <label>Цена, ₽ <input type="number" value={price} onChange={(e) => setPrice(Number(e.target.value))} /></label>
          <label>Размер лота <input type="number" value={lotSize} onChange={(e) => setLotSize(Number(e.target.value))} /></label>
          <button
            type="button"
            onClick={() =>
              previewAllocation({
                capital,
                cost_bps: 5,
                candidates: [{ symbol: "BOND", sleeve: "FIXED_INCOME", price, lot_size: lotSize, target_weight: 1 }],
              }).then(setPreview).catch((reason: unknown) => setError(errorMessage(reason)))
            }
          >
            Рассчитать
          </button>
        </div>
        {preview ? (
          <div className="metric-grid">
            <MetricCard label="Лотов" value={preview.positions[0]?.lots ?? 0} />
            <MetricCard label="Комиссии" value={`${Number(preview.fees).toFixed(2)} ₽`} />
            <MetricCard label="Остаток" value={`${Number(preview.cash_remainder).toFixed(2)} ₽`} />
          </div>
        ) : null}
      </div>

      <div className="card">
        <h3>Инструменты fixed income</h3>
        {bonds.length ? (
          <div className="table-wrap"><table><thead><tr><th>Тикер</th><th>Тип</th><th>Номинал</th><th>Поддержка</th><th>Кредит</th></tr></thead>
            <tbody>{bonds.map((bond) => <tr key={bond.instrument_id}><td>{bond.symbol}</td><td>{bond.bond_type}</td><td>{bond.nominal ?? "—"}</td><td>{bond.support_status}</td><td>{bond.credit_quality_status}</td></tr>)}</tbody>
          </table></div>
        ) : <p className="muted">Доверенные данные облигаций ещё не загружены — NOT_READY.</p>}
      </div>

      <div className="card">
        <h3>Research Lab: порог доходности</h3>
        <p>В сравнении стратегии должен быть отдельный ответ: «Обогнал ли Kraken порог ключевой ставки?»</p>
        <p className="muted">До появления сопоставимого периода результат — INCONCLUSIVE.</p>
      </div>
    </div>
  );
}
