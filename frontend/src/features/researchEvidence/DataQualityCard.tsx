import { MetricCard } from "../../components/Ui";
import type { CampaignDataQuality } from "../../api/researchEvidence";
import { formatIssuerBasis, formatQualityValue } from "./campaignFormat";
import { NO_DATA_LABEL } from "./constants";

export function DataQualityCard({ quality }: { quality?: CampaignDataQuality | null }) {
  return (
    <div className="card" data-testid="campaign-data-quality">
      <h3>Качество исследовательских данных</h3>
      <p className="field-hint">
        Пропуски показываются как «{NO_DATA_LABEL}», а не как ноль покрытия. Отсутствие строк не значит
        «дивидендов не было».
      </p>
      <div className="metric-grid diagnostics-summary-grid">
        <div data-testid="data-quality-price">
          <MetricCard label="Покрытие цен" value={formatQualityValue(quality?.price_coverage, "share")} />
        </div>
        <div data-testid="data-quality-pit">
          <MetricCard label="PIT-статус" value={formatQualityValue(quality?.pit_status, "status")} />
        </div>
        <div data-testid="data-quality-fund">
          <MetricCard
            label="Покрытие фундаментала V4"
            value={formatQualityValue(quality?.v4_fundamental_coverage, "share")}
          />
        </div>
        <div data-testid="data-quality-events">
          <MetricCard label="Покрытие событий" value={formatQualityValue(quality?.event_coverage, "share")} />
        </div>
        <div data-testid="data-quality-issuer">
          <MetricCard label="Базис identity эмитента" value={formatIssuerBasis(quality?.issuer_identity_basis)} />
        </div>
        <div data-testid="data-quality-bank-fi">
          <MetricCard
            label="Bank/FI без поддержки"
            value={formatQualityValue(quality?.bank_fi_unsupported, "count")}
          />
        </div>
        <div data-testid="data-quality-total-return">
          <MetricCard
            label="Total Return"
            value={formatQualityValue(quality?.total_return_status, "status")}
          />
        </div>
      </div>
    </div>
  );
}
