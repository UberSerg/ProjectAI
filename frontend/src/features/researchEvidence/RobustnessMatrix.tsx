import { useState } from "react";
import { formatPercent } from "../../utils/format";
import type { EconomicsRobustness } from "../../api/researchEvidence";
import { isPrimaryRobustnessCell, robustnessAxes, robustnessCellAt } from "./campaignFormat";
import { NO_DATA_LABEL, PRIMARY_COST_BPS, ROBUSTNESS_COST_BPS } from "./constants";

export function RobustnessMatrix({ matrix }: { matrix?: EconomicsRobustness | null }) {
  const [cost, setCost] = useState<number>(PRIMARY_COST_BPS);
  const axes = robustnessAxes(matrix);

  return (
    <div className="card" data-testid="campaign-robustness">
      <h3>Матрица устойчивости (издержки)</h3>
      <p className="field-hint">
        Предзаявленная сетка rebalance × selection. Переключатель стоимости не меняет PRIMARY RESEARCH
        CONTRACT (30 bps). Максимальная доходность не подсвечивается.
      </p>
      <div className="page-actions" data-testid="robustness-cost-switch">
        {ROBUSTNESS_COST_BPS.map((bps) => (
          <button
            key={bps}
            type="button"
            className={bps === cost ? "primary" : "secondary"}
            data-testid={`robustness-cost-${bps}`}
            aria-pressed={bps === cost}
            onClick={() => setCost(bps)}
          >
            {bps} bps
          </button>
        ))}
      </div>
      <div className="table-wrap">
        <table data-testid="robustness-grid">
          <thead>
            <tr>
              <th>Rebalance \ Top</th>
              {axes.selection.map((sel) => (
                <th key={sel}>top {sel}%</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {axes.rebalance.map((reb) => (
              <tr key={reb}>
                <th>{reb} sess</th>
                {axes.selection.map((sel) => {
                  const cell = robustnessCellAt(matrix, reb, sel, cost);
                  const primary = isPrimaryRobustnessCell({
                    rebalance_sessions: reb,
                    selection_top_pct: sel,
                    cost_bps: cost,
                  });
                  return (
                    <td
                      key={sel}
                      data-testid={`robustness-cell-${reb}-${sel}-${cost}`}
                      className={primary ? "robustness-cell-primary" : undefined}
                      data-primary={primary ? "true" : "false"}
                      data-max-highlight="false"
                    >
                      {cell?.total_return == null ? NO_DATA_LABEL : formatPercent(cell.total_return)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {matrix?.notes ? <p className="muted">{matrix.notes}</p> : null}
    </div>
  );
}
