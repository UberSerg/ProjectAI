import { useState } from "react";
import { labels } from "../../utils/labels";

interface Props {
  open: boolean;
  onClose: () => void;
  onSubmit: (dateFrom: string, dateTo: string) => void;
  busy?: boolean;
}

export function TechnicalBackfillModal({ open, onClose, onSubmit, busy }: Props) {
  const [dateFrom, setDateFrom] = useState("2024-01-01");
  const [dateTo, setDateTo] = useState("");

  if (!open) return null;

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onMouseDown={(e) => e.stopPropagation()}>
        <h2>{labels.actions.backfillTechnical}</h2>
        <p className="muted">Пересчёт технических признаков и сигналов rules_v1 для активного universe.</p>
        <label className="field">
          <span>Дата начала</span>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label className="field">
          <span>Дата окончания (необязательно)</span>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
        <div className="button-row">
          <button type="button" disabled={busy || !dateFrom} onClick={() => onSubmit(dateFrom, dateTo)}>
            {labels.actions.start}
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={onClose}>
            {labels.actions.cancel}
          </button>
        </div>
      </div>
    </div>
  );
}
