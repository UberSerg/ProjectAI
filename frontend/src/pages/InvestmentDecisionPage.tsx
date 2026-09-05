import { useEffect, useState } from "react";
import {
  compareInvestmentDecisions,
  decideInvestment,
  getHurdle,
  type HurdleQuote,
  type InvestmentDecisionResponse,
} from "../api/investment";
import { errorMessage } from "../api/client";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";

function pct(weight: number | undefined | null): string {
  if (weight == null) return "—";
  return `${(weight * 100).toFixed(1)}%`;
}

function rate(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

export function InvestmentDecisionPage() {
  const [hurdle, setHurdle] = useState<HurdleQuote | null>(null);
  const [profileId, setProfileId] = useState("BALANCED_ALLOCATION_V0");
  const [excessBps, setExcessBps] = useState(0);
  const [result, setResult] = useState<InvestmentDecisionResponse | null>(null);
  const [compare, setCompare] = useState<Awaited<
    ReturnType<typeof compareInvestmentDecisions>
  > | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const run = () => {
    setError(null);
    const excess = excessBps / 10000;
    Promise.all([
      decideInvestment({
        profile_id: profileId,
        capital: 100000,
        equity_expected_excess_return: excess,
      }),
      compareInvestmentDecisions({ capital: 100000, equity_expected_excess_return: excess }),
    ])
      .then(([decide, cmp]) => {
        setResult(decide);
        setCompare(cmp);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  if (loading) return <PageState kind="loading" title="Загрузка инвестиционного решения…" />;

  const decision = result?.decision;
  const equity = result?.equity_opportunity;
  const fi = result?.fixed_income_opportunity;
  const cash = result?.cash_opportunity;
  const cal = result?.calibration;

  return (
    <div className="allocation-page">
      <PageHeader
        title="Инвестиционное решение Kraken"
        description="Почему Kraken выбрал бы такую структуру капитала: возможность, риск и объяснение."
        helpPageId="investment_decision"
      />
      {error ? <div className="banner banner-warning">{error}</div> : null}

      <div className="card">
        <h3>Контекст</h3>
        <div className="card-grid">
          <MetricCard label="Дата" value={result?.as_of ?? "—"} helpId="investment_decision" />
          <MetricCard
            label="Capital"
            value={result?.capital ? `${Number(result.capital).toFixed(0)} ₽` : "100000 ₽"}
            helpId="investment_decision"
          />
          <MetricCard
            label="CBR hurdle"
            value={
              result?.cbr_hurdle_annual != null
                ? rate(result.cbr_hurdle_annual)
                : hurdle?.annual_rate == null
                  ? "Нет данных"
                  : rate(hurdle.annual_rate)
            }
            helpId="cbr_hurdle"
          />
          <MetricCard
            label="Market state"
            value={decision?.status ?? "—"}
            helpId="risk_budget"
          />
        </div>
      </div>

      <div className="card">
        <h3>Research input</h3>
        <div className="investment-calculator">
          <label>
            Risk profile{" "}
            <select value={profileId} onChange={(e) => setProfileId(e.target.value)}>
              <option value="CONSERVATIVE_ALLOCATION_V0">Conservative V0</option>
              <option value="BALANCED_ALLOCATION_V0">Balanced V0</option>
              <option value="GROWTH_ALLOCATION_V0">Growth V0</option>
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
            Рассчитать решение
          </button>
        </div>
        <p className="muted">
          Прогноз ≠ решение. Confidence не выдумывается. Высокая доходность облигации может отражать
          высокий риск.
        </p>
      </div>

      <div className="card-grid">
        <div className="card">
          <h3>Equity</h3>
          <p>
            Ожидаемая возможность: excess {rate(equity?.expected_excess_return)}
          </p>
          <p>
            Качество сигнала: calibration={equity?.calibration_status ?? "UNKNOWN"}, confidence=
            {equity?.confidence == null ? "UNKNOWN" : String(equity.confidence)}
          </p>
          <p className="muted">Риски: неизвестная калибровка, look-ahead запрещён, research-only.</p>
          <p className="muted">{decision?.why_equity_ru}</p>
        </div>
        <div className="card">
          <h3>Fixed Income</h3>
          <p>Доходность: {rate(fi?.expected_yield)} (source: {fi?.yield_source ?? "—"})</p>
          <p>
            Риски: credit={fi?.credit_quality ?? "—"}, duration={fi?.duration ?? "—"}, liquidity=
            {fi?.liquidity_status ?? fi?.liquidity ?? "—"}
          </p>
          <p>
            Качество данных: {fi?.data_quality ?? "—"} / support={fi?.support_status ?? "—"}
          </p>
          <p className="muted">{result?.bond_safety_reminder}</p>
          <p className="muted">{decision?.why_fixed_income_ru}</p>
        </div>
        <div className="card">
          <h3>Cash</h3>
          <p>Порог ключевой ставки: {rate(cash?.annual_rate ?? result?.cbr_hurdle_annual)}</p>
          <p className="muted">{decision?.why_cash_ru}</p>
        </div>
        <div className="card">
          <h3>Decision</h3>
          <p>
            Kraken рекомендует исследовательское распределение:
          </p>
          <ul className="plain-list">
            <li>Equity: {pct(decision?.equity_weight)}</li>
            <li>Fixed Income: {pct(decision?.fixed_income_weight)}</li>
            <li>Cash: {pct(decision?.cash_weight)}</li>
          </ul>
          {decision?.status ? <StatusBadge status={decision.status.toLowerCase()} /> : null}
        </div>
      </div>

      <div className="card">
        <h3>Почему так</h3>
        <ul className="plain-list">
          {(decision?.explanations ?? []).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        {(decision?.warnings ?? []).length > 0 ? (
          <>
            <h4>Warnings</h4>
            <ul className="plain-list">
              {decision!.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </>
        ) : null}
      </div>

      <div className="card">
        <h3>Equity calibration</h3>
        <div className="card-grid">
          <MetricCard label="Sample size" value={String(cal?.sample_size ?? 0)} helpId="calibration" />
          <MetricCard
            label="Bias"
            value={cal?.bias == null ? "—" : cal.bias.toFixed(4)}
            helpId="calibration"
          />
          <MetricCard
            label="Hit rate"
            value={cal?.hit_rate == null ? "—" : rate(cal.hit_rate)}
            helpId="calibration"
          />
          <MetricCard
            label="Status"
            value={cal?.calibration_status ?? "UNKNOWN"}
            helpId="opportunity_confidence"
          />
        </div>
        <p className="muted">{cal?.uncertainty_note}</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Bucket</th>
                <th>n</th>
                <th>Mean predicted</th>
                <th>Mean realized</th>
              </tr>
            </thead>
            <tbody>
              {(cal?.buckets ?? []).map((b) => (
                <tr key={b.name}>
                  <td>{b.name}</td>
                  <td>{b.n}</td>
                  <td>{b.mean_predicted == null ? "—" : rate(b.mean_predicted)}</td>
                  <td>{b.mean_realized == null ? "—" : rate(b.mean_realized)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>Economic metrics framing</h3>
        <p>
          <strong>{result?.economic_metrics.question_ru}</strong>
        </p>
        <p className="muted">{result?.economic_metrics.answer_ru}</p>
        <div className="card-grid">
          <MetricCard label="return" value="—" helpId="expected_excess_return" />
          <MetricCard label="excess_vs_cbr" value="—" helpId="expected_excess_return" />
          <MetricCard
            label="max_drawdown"
            value={
              result?.economic_metrics.max_drawdown == null
                ? "—"
                : rate(result.economic_metrics.max_drawdown)
            }
            helpId="risk_budget"
          />
          <MetricCard
            label="volatility"
            value={
              result?.economic_metrics.volatility == null
                ? "—"
                : rate(result.economic_metrics.volatility)
            }
            helpId="risk_budget"
          />
          <MetricCard label="turnover" value="—" helpId="allocation_reason" />
        </div>
      </div>

      <div className="card">
        <h3>Research Lab: сравнение</h3>
        <p className="muted">
          Equity only / Fixed Income only / Allocation Policy / CBR — без автовыбора победителя.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Источник</th>
                <th>Equity</th>
                <th>FI</th>
                <th>Cash</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {(compare?.profiles ?? []).map((row) => (
                <tr key={`p-${row.profile_id}`}>
                  <td>Risk profile: {row.profile_id}</td>
                  <td>{pct(row.decision.equity_weight)}</td>
                  <td>{pct(row.decision.fixed_income_weight)}</td>
                  <td>{pct(row.decision.cash_weight)}</td>
                  <td>
                    <StatusBadge status={row.decision.status.toLowerCase()} />
                  </td>
                </tr>
              ))}
              {(compare?.static_benchmarks ?? []).map((row) => (
                <tr key={`s-${row.policy.id}`}>
                  <td>
                    {row.policy.id.includes("EQUITY")
                      ? "Equity only"
                      : row.policy.id.includes("FIXED")
                        ? "Fixed Income only"
                        : row.policy.id.includes("CASH")
                          ? "Cash / CBR sleeve"
                          : `Allocation Policy: ${row.policy.title}`}
                  </td>
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
        <p className="muted">
          CBR benchmark:{" "}
          {compare?.cbr_benchmark?.annual_rate == null
            ? "—"
            : rate(compare.cbr_benchmark.annual_rate)}{" "}
          — {compare?.cbr_benchmark?.note}
        </p>
      </div>
    </div>
  );
}
