import { EmptyState, MetricCard } from "../../components/Ui";
import type { ProspectiveSummary } from "../../api/researchEvidence";
import { PROSPECTIVE_DIVIDER } from "./constants";
import { formatCount, formatIc, isProspectiveEmpty } from "./format";

export function ProspectiveSection({ prospective }: { prospective?: ProspectiveSummary | null }) {
  const empty = isProspectiveEmpty(prospective);

  return (
    <section className="research-evidence-prospective" data-testid="evidence-prospective">
      <div className="research-evidence-prospective-divider" data-testid="evidence-prospective-divider">
        <strong>{PROSPECTIVE_DIVIDER}</strong>
        <p>
          Эти наблюдения идут только вперёд и не смешиваются с историческим OOS. Не читайте их как
          подтверждение исторических метрик.
        </p>
      </div>
      {empty ? (
        <EmptyState
          title="Проспективных наблюдений пока нет"
          reason="Когда появятся новые даты после фиксации эксперимента, они отобразятся только в этом блоке."
        />
      ) : (
        <div className="card">
          <div className="metric-grid diagnostics-summary-grid">
            <MetricCard label="Наблюдений" value={formatCount(prospective?.n_observations)} />
            <MetricCard label="Rank IC (prospective)" value={formatIc(prospective?.rank_ic)} />
            <MetricCard label="Статус" value={prospective?.status ?? "—"} />
          </div>
          {prospective?.observations?.length ? (
            <div className="table-wrap">
              <table data-testid="evidence-prospective-observations">
                <thead>
                  <tr>
                    <th>Дата</th>
                    <th>n</th>
                    <th>Rank IC</th>
                    <th>Заметка</th>
                  </tr>
                </thead>
                <tbody>
                  {prospective.observations.map((row, idx) => (
                    <tr key={`${row.as_of ?? idx}`}>
                      <td>{row.as_of ?? "—"}</td>
                      <td>{formatCount(row.n)}</td>
                      <td>{formatIc(row.rank_ic)}</td>
                      <td>{row.notes ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {prospective?.notes ? <p className="muted">{prospective.notes}</p> : null}
        </div>
      )}
    </section>
  );
}
