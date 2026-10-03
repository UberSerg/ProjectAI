import { MetricCard } from "../../components/Ui";
import type { CampaignIdentity } from "../../api/researchEvidence";
import { CANONICAL_CAMPAIGN_VERSION } from "../../api/researchEvidence";
import { campaignWindow, fingerprintShort } from "./campaignFormat";
import { NO_DATA_LABEL } from "./constants";

export function CampaignIdentityCard({ identity }: { identity?: CampaignIdentity | null }) {
  const version = identity?.campaign_version ?? CANONICAL_CAMPAIGN_VERSION;
  const short = fingerprintShort(identity?.fingerprint, identity?.fingerprint_short);
  const snapshot = identity?.data_snapshot_hash
    ? fingerprintShort(identity.data_snapshot_hash)
    : NO_DATA_LABEL;

  return (
    <div className="card" data-testid="campaign-identity">
      <h3>Каноническое исследование</h3>
      <p className="field-hint">
        Замороженный контракт {CANONICAL_CAMPAIGN_VERSION}. Это исследование, не готовность к живой
        торговле.
      </p>
      <div className="metric-grid diagnostics-summary-grid">
        <MetricCard label="Версия кампании" value={version} />
        <MetricCard label="Fingerprint" value={short} />
        <MetricCard label="V3 run" value={identity?.v3_run_id != null ? String(identity.v3_run_id) : NO_DATA_LABEL} />
        <MetricCard label="V4 run" value={identity?.v4_run_id != null ? String(identity.v4_run_id) : NO_DATA_LABEL} />
        <MetricCard label="Окно" value={campaignWindow(identity?.date_from, identity?.date_to)} />
        <MetricCard label="Snapshot hash" value={snapshot} />
      </div>
      {identity?.data_snapshot_at ? (
        <p className="muted">Снимок данных: {identity.data_snapshot_at}</p>
      ) : null}
    </div>
  );
}
