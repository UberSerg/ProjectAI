import { useMemo, useState } from "react";
import { MetricHelp } from "../../help";
import { formatPercent, formatPercentPoints } from "../../utils/format";
import {
  HURDLE_PRESETS,
  clampHurdleRate,
  economicConclusion,
  excessCagrVsCash,
  excessVsCashHurdle,
} from "./cashHurdle";

type Props = {
  /** Total price return over the run window (fraction). */
  totalReturn?: number | null;
  /** Optional CAGR if available (fraction). Prefer for annualised display. */
  cagr?: number | null;
  maxDrawdown?: number | null;
  dateFrom?: string | null;
  dateTo?: string | null;
  /** Controlled hurdle rate (0–0.30). If omitted, uses local state starting at 0.10. */
  annualRate?: number;
  onAnnualRateChange?: (rate: number) => void;
  testId?: string;
};

/**
 * Post-processing only: compares historical strategy result to a fixed cash hurdle.
 * Must never imply that changing the rate re-runs or mutates the simulation.
 */
export function EconomicViabilityBlock({
  totalReturn,
  cagr,
  maxDrawdown,
  dateFrom,
  dateTo,
  annualRate: controlledRate,
  onAnnualRateChange,
  testId = "economic-viability",
}: Props) {
  const [localRate, setLocalRate] = useState(0.1);
  const annualRate = controlledRate ?? localRate;
  const setRate = (rate: number) => {
    const next = clampHurdleRate(rate);
    if (onAnnualRateChange) onAnnualRateChange(next);
    else setLocalRate(next);
  };

  const { hurdleReturn, excessPeriod } = useMemo(() => {
    const { hurdleReturn: h, excess } = excessVsCashHurdle(
      totalReturn,
      dateFrom,
      dateTo,
      annualRate,
    );
    return { hurdleReturn: h, excessPeriod: excess };
  }, [totalReturn, dateFrom, dateTo, annualRate]);

  const excessAnnual = excessCagrVsCash(cagr, annualRate);
  const displayStrategy = cagr != null ? cagr : totalReturn;
  const strategyLabel = cagr != null ? "Стратегия (годовая)" : "Стратегия (за период)";
  const excess = excessAnnual ?? excessPeriod;
  const conclusion = economicConclusion(excess);

  return (
    <div className="card" data-testid={testId}>
      <h3>
        Стоил ли риск результата? <MetricHelp metricId="economic_viability" />
      </h3>
      <p className="field-hint">
        Сравнение с условной денежной альтернативой — только пост-обработка отчёта. Выбор ставки не
        меняет симуляцию, config hash и сохранённый результат.{" "}
        <MetricHelp metricId="cash_hurdle" />
      </p>

      <div className="chip-row" role="group" aria-label="Денежная альтернатива">
        {HURDLE_PRESETS.map((p) => (
          <button
            key={p.rate}
            type="button"
            className={Math.abs(annualRate - p.rate) < 1e-9 ? "primary" : "secondary"}
            onClick={() => setRate(p.rate)}
          >
            {p.label}
          </button>
        ))}
        <label className="hurdle-custom">
          Своя ставка, % годовых (0–30)
          <input
            type="number"
            min={0}
            max={30}
            step={0.5}
            value={Number((annualRate * 100).toFixed(2))}
            onChange={(e) => setRate(Number(e.target.value) / 100)}
            aria-label="Ставка денежной альтернативы в процентах годовых"
          />
        </label>
      </div>

      <div className="summary-box" data-testid={`${testId}-numbers`}>
        <div>
          {strategyLabel}: {formatPercent(displayStrategy)}
        </div>
        <div>
          Денежная альтернатива: {formatPercent(annualRate)} годовых{" "}
          <MetricHelp metricId="cash_hurdle" />
        </div>
        {hurdleReturn != null ? (
          <div>
            Эквивалент за период: {formatPercent(hurdleReturn)}{" "}
            <MetricHelp metricId="rate_based_cash_proxy" />
          </div>
        ) : null}
        <div>
          Разница vs денежная альтернатива: {formatPercentPoints(excess)}{" "}
          <MetricHelp metricId="excess_vs_cash" />
        </div>
        <div>
          Максимальная просадка: {formatPercent(maxDrawdown)}{" "}
          <MetricHelp metricId="sim_max_drawdown" />
        </div>
      </div>

      <p className="field-hint" data-testid={`${testId}-conclusion`}>
        {conclusion}
      </p>
    </div>
  );
}
