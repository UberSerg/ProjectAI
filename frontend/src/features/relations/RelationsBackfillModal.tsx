import { useState } from "react";
import { labels } from "../../utils/labels";

interface Props {
  open: boolean;
  busy?: boolean;
  onClose: () => void;
  onSubmit: (asOfFrom: string, asOfTo: string, cadence: string) => void;
}

export function RelationsBackfillModal({ open, busy, onClose, onSubmit }: Props) {
  const [asOfFrom, setAsOfFrom] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 120);
    return d.toISOString().slice(0, 10);
  });
  const [asOfTo, setAsOfTo] = useState("");
  const [cadence, setCadence] = useState("WEEKLY");

  if (!open) return null;

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-labelledby="relations-backfill-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="relations-backfill-title">Backfill связей</h2>
        <p className="muted">
          Исторические snapshots по as_of (по умолчанию WEEKLY за ~90–120 дней). Не путать с
          многолетним daily.
        </p>
        <label>
          as_of_from
          <input type="date" value={asOfFrom} onChange={(e) => setAsOfFrom(e.target.value)} />
        </label>
        <label>
          as_of_to (пусто = latest)
          <input type="date" value={asOfTo} onChange={(e) => setAsOfTo(e.target.value)} />
        </label>
        <label>
          cadence
          <select value={cadence} onChange={(e) => setCadence(e.target.value)}>
            <option value="WEEKLY">WEEKLY</option>
            <option value="DAILY">DAILY</option>
          </select>
        </label>
        <div className="modal-actions">
          <button type="button" className="secondary" disabled={busy} onClick={onClose}>
            {labels.actions.cancel}
          </button>
          <button
            type="button"
            disabled={busy || !asOfFrom}
            onClick={() => onSubmit(asOfFrom, asOfTo, cadence)}
          >
            {labels.actions.start}
          </button>
        </div>
      </div>
    </div>
  );
}
