import { EmptyState, MetricCard } from "../../components/Ui";
import type {
  ProspectiveForward,
  ProspectiveHorizonRow,
  ProspectivePdm,
  ProspectiveSummary,
} from "../../api/researchEvidence";
import { PROSPECTIVE_DIVIDER } from "./constants";
import { formatCount, isProspectiveEmpty } from "./format";

const HORIZON_ORDER = [5, 20, 60];

function horizonStatus(row?: ProspectiveHorizonRow | null): string {
  return row?.price_return?.status ?? row?.status ?? "—";
}

function PdmBlock({ pdm }: { pdm?: ProspectivePdm | null }) {
  const horizons = pdm?.horizons ?? [];
  const byHorizon = new Map(horizons.map((row) => [Number(row.horizon_sessions), row]));
  const links = pdm?.confirmed_operation_links;
  return (
    <div className="card" data-testid="evidence-pdm">
      <h3>Personal Decision Memory</h3>
      <div className="metric-grid diagnostics-summary-grid">
        <MetricCard label="Захватов (captures)" value={formatCount(pdm?.captures_total)} />
        <MetricCard label="Тип доходности" value={pdm?.return_type ?? "PRICE_RETURN"} />
      </div>
      <p className="field-hint">
        Captures показывают, сколько рекомендаций зафиксировано. Они не заменяют matured-выборку и не
        считаются достаточным доказательством.
      </p>
      <div className="table-wrap">
        <table data-testid="evidence-pdm-horizons">
          <thead>
            <tr>
              <th>Горизонт</th>
              <th>Matured</th>
              <th>Pending</th>
              <th>Unavailable</th>
              <th>Статус return</th>
              <th>Alignment</th>
            </tr>
          </thead>
          <tbody>
            {HORIZON_ORDER.map((horizon) => {
              const row = byHorizon.get(horizon);
              const align = row?.direction_alignment;
              return (
                <tr key={horizon} data-testid={`evidence-pdm-horizon-${horizon}`}>
                  <td>{horizon}d</td>
                  <td>{formatCount(row?.matured_count)}</td>
                  <td>{formatCount(row?.pending_count)}</td>
                  <td>{formatCount(row?.unavailable_count)}</td>
                  <td>{horizonStatus(row)}</td>
                  <td>
                    {align?.status
                      ? `${align.status}${align.alignment_rate != null ? ` (${align.alignment_rate})` : ""}`
                      : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {links ? (
        <p className="muted" data-testid="evidence-pdm-links">
          Подтверждённые связи с PersonalOperation: {formatCount(links.count)} — только метаданные, не
          причинность.
        </p>
      ) : null}
    </div>
  );
}

function metricEntries(block: Record<string, unknown> | null | undefined, allowError: boolean) {
  if (!block) return [];
  const out: Array<[string, string]> = [];
  for (const [key, value] of Object.entries(block)) {
    if (value == null || typeof value === "object") continue;
    const lower = key.toLowerCase();
    if (!allowError && (lower === "rmse" || lower === "mae")) continue;
    out.push([key, String(value)]);
  }
  return out;
}

function ForwardBlock({ forward }: { forward?: ProspectiveForward | null }) {
  const expected = forward?.expected_return;
  const ranking = forward?.ranking_score;
  const freshness = forward?.freshness;
  const latest = forward?.latest_batch;
  const evaluated = forward?.latest_evaluated_batch;
  return (
    <div className="card" data-testid="evidence-forward">
      <h3>Forward Predictions</h3>
      <div className="metric-grid diagnostics-summary-grid">
        <MetricCard label="Последний batch" value={latest?.batch_id != null ? String(latest.batch_id) : "—"} />
        <MetricCard
          label="Последний evaluated"
          value={evaluated?.batch_id != null ? String(evaluated.batch_id) : "—"}
        />
        <MetricCard label="Matured" value={formatCount(freshness?.matured_count)} />
        <MetricCard label="Pending" value={formatCount(freshness?.pending_count)} />
      </div>
      {expected ? (
        <div data-testid="evidence-forward-expected">
          <h4>EXPECTED_RETURN</h4>
          <p className="muted">
            status={expected.status ?? "—"}
            {expected.mae != null ? ` MAE=${expected.mae}` : ""}
            {expected.rmse != null ? ` RMSE=${expected.rmse}` : ""}
          </p>
        </div>
      ) : null}
      {ranking ? (
        <div data-testid="evidence-forward-ranking">
          <h4>RANKING_SCORE</h4>
          <p className="muted">
            {metricEntries(ranking as Record<string, unknown>, false)
              .map(([key, value]) => `${key}=${value}`)
              .join(" · ") || "метрики без RMSE/MAE"}
          </p>
        </div>
      ) : null}
    </div>
  );
}

export function ProspectiveSection({ prospective }: { prospective?: ProspectiveSummary | null }) {
  const empty = isProspectiveEmpty(prospective);
  const pdm = prospective?.personal_decision_memory;
  const forward = prospective?.forward_predictions;

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
        <>
          <PdmBlock pdm={pdm} />
          <ForwardBlock forward={forward} />
          {prospective?.notes ? <p className="muted">{prospective.notes}</p> : null}
        </>
      )}
    </section>
  );
}
