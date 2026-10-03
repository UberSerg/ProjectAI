import { MetricCard } from "../../components/Ui";
import type { EvidenceDataset } from "../../api/researchEvidence";
import {
  formatBoolRu,
  formatCount,
  formatShare,
  totalReturnStatusLabel,
} from "./format";

export function DatasetCard({ dataset }: { dataset?: EvidenceDataset | null }) {
  if (!dataset) {
    return (
      <div className="card" data-testid="evidence-dataset-empty">
        <p className="muted">Карточка датасета пока недоступна — доказательства частичные или ещё не собраны.</p>
      </div>
    );
  }

  const labels = dataset.labels?.length ? dataset.labels.join(", ") : "—";

  return (
    <div className="card" data-testid="evidence-dataset-card">
      <h3>Dataset V3 → V4</h3>
      {dataset.universe_label ? <p className="muted">{dataset.universe_label}</p> : null}
      <div className="metric-grid diagnostics-summary-grid">
        <MetricCard label="Universe V3" value={formatCount(dataset.universe_v3)} />
        <MetricCard label="Universe V4" value={formatCount(dataset.universe_v4)} />
        <MetricCard label="Признаки V3" value={formatCount(dataset.feature_count_v3)} />
        <MetricCard label="Признаки V4" value={formatCount(dataset.feature_count_v4)} />
        <MetricCard
          label="Sample identity"
          value={formatBoolRu(dataset.sample_identity_match, "совпадает", "не совпадает")}
        />
        <MetricCard label="PIT-нарушения" value={formatCount(dataset.pit_violations)} />
        <MetricCard label="Покрытие фундаментала" value={formatShare(dataset.fund_coverage)} />
        <MetricCard label="Покрытие событий" value={formatShare(dataset.event_coverage)} />
        <MetricCard label="Доля CURRENT_ONLY" value={formatShare(dataset.current_only_share)} />
        <MetricCard label="Bank/FI без поддержки" value={formatCount(dataset.bank_fi_unsupported)} />
        <MetricCard label="Total Return" value={totalReturnStatusLabel(dataset.total_return_status)} />
      </div>
      <p className="field-hint" data-testid="evidence-dataset-labels">
        Labels: {labels}
      </p>
      {dataset.notes ? <p className="muted">{dataset.notes}</p> : null}
    </div>
  );
}
