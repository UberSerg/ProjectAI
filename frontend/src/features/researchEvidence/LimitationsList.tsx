import type { EvidenceLimitation } from "../../api/researchEvidence";
import { mergeLimitations } from "./format";

export function LimitationsList({
  limitations,
}: {
  limitations?: Array<EvidenceLimitation | string> | null;
}) {
  const rows = mergeLimitations(limitations);
  return (
    <div className="card" data-testid="evidence-limitations">
      <h3>Ограничения данных</h3>
      <p className="field-hint">Этот список обязателен. Он не исчезает, даже если API вернул пустой массив.</p>
      <ul className="plain-list">
        {rows.map((row) => (
          <li key={row.code ?? row.title ?? ""} data-testid={`limitation-${row.code}`}>
            <strong>{row.title}</strong>
            {row.detail ? <span className="muted"> — {row.detail}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
