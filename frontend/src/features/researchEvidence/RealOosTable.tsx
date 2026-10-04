import type { AblationTable, CampaignOosTable } from "../../api/researchEvidence";
import { formatCi, formatCount } from "./format";
import { formatIcOrNoData, oosRows } from "./campaignFormat";
import { NO_DATA_LABEL } from "./constants";

export function RealOosTable({
  oos,
  ablation,
}: {
  oos?: CampaignOosTable | null;
  ablation?: AblationTable | null;
}) {
  const rows = oosRows(oos, ablation);
  const empty = !oos?.rows?.length && !ablation?.rows?.length;

  return (
    <div className="card" data-testid="campaign-oos">
      <h3>Исторический OOS (хронологический)</h3>
      <p className="field-hint">
        Rank IC, spread, n и CI по вариантам BASE / FUND / EVENTS / V4 FULL. Это не конкурс и не выбор
        чемпиона.
      </p>
      {empty ? <p className="muted">OOS-таблица ещё не заполнена — {NO_DATA_LABEL}.</p> : null}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Вариант</th>
              <th>Rank IC</th>
              <th>Spread</th>
              <th>n</th>
              <th>CI</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.variant} data-testid={`oos-row-${row.variant}`}>
                <td>{row.label}</td>
                <td>{formatIcOrNoData(row.rank_ic)}</td>
                <td>{formatIcOrNoData(row.spread)}</td>
                <td>{row.n == null ? NO_DATA_LABEL : formatCount(row.n)}</td>
                <td>
                  {row.ci_low == null && row.ci_high == null
                    ? NO_DATA_LABEL
                    : formatCi(row.ci_low, row.ci_high)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {oos?.notes ? <p className="muted">{oos.notes}</p> : null}
    </div>
  );
}
