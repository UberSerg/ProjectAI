import type { AblationTable as AblationTablePayload } from "../../api/researchEvidence";
import { ablationRows, formatCi, formatCount, formatIc } from "./format";

export function AblationTable({ ablation }: { ablation?: AblationTablePayload | null }) {
  const rows = ablationRows(ablation);
  const empty = !ablation?.rows?.length;

  return (
    <div className="card" data-testid="evidence-ablation">
      <h3>Вклад фундаментала / событий</h3>
      <p className="field-hint">
        Сравнение вариантов признаков на mean OOS IC. Это не конкурс и не выбор чемпиона.
      </p>
      {empty ? (
        <p className="muted">Таблица абляции ещё не заполнена.</p>
      ) : null}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Вариант</th>
              <th>Mean OOS IC</th>
              <th>Spread</th>
              <th>Bootstrap CI</th>
              <th>n</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.variant} data-testid={`ablation-row-${row.variant}`}>
                <td>{row.label}</td>
                <td>{formatIc(row.mean_oos_ic)}</td>
                <td>{formatIc(row.spread)}</td>
                <td>{formatCi(row.bootstrap_ci_low, row.bootstrap_ci_high)}</td>
                <td>{formatCount(row.n)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ablation?.notes ? <p className="muted">{ablation.notes}</p> : null}
    </div>
  );
}
