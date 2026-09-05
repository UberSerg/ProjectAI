import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import { assessPortfolioRisk, type PortfolioRiskResponse } from "../api/investment";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";

function pct(weight: number | undefined | null): string {
  if (weight == null) return "—";
  return `${(weight * 100).toFixed(1)}%`;
}

export function PortfolioRiskPage() {
  const [result, setResult] = useState<PortfolioRiskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [excessBps, setExcessBps] = useState(0);

  const run = () => {
    setError(null);
    setLoading(true);
    assessPortfolioRisk({
      capital: 100000,
      equity_expected_excess_return: excessBps / 10000,
      profile_id: "BALANCED_ALLOCATION_V0",
    })
      .then(setResult)
      .catch((reason: unknown) => setError(errorMessage(reason)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading && !result) {
    return <PageState kind="loading" title="Загрузка проверки риска портфеля…" />;
  }

  const risk = result?.risk_assessment;

  return (
    <div className="allocation-page">
      <PageHeader
        title="Проверка риска портфеля Kraken"
        description="Opportunity → Risk Checks → Eligibility → Portfolio Candidate. Доходность сама по себе не разрешает покупку."
        helpPageId="portfolio_risk"
      />
      {error ? <div className="banner banner-warning">{error}</div> : null}

      <div className="card">
        <h3>Research input 100 000 ₽</h3>
        <div className="investment-calculator">
          <label>
            Equity excess (bps){" "}
            <input
              type="number"
              value={excessBps}
              onChange={(e) => setExcessBps(Number(e.target.value))}
            />
          </label>
          <button type="button" onClick={run}>
            Проверить риск
          </button>
        </div>
        <p className="muted">
          Pipeline: {result?.pipeline}.{" "}
          <Link to="/investment-decision">Инвестиционное решение</Link> ·{" "}
          <Link to="/bonds">Облигации</Link>
        </p>
      </div>

      <div className="card-grid">
        <MetricCard
          label="Статус gate"
          value={risk?.status ?? "—"}
          helpId="portfolio_risk_gate"
        />
        <MetricCard
          label="Capital"
          value={result?.capital ? `${Number(result.capital).toFixed(0)} ₽` : "100000 ₽"}
          helpId="portfolio_risk_gate"
        />
        <MetricCard
          label="Equity"
          value={pct(result?.allocation.equity_weight)}
          helpId="equity_sleeve"
        />
        <MetricCard
          label="Fixed Income"
          value={pct(result?.allocation.fixed_income_weight)}
          helpId="fixed_income_sleeve"
        />
        <MetricCard label="Cash" value={pct(result?.allocation.cash_weight)} helpId="cash_sleeve" />
      </div>

      {risk ? (
        <>
          <div className="card">
            <h3>Итог</h3>
            <p>
              <StatusBadge status={risk.status.toLowerCase()} /> {risk.summary_ru}
            </p>
          </div>

          <div className="card-grid">
            <div className="card">
              <h3>Разрешено</h3>
              <p>{risk.approved.length ? risk.approved.join(", ") : "—"}</p>
            </div>
            <div className="card">
              <h3>С предупреждениями</h3>
              <p>
                {risk.approved_with_warnings.length
                  ? risk.approved_with_warnings.join(", ")
                  : "—"}
              </p>
            </div>
            <div className="card">
              <h3>Research only</h3>
              <p>{risk.research_only.length ? risk.research_only.join(", ") : "—"}</p>
            </div>
            <div className="card">
              <h3>Заблокировано</h3>
              <p>{risk.blocked.length ? risk.blocked.join(", ") : "—"}</p>
            </div>
          </div>

          <div className="card">
            <h3>Позиции и причины</h3>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Sleeve</th>
                    <th>Weight</th>
                    <th>Status</th>
                    <th>Причины</th>
                  </tr>
                </thead>
                <tbody>
                  {risk.positions.map((p) => (
                    <tr key={`${p.sleeve}-${p.symbol}`}>
                      <td>{p.symbol}</td>
                      <td>{p.sleeve}</td>
                      <td>{pct(p.target_weight)}</td>
                      <td>
                        <StatusBadge status={p.status.toLowerCase()} />
                      </td>
                      <td>
                        <ul className="plain-list">
                          {p.explanations_ru.map((line) => (
                            <li key={line}>{line}</li>
                          ))}
                          {p.warnings_ru.map((line) => (
                            <li key={line}>{line}</li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <h3>Предупреждения портфеля</h3>
            <ul className="plain-list">
              {(risk.warnings_ru.length ? risk.warnings_ru : ["Нет дополнительных предупреждений."]).map(
                (w) => (
                  <li key={w}>{w}</li>
                ),
              )}
            </ul>
            <p className="muted">{result?.note}</p>
          </div>
        </>
      ) : null}
    </div>
  );
}
