import { formatPercent } from "../../utils/format";
import type { EconomicsSummary } from "../../api/researchEvidence";
import { ECONOMICS_DISCLAIMER } from "./constants";
import { economicsScenarios, formatTurnover } from "./format";

export function EconomicsSection({ economics }: { economics?: EconomicsSummary | null }) {
  const rows = economicsScenarios(economics);
  const returnKind = economics?.return_kind ?? "PRICE_RETURN";
  const dividends = economics?.dividends ?? "excluded";
  const benchmark = economics?.benchmark ?? "—";

  return (
    <div className="card" data-testid="evidence-economics">
      <h3>Экономическая симуляция</h3>
      <p className="field-hint" data-testid="evidence-economics-disclaimer">
        {ECONOMICS_DISCLAIMER}. Ряд: {returnKind}, дивиденды: {dividends}.
      </p>
      <p className="muted">Benchmark: {benchmark}</p>
      {!economics?.scenarios?.length ? (
        <p className="muted">Сценарии издержек ещё не рассчитаны.</p>
      ) : null}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Сценарий</th>
              <th>Доходность</th>
              <th>CAGR</th>
              <th>vs benchmark</th>
              <th>MDD</th>
              <th>Turnover</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={String(row.id)} data-testid={`economics-row-${row.id}`}>
                <td>{row.label}</td>
                <td>{formatPercent(row.total_return)}</td>
                <td>{formatPercent(row.cagr)}</td>
                <td>{formatPercent(row.excess_vs_benchmark)}</td>
                <td>{formatPercent(row.max_drawdown)}</td>
                <td>{formatTurnover(row.turnover_ratio)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {economics?.notes ? <p className="muted">{economics.notes}</p> : null}
    </div>
  );
}
