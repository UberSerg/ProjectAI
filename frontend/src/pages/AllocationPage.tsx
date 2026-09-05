import { useEffect, useState } from "react";
import {
  compareAllocations,
  decideAllocation,
  getHurdle,
  type AllocationDecideResponse,
  type AllocationDecisionView,
  type HurdleQuote,
} from "../api/investment";
import { errorMessage } from "../api/client";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";

function pct(weight: number | undefined): string {
  if (weight == null) return "—";
  return `${(weight * 100).toFixed(1)}%`;
}

function money(value: string | number | undefined): string {
  if (value == null) return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return "—";
  return `${n.toFixed(0)} ₽`;
}

export function AllocationPage() {
  const [hurdle, setHurdle] = useState<HurdleQuote | null>(null);
  const [policyId, setPolicyId] = useState("CBR_HURDLE_GATE_V0");
  const [excessBps, setExcessBps] = useState(-200);
  const [result, setResult] = useState<AllocationDecideResponse | null>(null);
  const [comparisons, setComparisons] = useState<
    Array<{ policy: { id: string; title: string }; decision: AllocationDecisionView }>
  >([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const run = () => {
    setError(null);
    const excess = excessBps / 10000;
    Promise.all([
      decideAllocation({
        policy_id: policyId,
        capital: 100000,
        equity_expected_excess_return: excess,
        equity_price: 300,
        equity_lot_size: 10,
        bond_price: 980,
        bond_lot_size: 1,
        cost_bps: 5,
      }),
      compareAllocations({ capital: 100000, equity_expected_excess_return: excess }),
    ])
      .then(([decide, compare]) => {
        setResult(decide);
        setComparisons(compare.comparisons);
      })
      .catch((reason: unknown) => setError(errorMessage(reason)));
  };

  useEffect(() => {
    const controller = new AbortController();
    getHurdle(controller.signal)
      .then(setHurdle)
      .catch((reason: unknown) => setError(errorMessage(reason)))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!loading) run();
    // initial preview once hurdle load settles
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  if (loading) return <PageState kind="loading" title="Загрузка распределения капитала…" />;

  const decision = result?.decision;
  const sleeves = result?.lots.sleeve_cash_used;

  return (
    <div className="allocation-page">
      <PageHeader
        title="Распределение капитала"
        description="Как Kraken распределил бы капитал между риском и защитной частью."
        helpPageId="allocation"
      />
      {error ? <div className="banner banner-warning">{error}</div> : null}

      <div className="card">
        <h3>Текущий рыночный контекст</h3>
        <div className="card-grid">
          <MetricCard
            label="Ключевая ставка ЦБ РФ"
            value={hurdle?.annual_rate == null ? "Нет данных" : `${(hurdle.annual_rate * 100).toFixed(2)}%`}
            helpId="cbr_hurdle"
          />
          <MetricCard
            label="Порог 20д"
            value={hurdle?.hurdle_20d == null ? "—" : `${(hurdle.hurdle_20d * 100).toFixed(3)}%`}
            helpId="hurdle"
          />
          <MetricCard
            label="Порог 1г"
            value={hurdle?.hurdle_1y == null ? "—" : `${(hurdle.hurdle_1y * 100).toFixed(2)}%`}
            helpId="hurdle"
          />
        </div>
      </div>

      <div className="card">
        <h3>Research preview 100 000 ₽</h3>
        <div className="investment-calculator">
          <label>
            Политика{" "}
            <select value={policyId} onChange={(e) => setPolicyId(e.target.value)}>
              <option value="CBR_HURDLE_GATE_V0">CBR Hurdle Gate V0</option>
              <option value="STATIC_100_EQUITY">100% Equity</option>
              <option value="STATIC_100_FIXED_INCOME">100% Fixed Income</option>
              <option value="STATIC_100_CASH">100% Cash</option>
            </select>
          </label>
          <label>
            Equity excess (bps vs CBR){" "}
            <input
              type="number"
              value={excessBps}
              onChange={(e) => setExcessBps(Number(e.target.value))}
            />
          </label>
          <button type="button" onClick={run}>
            Рассчитать
          </button>
        </div>
        <p className="muted">
          Вход excess — research input. Модели пока с <code>prediction_quality=UNKNOWN</code>. Нет
          magic investment_score.
        </p>
      </div>

      {decision ? (
        <>
          <div className="card-grid">
            <MetricCard label="Акции" value={pct(decision.equity_weight)} helpId="equity_sleeve" />
            <MetricCard
              label="Облигации"
              value={pct(decision.fixed_income_weight)}
              helpId="fixed_income_sleeve"
            />
            <MetricCard label="Cash" value={pct(decision.cash_weight)} helpId="cash_sleeve" />
            <MetricCard label="Статус" value={decision.status} helpId="asset_allocation" />
          </div>

          <div className="card">
            <h3>Почему так</h3>
            <p>{decision.explanation_ru}</p>
            <ul className="plain-list">
              {decision.reason_codes_ru.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            <p className="muted">{decision.bond_safety_reminder}</p>
          </div>

          <div className="card-grid">
            <div className="card">
              <h3>Акции</h3>
              <p>Ожидаемая возможность: research excess {excessBps} bps</p>
              <p>Почему: см. explanation выше</p>
              <p>
                После лотов: <strong>{money(sleeves?.EQUITY_ALPHA)}</strong>
              </p>
            </div>
            <div className="card">
              <h3>Облигации</h3>
              <p>Доступная доходность: только observed / не гарантирована</p>
              <p>Риски: кредитный риск, unsupported schedules</p>
              <p>
                После лотов: <strong>{money(sleeves?.FIXED_INCOME)}</strong>
              </p>
              <p className="muted">{decision.bond_safety_reminder}</p>
            </div>
            <div className="card">
              <h3>Денежная альтернатива</h3>
              <p>Benchmark: CBR</p>
              <p>
                Остаток cash: <strong>{money(sleeves?.CASH)}</strong>
              </p>
            </div>
          </div>

          <div className="card">
            <h3>Economic verdict framing</h3>
            <p>
              <strong>{result?.economic_verdict.question_ru}</strong>
            </p>
            <p className="muted">{result?.economic_verdict.answer_ru}</p>
          </div>
        </>
      ) : null}

      <div className="card">
        <h3>Research Lab: сравнение политик</h3>
        <p className="muted">Без автоматического выбора победителя.</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Политика</th>
                <th>Equity</th>
                <th>FI</th>
                <th>Cash</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {comparisons.map((row) => (
                <tr key={row.policy.id}>
                  <td>{row.policy.title}</td>
                  <td>{pct(row.decision.equity_weight)}</td>
                  <td>{pct(row.decision.fixed_income_weight)}</td>
                  <td>{pct(row.decision.cash_weight)}</td>
                  <td>
                    <StatusBadge status={row.decision.status.toLowerCase()} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
