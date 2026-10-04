import type { EvidenceCampaignSummary } from "../../api/researchEvidence";
import { campaignWindow, fingerprintShort } from "./campaignFormat";
import { NO_DATA_LABEL } from "./constants";

export function CampaignHistoryList({
  campaigns,
  selected,
  onSelect,
}: {
  campaigns: EvidenceCampaignSummary[];
  selected?: string | null;
  onSelect: (fingerprint: string) => void;
}) {
  return (
    <div className="card" data-testid="campaign-history">
      <h3>Досье кампаний</h3>
      <p className="field-hint">Новые сверху. Выбор загружает неизменяемый агрегат, не строки предсказаний.</p>
      {!campaigns.length ? (
        <p className="muted">Канонических досье пока нет.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Fingerprint</th>
                <th>Окно</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((row) => (
                <tr
                  key={row.fingerprint}
                  data-testid={`campaign-row-${row.fingerprint}`}
                  className={selected === row.fingerprint ? "is-selected" : undefined}
                >
                  <td>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => onSelect(row.fingerprint)}
                    >
                      {fingerprintShort(row.fingerprint, row.fingerprint_short)}
                    </button>
                  </td>
                  <td>{campaignWindow(row.date_from, row.date_to)}</td>
                  <td>{row.status ?? NO_DATA_LABEL}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
