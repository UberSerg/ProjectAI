import { useEffect, useMemo, useState } from "react";
import {
  getBondAccountingPreview,
  getBonds,
  getFixedIncomeRisk,
  getHurdle,
  getInvestmentReadiness,
  previewAllocation,
  type AccountingPreview,
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
  BOND_TERMS_READY: "Условия облигаций",
  COUPON_CASHFLOWS_READY: "График купонов",
  REDEMPTION_READY: "Погашение",
  AMORTIZATION_PARTIAL: "Амортизация (частично)",
  OFFER_POLICY_NOT_READY: "Политика оферт",
  CREDIT_QUALITY_NOT_READY: "Кредитное качество (foundation)",
  LIQUIDITY_FOUNDATION_READY: "Ликвидность (foundation)",
  BOND_HISTORICAL_TOTAL_RETURN: "Исторический total return облигаций",
  BOND_CASHFLOWS_READY: "Денежные потоки облигаций",
  REALISTIC_LOTS_READY: "Реалистичные целые лоты",
  TRANSACTION_COSTS_READY: "Профиль торговых издержек",
  ASSET_ALLOCATION_RESEARCH_READY: "Research asset allocation",
  TAX_MODEL_NOT_READY: "Налоги (ещё не моделируются)",
  DIVIDEND_TOTAL_RETURN_NOT_READY: "Total return по дивидендам",
  REAL_MONEY_NOT_READY: "Реальные деньги",
};

function fmtMoney(value: number | string | null | undefined): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return "—";
  return `${n.toFixed(2)} ₽`;
}

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
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof previewAllocation>> | null>(null);
  const [selected, setSelected] = useState<BondInstrument | null>(null);
  const [accounting, setAccounting] = useState<AccountingPreview | null>(null);
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

  useEffect(() => {
    if (!selected || selected.support_status !== "SUPPORTED") {
      setAccounting(null);
      return;
    }
    const controller = new AbortController();
    getBondAccountingPreview(selected.symbol, 1, controller.signal)
      .then(setAccounting)
      .catch((reason: unknown) => setError(errorMessage(reason)));
    return () => controller.abort();
  }, [selected]);

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
        description="Купоны, учёт потоков и риск-фильтры. Уметь посчитать потоки ≠ считать бумагу безопасной."
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
          label="Порог 1 год"
          value={hurdle?.hurdle_1y == null ? "—" : `${(hurdle.hurdle_1y * 100).toFixed(2)}%`}
          helpId="cbr_hurdle"
        />
        <MetricCard label="Облигаций в контуре" value={bonds.length} helpId="investment_eligibility" />
        <MetricCard
          label="SUPPORTED"
          value={bonds.filter((b) => b.support_status === "SUPPORTED").length}
          helpId="bond_supported"
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
          <p>Рейтинг: {sample?.credit_status === "AVAILABLE" ? "есть observed" : "Нет данных"}</p>
          <p>Источник: — (агентские ленты требуют доступ)</p>
          <p>
            Статус: <StatusBadge status={(sample?.credit_status ?? "unknown").toLowerCase()} />
          </p>
          <p className="muted">
            Высокая доходность может отражать риск дефолта. Отсутствие рейтинга не означает
            безопасность. <MetricHelp metricId="unknown_rating" />
          </p>
        </div>
        <div className="card">
          <h3>
            Ликвидность <MetricHelp metricId="liquidity_risk" />
          </h3>
          <p>Объём торгов: {riskSummary?.items?.[0] ? "см. статусы по инструментам" : "Нет данных"}</p>
          <p>Последняя сделка: по snapshot / candles, если есть</p>
          <p>
            Статус:{" "}
            <StatusBadge status={(sample?.liquidity_status ?? "unknown").toLowerCase()} />
          </p>
          <p className="muted">Риск ликвидности — сложность быстро купить/продать по ожидаемой цене.</p>
        </div>
      </div>

      <div className="card">
        <h3>Готовность fixed income</h3>
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
            <input type="number" value={capital} onChange={(e) => setCapital(Number(e.target.value))} />
          </label>
          <label>
            Цена, ₽ <input type="number" value={price} onChange={(e) => setPrice(Number(e.target.value))} />
          </label>
          <label>
            Размер лота{" "}
            <input type="number" value={lotSize} onChange={(e) => setLotSize(Number(e.target.value))} />
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
              <MetricCard label="Остаток" value={`${Number(preview.cash_remainder).toFixed(2)} ₽`} />
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
            <select value={filterEligibility} onChange={(e) => setFilterEligibility(e.target.value)}>
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
        <p className="muted">
          Корректный расчёт купонов не равен безопасности эмитента. Accounting YES ≠ Investment YES.
        </p>
        {filtered.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Тикер</th>
                  <th>Тип</th>
                  <th>Цена %</th>
                  <th>НКД</th>
                  <th>Покупка (оценка)</th>
                  <th>Ближ. купон</th>
                  <th>Купон, ₽</th>
                  <th>Погашение</th>
                  <th>YTM</th>
                  <th>Поддержка</th>
                  <th>Accounting</th>
                  <th>Credit</th>
                  <th>Liquidity</th>
                  <th>Eligibility</th>
                  <th>Данные</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((bond) => (
                  <tr
                    key={bond.instrument_id}
                    className={selected?.instrument_id === bond.instrument_id ? "row-selected" : undefined}
                    onClick={() => setSelected(bond)}
                    style={{ cursor: "pointer" }}
                  >
                    <td>{bond.symbol}</td>
                    <td>{bond.bond_type}</td>
                    <td>{bond.clean_price_percent ?? "—"}</td>
                    <td>{bond.nkd ?? "—"}</td>
                    <td title="Чистая цена + НКД на 1 бумагу">{fmtMoney(bond.dirty_estimate)}</td>
                    <td>{bond.next_coupon_date ?? "—"}</td>
                    <td>{bond.next_coupon_amount ?? "—"}</td>
                    <td>{bond.maturity_date ?? "—"}</td>
                    <td title={bond.ytm_note ?? undefined}>{bond.ytm ?? "—"}</td>
                    <td>
                      <StatusBadge status={bond.support_status.toLowerCase()} />
                    </td>
                    <td>{bond.accounting_quality ?? "—"}</td>
                    <td>{bond.credit_status ?? bond.credit_quality_status}</td>
                    <td>{bond.liquidity_status ?? "UNKNOWN"}</td>
                    <td>{bond.investment_eligibility ?? "RESEARCH_ONLY"}</td>
                    <td title={bond.data_quality?.source}>
                      {bond.data_quality?.known_at_quality ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">Нет инструментов под выбранные фильтры / данные ещё не загружены.</p>
        )}
      </div>

      {selected ? (
        <div className="card">
          <h3>
            Детали: {selected.symbol}{" "}
            <span className="muted">({selected.currency_display ?? selected.currency})</span>
          </h3>
          <p>
            <strong>Почему Kraken пока не может использовать эту облигацию:</strong>{" "}
            {selected.support_status === "SUPPORTED"
              ? "Может использовать для учёта денежных потоков (не для реального портфеля без credit gate)."
              : selected.why_not_supported ?? "Недостаточно данных"}
          </p>
          <p className="muted">{selected.credit_safety_note}</p>
          {selected.currency_raw ? (
            <p className="muted">Сырое значение MOEX FACEUNIT: {selected.currency_raw}</p>
          ) : null}
          {accounting?.status === "READY" ? (
            <div className="metric-grid">
              <MetricCard label="Чистая сумма" value={fmtMoney(accounting.clean_total)} helpId="dirty_price" />
              <MetricCard label="НКД" value={fmtMoney(accounting.nkd_total)} helpId="nkd" />
              <MetricCard
                label="Грязная покупка"
                value={fmtMoney(accounting.dirty_purchase)}
                helpId="dirty_price"
              />
              <MetricCard label="Комиссия" value={fmtMoney(accounting.fees)} helpId="transaction_costs" />
              <MetricCard
                label="Купоны (всего)"
                value={fmtMoney(accounting.coupon_total)}
                helpId="bond_coupon_schedule"
              />
              <MetricCard label="Погашение" value={fmtMoney(accounting.redemption_total)} helpId="bond_redemption" />
              <MetricCard
                label="Total return до налогов"
                value={fmtMoney(accounting.total_return_before_tax)}
                helpId="tax_not_modeled"
              />
              <MetricCard label="YTM (MOEX)" value={accounting.ytm_value ?? "—"} helpId="bond_ytm" />
            </div>
          ) : accounting ? (
            <p className="muted">{accounting.note ?? accounting.status}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
