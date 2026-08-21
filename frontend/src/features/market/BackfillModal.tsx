import { type FormEvent, useState } from "react";
import { labels } from "../../utils/labels";

export function BackfillModal({
  busy,
  onClose,
  onSubmit,
}: {
  busy: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    symbols?: string[];
    date_from?: string;
    date_to?: string;
    default_universe: boolean;
  }) => void;
}) {
  const [universe, setUniverse] = useState(true);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const symbols = String(form.get("instruments") ?? "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    onSubmit({
      symbols: universe || !symbols.length ? undefined : symbols,
      date_from: String(form.get("date_from") ?? "") || undefined,
      date_to: String(form.get("date_to") ?? "") || undefined,
      default_universe: universe || symbols.length === 0,
    });
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="backfill-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <h2 id="backfill-title">{labels.actions.backfill}</h2>
        <p className="subtitle">Загрузка полной истории может занять некоторое время.</p>
        <form onSubmit={handleSubmit}>
          <label className="check-row">
            <input type="checkbox" checked={universe} onChange={(e) => setUniverse(e.target.checked)} />
            Вся текущая выборка инструментов
          </label>
          <label>
            Инструменты
            <input name="instruments" disabled={universe} placeholder="SBER, LKOH, IMOEX" />
          </label>
          <div className="form-row">
            <label>
              Дата с
              <input name="date_from" type="date" defaultValue="2024-01-01" />
            </label>
            <label>
              Дата по
              <input name="date_to" type="date" />
            </label>
          </div>
          <div className="button-row">
            <button type="submit" disabled={busy}>
              {labels.actions.start}
            </button>
            <button type="button" className="secondary" onClick={onClose}>
              {labels.actions.cancel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
