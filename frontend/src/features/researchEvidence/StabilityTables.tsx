import type { CampaignStability, EvidenceStability, StabilitySliceRow } from "../../api/researchEvidence";
import { formatCount } from "./format";
import { formatIcOrNoData, sliceLabel, stabilityRows } from "./campaignFormat";
import { NO_DATA_LABEL } from "./constants";

function CompactTable({
  title,
  testId,
  rows,
}: {
  title: string;
  testId: string;
  rows: StabilitySliceRow[];
}) {
  return (
    <div className="card" data-testid={testId}>
      <h4>{title}</h4>
      {!rows.length ? (
        <p className="muted">{NO_DATA_LABEL}</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Срез</th>
                <th>Rank IC</th>
                <th>Spread</th>
                <th>n</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => (
                <tr key={`${sliceLabel(row)}-${idx}`}>
                  <td>{sliceLabel(row)}</td>
                  <td>{formatIcOrNoData(row.rank_ic)}</td>
                  <td>{formatIcOrNoData(row.spread)}</td>
                  <td>{row.n == null ? NO_DATA_LABEL : formatCount(row.n)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function StabilityTables({
  stability,
}: {
  stability?: CampaignStability | EvidenceStability | null;
}) {
  return (
    <div className="diagnostics-two-col" data-testid="campaign-stability">
      <CompactTable title="Годы" testId="stability-years" rows={stabilityRows(stability, "years")} />
      <CompactTable title="Фолды" testId="stability-folds" rows={stabilityRows(stability, "folds")} />
      <CompactTable
        title="DATED_WINDOW / CURRENT_ONLY"
        testId="stability-identity"
        rows={stabilityRows(stability, "identity_basis")}
      />
      <CompactTable
        title="Active / historical inactive"
        testId="stability-activity"
        rows={stabilityRows(stability, "activity")}
      />
    </div>
  );
}
