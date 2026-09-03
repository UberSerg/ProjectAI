import { getMetricHelp } from "./registry";
import { useHelpOptional } from "./HelpContext";
import { HelpTooltip } from "./HelpTooltip";

/** Inline ⓘ — tooltip on hover/focus; click opens expanded drawer. */
export function MetricHelp({ metricId, label }: { metricId: string; label?: string }) {
  const entry = getMetricHelp(metricId);
  const help = useHelpOptional();
  if (!entry || !help) return null;

  return (
    <span className="metric-help">
      {label ? <span className="metric-help-label">{label}</span> : null}
      <HelpTooltip summary={entry.summary} onExpand={() => help.openMetric(metricId)}>
        <span aria-hidden>i</span>
      </HelpTooltip>
    </span>
  );
}
