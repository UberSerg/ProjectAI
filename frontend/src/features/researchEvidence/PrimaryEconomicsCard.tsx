import { MetricCard } from "../../components/Ui";
import { formatPercent } from "../../utils/format";
import type { PrimaryResearchContract } from "../../api/researchEvidence";
import { formatMetricOrNoData } from "./campaignFormat";
import { ECONOMICS_DISCLAIMER, PRIMARY_CONTRACT_LABEL } from "./constants";
import { formatCount, formatTurnover } from "./format";

export function PrimaryEconomicsCard({
  contract,
}: {
  contract?: PrimaryResearchContract | null;
}) {
  const rebalance = contract?.rebalance_sessions ?? 20;
  const top = contract?.selection_top_pct ?? 20;
  const bps = contract?.cost_bps_per_side ?? 30;
  const returnKind = contract?.return_kind ?? "PRICE_RETURN";

  return (
    <div className="card primary-research-contract" data-testid="campaign-primary-economics">
      <h3>{PRIMARY_CONTRACT_LABEL}</h3>
      <p className="field-hint" data-testid="primary-contract-spec">
        {rebalance} sessions · top {top}% · {bps} bps/side assumed · {returnKind}. {ECONOMICS_DISCLAIMER}.
        30 bps — исследовательское допущение, не тариф брокера.
      </p>
      <div className="metric-grid diagnostics-summary-grid">
        <MetricCard
          label="Cumulative PRICE_RETURN"
          value={formatMetricOrNoData(contract?.cumulative_price_return, (v) => formatPercent(v))}
        />
        <MetricCard
          label="Benchmark"
          value={formatMetricOrNoData(contract?.benchmark_return, (v) => formatPercent(v))}
        />
        <MetricCard
          label="Max drawdown"
          value={formatMetricOrNoData(contract?.max_drawdown, (v) => formatPercent(v))}
        />
        <MetricCard
          label="Turnover"
          value={formatMetricOrNoData(contract?.turnover, (v) => formatTurnover(v))}
        />
        <MetricCard
          label="Cash"
          value={formatMetricOrNoData(contract?.average_cash_weight, (v) => formatPercent(v))}
        />
        <MetricCard
          label="Unresolved exits"
          value={formatMetricOrNoData(contract?.unresolved_exits, (v) => formatCount(v))}
        />
      </div>
      {contract?.notes ? <p className="muted">{contract.notes}</p> : null}
    </div>
  );
}
