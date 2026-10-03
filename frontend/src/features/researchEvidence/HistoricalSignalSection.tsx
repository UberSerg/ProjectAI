import { MetricCard } from "../../components/Ui";
import type { FoldYearRow, HistoricalModelSignal } from "../../api/researchEvidence";
import { formatBoolRu, formatCount, formatIc } from "./format";

function FoldTable({ rows, testId }: { rows?: FoldYearRow[] | null; testId: string }) {
  if (!rows?.length) {
    return <p className="muted">Согласованность по фолдам/годам пока не пришла.</p>;
  }
  return (
    <div className="table-wrap">
      <table data-testid={testId}>
        <thead>
          <tr>
            <th>Fold / год</th>
            <th>Rank IC</th>
            <th>Spread</th>
            <th>n</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={`${row.fold ?? row.year ?? idx}`}>
              <td>{row.fold ?? row.year ?? "—"}</td>
              <td>{formatIc(row.rank_ic)}</td>
              <td>{formatIc(row.spread)}</td>
              <td>{formatCount(row.n)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ModelBlock({
  title,
  signal,
  testId,
}: {
  title: string;
  signal?: HistoricalModelSignal | null;
  testId: string;
}) {
  const empty =
    !signal ||
    (signal.rank_ic == null && signal.spread == null && signal.n == null && !signal.fold_year?.length);

  return (
    <div className="card" data-testid={testId}>
      <h3>{title}</h3>
      {empty ? (
        <p className="muted">Исторический OOS-сигнал для этой модели ещё не собран.</p>
      ) : (
        <>
          <div className="metric-grid diagnostics-summary-grid">
            <MetricCard label="Rank IC" value={formatIc(signal.rank_ic)} />
            <MetricCard label="Spread" value={formatIc(signal.spread)} />
            <MetricCard label="n" value={formatCount(signal.n)} />
            <MetricCard
              label="Согласованность fold/year"
              value={formatBoolRu(signal.consistent, "устойчива", "не подтверждена")}
            />
          </div>
          <FoldTable rows={signal.fold_year} testId={`${testId}-folds`} />
          {signal.notes ? <p className="muted">{signal.notes}</p> : null}
        </>
      )}
    </div>
  );
}

export function HistoricalSignalSection({
  regression,
  ranker,
}: {
  regression?: HistoricalModelSignal | null;
  ranker?: HistoricalModelSignal | null;
}) {
  return (
    <div className="diagnostics-two-col" data-testid="evidence-historical-oos">
      <ModelBlock title="Regression" signal={regression} testId="evidence-regression" />
      <ModelBlock title="Ranker" signal={ranker} testId="evidence-ranker" />
    </div>
  );
}
