import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  getDiagnosticsDisagreements,
  getDiagnosticsRegimes,
  getDiagnosticsStability,
  getDiagnosticsSummary,
  getDiagnosticsTopTail,
  getEconomicViability,
  pickModelCards,
  type DiagnosticsSummary,
  type DisagreementRow,
  type RegimeRow,
  type StabilityMetrics,
  type TopTailRow,
} from "../api/modelEdge";
import { MetricCard, PageHeader, PageState } from "../components/Ui";
import { EconomicViabilityBlock } from "../features/researchLab/EconomicViabilityBlock";
import { clampHurdleRate, parseHurdleParam } from "../features/researchLab/cashHurdle";
import { MetricHelp } from "../help";
import { formatPercent, formatPercentPoints } from "../utils/format";

function fmtIc(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return Number(value).toFixed(3);
}

function fmtRatio(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Number(value).toFixed(1)}×`;
}

function ModelSummaryPanel({
  title,
  card,
}: {
  title: string;
  card?: Record<string, unknown>;
}) {
  const c = card ?? {};
  const rankIc = (c.rank_ic as number | null | undefined) ?? null;
  const top20 =
    (c.top20_spread as number | null | undefined) ??
    (c.top20_realized as number | null | undefined) ??
    null;
  const stability =
    (c.stability as number | null | undefined) ??
    (c.rank_stability as number | null | undefined) ??
    null;
  const cagr = (c.cagr as number | null | undefined) ?? null;
  const maxDd = (c.max_drawdown as number | null | undefined) ?? null;
  const turnover = (c.turnover_ratio as number | null | undefined) ?? null;
  const excess = (c.excess_vs_cash as number | null | undefined) ?? null;

  return (
    <div className="card" data-testid={`summary-${title.toLowerCase()}`}>
      <h3>{title}</h3>
      <div className="metric-grid diagnostics-summary-grid">
        <MetricCard
          label="Качество ранжирования (Rank IC)"
          value={fmtIc(rankIc)}
          helpId="rank_ic"
        />
        <MetricCard
          label="Верх списка Top 20"
          value={formatPercent(top20)}
          helpId="top_tail_quality"
        />
        <MetricCard
          label="Стабильность рейтинга"
          value={fmtIc(stability)}
          helpId="rank_stability"
        />
        <MetricCard
          label="Годовая доходность портфеля"
          value={formatPercent(cagr)}
          helpId="sim_cagr"
        />
        <MetricCard
          label="Максимальная просадка"
          value={formatPercent(maxDd)}
          helpId="sim_max_drawdown"
        />
        <MetricCard label="Оборот" value={fmtRatio(turnover)} helpId="sim_turnover" />
        <MetricCard
          label="Разница vs денежная альтернатива"
          value={formatPercentPoints(excess)}
          helpId="excess_vs_cash"
        />
      </div>
    </div>
  );
}

function quantileLabel(row: TopTailRow): string {
  if (row.label) return String(row.label);
  const q = row.quantile;
  if (q == null) return "—";
  return `Top ${Math.round(Number(q) * 100)}%`;
}

export function ResearchDiagnosticsPage() {
  const [params, setParams] = useSearchParams();
  const hurdle = parseHurdleParam(params.get("hurdle"));

  const [summary, setSummary] = useState<DiagnosticsSummary | null>(null);
  const [topTail, setTopTail] = useState<TopTailRow[]>([]);
  const [stability, setStability] = useState<StabilityMetrics | null>(null);
  const [regimes, setRegimes] = useState<RegimeRow[]>([]);
  const [disagreeDates, setDisagreeDates] = useState<string[]>([]);
  const [asOf, setAsOf] = useState<string>("");
  const [disagreeRows, setDisagreeRows] = useState<DisagreementRow[]>([]);
  const [disagreeExample, setDisagreeExample] = useState<string | null>(null);
  const [onlyDiff, setOnlyDiff] = useState(true);
  const [econModels, setEconModels] = useState<Record<string, Record<string, unknown>>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const setHurdle = (rate: number) => {
    const next = clampHurdleRate(rate);
    const nextParams = new URLSearchParams(params);
    nextParams.set("hurdle", next.toFixed(2));
    setParams(nextParams, { replace: true });
  };

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    Promise.all([
      getDiagnosticsSummary(controller.signal),
      getDiagnosticsTopTail(controller.signal),
      getDiagnosticsStability(controller.signal),
      getDiagnosticsRegimes(controller.signal),
      getDiagnosticsDisagreements(undefined, controller.signal),
    ])
      .then(([sum, tt, st, rg, dg]) => {
        setSummary(sum);
        setTopTail(tt.rows ?? tt.items ?? []);
        setStability(st);
        setRegimes(rg.rows ?? rg.items ?? []);
        const dates = dg.dates ?? [];
        setDisagreeDates(dates);
        setDisagreeRows(dg.rows ?? dg.items ?? []);
        setDisagreeExample(dg.human_example ?? null);
        if (dg.as_of) setAsOf(dg.as_of);
        else if (dates.length) setAsOf(dates[dates.length - 1] ?? "");
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!asOf) return;
    const controller = new AbortController();
    getDiagnosticsDisagreements(asOf, controller.signal)
      .then((dg) => {
        setDisagreeRows(dg.rows ?? dg.items ?? []);
        setDisagreeExample(dg.human_example ?? null);
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      });
    return () => controller.abort();
  }, [asOf]);

  useEffect(() => {
    const controller = new AbortController();
    getEconomicViability(hurdle, controller.signal)
      .then((econ) => {
        setEconModels((econ.models as Record<string, Record<string, unknown>>) ?? {});
      })
      .catch(() => {
        /* economic endpoint may lag; page still usable via client hurdle block */
      });
    return () => controller.abort();
  }, [hurdle]);

  const { v0, v1 } = pickModelCards(summary);
  const conclusion =
    summary?.conclusion ??
    summary?.human_summary ??
    "Пока недостаточно данных для детерминированного вывода.";

  const learned =
    summary?.learned ??
    summary?.what_we_learned ??
    [
      "Качество общего ранжирования и качество верхней части списка — разные вопросы.",
      "Стабильность рейтинга влияет на оборот, но сама по себе не означает edge.",
      "Экономический смысл смотрится относительно выбранной денежной альтернативы.",
    ];

  const filteredDisagree = useMemo(() => {
    if (!onlyDiff) return disagreeRows;
    return disagreeRows.filter((r) => {
      if (r.v0_selected !== r.v1_selected) return true;
      const delta = r.rank_delta;
      return delta != null && Math.abs(Number(delta)) >= 5;
    });
  }, [disagreeRows, onlyDiff]);

  const stabV0 = (stability?.v0 ?? stability?.by_model?.v0 ?? stability) as StabilityMetrics | null;
  const stabV1 = (stability?.v1 ?? stability?.by_model?.v1 ?? null) as StabilityMetrics | null;

  const econV0 = econModels.v0 ?? econModels.V0;
  const displayCagr =
    (econV0?.cagr as number | undefined) ?? (v0?.cagr as number | undefined) ?? null;
  const displayReturn = (econV0?.total_price_return as number | undefined) ?? null;
  const displayDd =
    (econV0?.max_drawdown as number | undefined) ?? (v0?.max_drawdown as number | undefined) ?? null;

  if (error && !summary) return <PageState kind="error">{error}</PageState>;
  if (loading && !summary) {
    return <PageState kind="loading" title="Загрузка диагностики моделей…" />;
  }

  return (
    <section className="research-diagnostics">
      <PageHeader
        title="Почему модели дают такой результат?"
        description="Разбираем качество рейтинга, верхнюю часть списка, стабильность, решения стратегии и экономический результат."
        helpPageId="research_diagnostics"
        actions={
          <Link to="/research" className="secondary button-link">
            ← Лаборатория
          </Link>
        }
      />

      <div className="info-panel" data-testid="rank-ic-vs-portfolio">
        Стратегия покупает верхнюю часть рейтинга, поэтому хороший общий Rank IC не гарантирует
        хороший портфель. <MetricHelp metricId="portfolio_translation" />
      </div>

      <div className="diagnostics-two-col">
        <ModelSummaryPanel title="V0" card={v0} />
        <ModelSummaryPanel title="V1" card={v1} />
      </div>

      <div className="card" data-testid="main-conclusion">
        <h3>
          Главный вывод <MetricHelp metricId="model_quality" />
        </h3>
        <p>{conclusion}</p>
      </div>

      <div className="card" data-testid="top-tail-section">
        <h3>
          Качество верхней части рейтинга <MetricHelp metricId="top_tail_quality" />
        </h3>
        <p className="field-hint">
          Стратегия покупает не весь рейтинг, а только верхнюю его часть.{" "}
          <MetricHelp metricId="top_k_precision" /> <MetricHelp metricId="loser_contamination" />
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Квантиль</th>
                <th className="numeric">V0 факт. доходность</th>
                <th className="numeric">V1 факт. доходность</th>
                <th className="numeric">V0 попадания</th>
                <th className="numeric">V1 попадания</th>
                <th className="numeric">V0 «мусор» в топе</th>
                <th className="numeric">V1 «мусор» в топе</th>
              </tr>
            </thead>
            <tbody>
              {(topTail.length ? topTail : [{}, {}, {}, {}]).map((row, idx) => (
                <tr key={String(row.quantile ?? idx)}>
                  <td>{quantileLabel(row as TopTailRow)}</td>
                  <td className="numeric">{formatPercent(row.v0_realized_return as number | null)}</td>
                  <td className="numeric">{formatPercent(row.v1_realized_return as number | null)}</td>
                  <td className="numeric">{formatPercent(row.v0_hit_rate as number | null)}</td>
                  <td className="numeric">{formatPercent(row.v1_hit_rate as number | null)}</td>
                  <td className="numeric">
                    {formatPercent(row.v0_loser_contamination as number | null)}
                  </td>
                  <td className="numeric">
                    {formatPercent(row.v1_loser_contamination as number | null)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card" data-testid="stability-section">
        <h3>
          Стабильность рейтинга <MetricHelp metricId="rank_stability" />
        </h3>
        <p className="field-hint">
          Стабильный рейтинг может уменьшать лишние сделки, но стабильность сама по себе не означает
          качество. <MetricHelp metricId="rank_churn" />{" "}
          <MetricHelp metricId="rank_persistence" />
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Метрика</th>
                <th className="numeric">V0</th>
                <th className="numeric">V1</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ["Корреляция неделя к неделе", "week_to_week_correlation"],
                  ["Среднее смещение ранга", "avg_rank_movement"],
                  ["Удержание Top 20", "top20_persistence"],
                  ["Удержание Top 35", "top35_persistence"],
                  ["Входы (churn)", "entry_churn"],
                  ["Выходы (churn)", "exit_churn"],
                ] as const
              ).map(([label, key]) => (
                <tr key={key}>
                  <td>{label}</td>
                  <td className="numeric">{fmtIc(stabV0?.[key] as number | null | undefined)}</td>
                  <td className="numeric">{fmtIc(stabV1?.[key] as number | null | undefined)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card" data-testid="disagreement-section">
        <h3>
          Где модели расходятся <MetricHelp metricId="model_disagreement" />
        </h3>
        <p className="field-hint">
          Исторические факты по выбранной дате перебалансировки.{" "}
          <MetricHelp metricId="decision_attribution" />
        </p>
        <div className="form-row">
          <label>
            Дата
            <select
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              aria-label="Дата расхождений"
            >
              {!disagreeDates.length ? <option value="">Нет дат</option> : null}
              {disagreeDates.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
          <label className="radio-row">
            <input
              type="checkbox"
              checked={onlyDiff}
              onChange={(e) => setOnlyDiff(e.target.checked)}
            />
            Только расхождения
          </label>
        </div>
        {disagreeExample ? <p className="field-hint">{disagreeExample}</p> : null}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Тикер</th>
                <th className="numeric">Ранг V0</th>
                <th className="numeric">Ранг V1</th>
                <th className="numeric">Δ ранга</th>
                <th>V0 в портфеле</th>
                <th>V1 в портфеле</th>
                <th className="numeric">Факт 20д</th>
              </tr>
            </thead>
            <tbody>
              {!filteredDisagree.length ? (
                <tr>
                  <td colSpan={7}>Нет строк для выбранного фильтра.</td>
                </tr>
              ) : (
                filteredDisagree.slice(0, 80).map((r, idx) => (
                  <tr key={`${r.ticker ?? r.instrument_id ?? idx}`}>
                    <td>{r.ticker ?? r.instrument_id ?? "—"}</td>
                    <td className="numeric">{r.v0_rank ?? "—"}</td>
                    <td className="numeric">{r.v1_rank ?? "—"}</td>
                    <td className="numeric">{r.rank_delta ?? "—"}</td>
                    <td>{r.v0_selected ? "да" : "нет"}</td>
                    <td>{r.v1_selected ? "да" : "нет"}</td>
                    <td className="numeric">{formatPercent(r.realized_20d)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card" data-testid="regime-section">
        <h3>
          Режимы и годы <MetricHelp metricId="regime_analysis" />
        </h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Режим / год</th>
                <th className="numeric">V0 Rank IC</th>
                <th className="numeric">V1 Rank IC</th>
                <th className="numeric">V0 Top20</th>
                <th className="numeric">V1 Top20</th>
                <th className="numeric">V0 портфель</th>
                <th className="numeric">V1 портфель</th>
                <th className="numeric">Наблюдений</th>
              </tr>
            </thead>
            <tbody>
              {!regimes.length ? (
                <tr>
                  <td colSpan={8}>Данные режимов пока недоступны.</td>
                </tr>
              ) : (
                regimes.map((r, idx) => (
                  <tr key={`${r.regime ?? r.year ?? idx}`}>
                    <td>{r.label ?? r.regime ?? r.year ?? "—"}</td>
                    <td className="numeric">{fmtIc(r.v0_rank_ic)}</td>
                    <td className="numeric">{fmtIc(r.v1_rank_ic)}</td>
                    <td className="numeric">{formatPercent(r.v0_top20)}</td>
                    <td className="numeric">{formatPercent(r.v1_top20)}</td>
                    <td className="numeric">{formatPercent(r.v0_portfolio_result)}</td>
                    <td className="numeric">{formatPercent(r.v1_portfolio_result)}</td>
                    <td className="numeric">{r.observations ?? "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <EconomicViabilityBlock
        cagr={displayCagr}
        totalReturn={displayReturn}
        maxDrawdown={displayDd}
        annualRate={hurdle}
        onAnnualRateChange={setHurdle}
        testId="diagnostics-economic"
      />

      <div className="card" data-testid="what-we-learned">
        <h3>Что мы узнали?</h3>
        <ul>
          {learned.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </div>

      <details>
        <summary>Технические детали</summary>
        <pre className="tech-block">
          {JSON.stringify(
            { hurdle, has_summary: Boolean(summary), top_tail_rows: topTail.length },
            null,
            2,
          )}
        </pre>
      </details>
    </section>
  );
}
