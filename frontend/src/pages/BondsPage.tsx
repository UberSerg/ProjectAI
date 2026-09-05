import { useEffect, useMemo, useState } from "react";
import {
  getBonds,
  getFixedIncomeRisk,
  getHurdle,
  getInvestmentReadiness,
  previewAllocation,
  type BondInstrument,
  type HurdleQuote,
  type ReadinessCheck,
} from "../api/investment";
import { errorMessage } from "../api/client";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { MetricHelp } from "../help";

const readinessLabels: Record<string, string> = {
  CBR_HURDLE_READY: "Порог ключевой ставки ЦБ РФ",
  FIXED_INCOME_DATA_READY: "Данные облигаций",
  BOND_CASHFLOWS_READY: "Денежные потоки облигаций",
  REALISTIC_LOTS_READY: "Реалистичные целые лоты",
  TRANSACTION_COSTS_READY: "Профиль торговых издержек",
  ASSET_ALLOCATION_RESEARCH_READY: "Research asset allocation",
  TAX_MODEL_NOT_READY: "Налоги (ещё не моделируются)",
  CREDIT_QUALITY_NOT_READY: "Кредитное качество (foundation)",
  LIQUIDITY_FOUNDATION_READY: "Ликвидность (foundation)",
  DIVIDEND_TOTAL_RETURN_NOT_READY: "Total return по дивидендам",
  REAL_MONEY_NOT_READY: "Реальные деньги",
};

export function BondsPage() {
  const [hurdle, setHurdle] = useState<HurdleQuote | null>(null);
  const [checks, setChecks] = useState<ReadinessCheck[]>([]);
  const [bonds, setBonds] = useState<BondInstrument[]>([]);
  const [riskSummary, setRiskSummary] = useState<Awaited<
    ReturnType<typeof getFixedIncomeRisk>
  > | null>(null);
  const [capital, setCapital] = useState(100000);
  const [price, setPrice] = useState(980);
  const [lotSize, setLotSize] = useState(1);
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof previewAllocation>> | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filterCredit, setFilterCredit] = useState("");
  const [filterLiquidity, setFilterLiquidity] = useState("");
  const [filterEligibility, setFilterEligibility] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getHurdle(controller.signal),
      getInvestmentReadiness(controller.signal),
      getBonds(controller.signal),
      getFixedIncomeRisk(controller.signal),
    ])
      .then(([h, r, b, risk]) => {
        setHurdle(h);
        setChecks(r.checks);
        setBonds(b.items);
        setRiskSummary(risk);
      })
      .catch((reason: unknown) => setError(errorMessage(reason)))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  const filtered = useMemo(() => {
    return bonds.filter((bond) => {
      if (filterCredit && (bond.credit_status ?? bond.credit_quality_status) !== filterCredit) {
        return false;
      }
      if (filterLiquidity && (bond.liquidity_status ?? "UNKNOWN") !== filterLiquidity) {
        return false;
      }
      if (
        filterEligibility &&
        (bond.investment_eligibility ?? "RESEARCH_ONLY") !== filterEligibility
      ) {
        return false;
      }
      return true;
    });
  }, [bonds, filterCredit, filterLiquidity, filterEligibility]);

  if (loading) return <PageState kind="loading" title="Загрузка инвестиционного контура…" />;

  const sample = bonds[0];

  return (
    <div className="bonds-page">
      <PageHeader
        title="Облигации"
        description="Accounting quality ≠ investment quality. Доходность не равна безопасности."
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
          label="Облигаций в контуре"
          value={bonds.length}
          helpId="investment_eligibility"
        />
        <MetricCard
          label="Credit UNKNOWN"
          value={String(riskSummary?.credit_coverage?.UNKNOWN ?? "—")}
          helpId="credit_quality"
        />
      </div>

      <div className="card-grid">
        <div className="card">
          <h3>
            Кредитное качество <MetricHelp metricId="credit_quality" />
          </h3>
          <p>
            Рейтинг: {sample?.credit_status === "AVAILABLE" ? "есть observed" : "Нет данных"}
          </p>
          <p>Источник: — (агентские ленты требуют доступ)</p>
          <p>
            Статус:{" "}
            <StatusBadge status={(sample?.credit_status ?? "unknown").toLowerCase()} />
          </p>
          <p className="muted">
            Почему важно: высокая доходность может отражать риск дефолта. Отсутствие рейтинга не
            означает безопасность. <MetricHelp metricId="unknown_rating" />
          </p>
        </div>
        <div className="card">
          <h3>
            Ликвидность <MetricHelp metricId="liquidity_risk" />
          </h3>
          <p>
            Объём торгов:{" "}
            {riskSummary?.items?.[0] ? "см. статусы по инструментам" : "Нет данных"}
          </p>
          <p>Последняя сделка: по snapshot / candles, если есть</p>
          <p>
            Статус:{" "}
            <StatusBadge
              status={(sample?.liquidity_status ?? "unknown").toLowerCase()}
            />
          </p>
          <p className="muted">
            Риск ликвидности — сложность быстро купить/продать по ожидаемой цене.
          </p>
        </div>
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
          <label>
            Капитал, ₽{" "}
            <input
              type="number"
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
            />
          </label>
          <label>
            Цена, ₽{" "}
            <input type="number" value={price} onChange={(e) => setPrice(Number(e.target.value))} />
          </label>
          <label>
            Размер лота{" "}
            <input
              type="number"
              value={lotSize}
              onChange={(e) => setLotSize(Number(e.target.value))}
            />
          </label>
          <button
            type="button"
            onClick={() =>
              previewAllocation({
                capital,
                cost_bps: 5,
                candidates: [
                  {
                    symbol: "BOND",
                    sleeve: "FIXED_INCOME",
                    price,
                    lot_size: lotSize,
                    target_weight: 1,
                  },
                ],
              })
                .then(setPreview)
                .catch((reason: unknown) => setError(errorMessage(reason)))
            }
          >
            Рассчитать
          </button>
        </div>
        {preview ? (
          <>
            <div className="metric-grid">
              <MetricCard label="Лотов" value={preview.positions[0]?.lots ?? 0} />
              <MetricCard label="Комиссии" value={`${Number(preview.fees).toFixed(2)} ₽`} />
              <MetricCard
                label="Остаток"
                value={`${Number(preview.cash_remainder).toFixed(2)} ₽`}
              />
            </div>
            {(preview as { warnings?: string[] }).warnings?.length ? (
              <div className="banner banner-warning">
                <strong>Предупреждения</strong>
                <ul className="plain-list">
                  {(preview as { warnings?: string[] }).warnings!.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        ) : null}
      </div>

      <div className="card">
        <h3>Research Lab: фильтры качества</h3>
        <div className="investment-calculator">
          <label>
            Credit quality{" "}
            <select value={filterCredit} onChange={(e) => setFilterCredit(e.target.value)}>
              <option value="">Все</option>
              <option value="UNKNOWN">UNKNOWN</option>
              <option value="AVAILABLE">AVAILABLE</option>
              <option value="NOT_RATED">NOT_RATED</option>
              <option value="STALE">STALE</option>
            </select>
          </label>
          <label>
            Liquidity{" "}
            <select value={filterLiquidity} onChange={(e) => setFilterLiquidity(e.target.value)}>
              <option value="">Все</option>
              <option value="GOOD">GOOD</option>
              <option value="MEDIUM">MEDIUM</option>
              <option value="LOW">LOW</option>
              <option value="UNKNOWN">UNKNOWN</option>
            </select>
          </label>
          <label>
            Investment eligibility{" "}
            <select
              value={filterEligibility}
              onChange={(e) => setFilterEligibility(e.target.value)}
            >
              <option value="">Все</option>
              <option value="RESEARCH_ONLY">RESEARCH_ONLY</option>
              <option value="REAL_PORTFOLIO_CANDIDATE">REAL_PORTFOLIO_CANDIDATE</option>
              <option value="BLOCKED">BLOCKED</option>
            </select>
          </label>
        </div>
        <p className="muted">Фильтры research-only — без оптимизации и автовыбора победителя.</p>
      </div>

      <div className="card">
        <h3>Инструменты fixed income</h3>
        {filtered.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Тикер</th>
                  <th>Тип</th>
                  <th>Валюта</th>
                  <th>Номинал</th>
                  <th>Accounting</th>
                  <th>Credit</th>
                  <th>Liquidity</th>
                  <th>Eligibility</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((bond) => (
                  <tr key={bond.instrument_id}>
                    <td>{bond.symbol}</td>
                    <td>{bond.bond_type}</td>
                    <td title={bond.currency_raw ? `MOEX FACEUNIT=${bond.currency_raw}` : undefined}>
                      {bond.currency_display ?? "—"}
                    </td>
                    <td>{bond.nominal ?? "—"}</td>
                    <td>{bond.accounting_quality ?? "—"}</td>
                    <td>{bond.credit_status ?? bond.credit_quality_status}</td>
                    <td>{bond.liquidity_status ?? "UNKNOWN"}</td>
                    <td>{bond.investment_eligibility ?? "RESEARCH_ONLY"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">Нет инструментов под выбранные фильтры / данные ещё не загружены.</p>
        )}
      </div>
    </div>
  );
}
