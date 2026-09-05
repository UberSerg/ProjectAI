import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  getProspectiveBatch,
  getProspectiveEvaluation,
  getProspectiveLatest,
  listProspectiveBatches,
  type ProspectiveBatchDetail,
  type ProspectiveBatchSummary,
  type ProspectiveEvaluation,
  type ProspectiveLatest,
  type ProspectivePredictionRow,
} from "../api/modelEdge";
import { MetricCard, PageHeader, PageState } from "../components/Ui";
import { sampleMaturityLabel } from "../features/researchLab/sampleMaturity";
import { MetricHelp } from "../help";
import { formatMoney, formatPercent } from "../utils/format";

const PIPELINE_STAGES: Array<{
  id: string;
  label: string;
  flag: keyof NonNullable<ProspectiveLatest["pipeline"]>;
}> = [
  { id: "activated", label: "Эксперимент активирован", flag: "experiment_activated" },
  { id: "market", label: "Новые рыночные данные", flag: "new_market_data" },
  { id: "predictions", label: "Два прогноза", flag: "paired_predictions" },
  { id: "decision", label: "Решение стратегии", flag: "strategy_decision" },
  { id: "open", label: "Будущее открытие рынка", flag: "future_open" },
  { id: "exec", label: "Исполнение", flag: "execution" },
  { id: "obs20", label: "20 торговых наблюдений", flag: "twenty_observations" },
  { id: "eval", label: "Оценка моделей", flag: "model_evaluation" },
];

function stageDone(
  latest: ProspectiveLatest | null,
  flag: keyof NonNullable<ProspectiveLatest["pipeline"]>,
  id: string,
): boolean {
  const pipeline = latest?.pipeline;
  if (!pipeline) {
    // Fallback: activation alone when experiment exists
    if (flag === "experiment_activated") {
      return Boolean(latest?.activated_at || latest?.experiment?.activated_at || latest?.status);
    }
    return false;
  }
  if (pipeline[flag] === true) return true;
  const completed = pipeline.completed ?? [];
  return completed.includes(id) || completed.includes(String(flag));
}

function portfolioOf(
  latest: ProspectiveLatest | null,
  side: "v0" | "v1",
): { nav?: number | null; cash?: number | null; drawdown?: number | null; trade_count?: number | null; turnover_ratio?: number | null; human_name?: string | null } {
  if (!latest) return {};
  if (side === "v0") {
    return (
      latest.portfolio_a ??
      latest.portfolios?.v0 ??
      latest.portfolios?.a ??
      { nav: 1_000_000, cash: 1_000_000 }
    );
  }
  return (
    latest.portfolio_b ??
    latest.portfolios?.v1 ??
    latest.portfolios?.b ??
    { nav: 1_000_000, cash: 1_000_000 }
  );
}

function formatRankingScore(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return Number(value).toFixed(4);
}

function yesNo(v?: boolean | null): string {
  if (v == null) return "—";
  return v ? "да" : "нет";
}

export function ResearchProspectiveModelsPage() {
  const [latest, setLatest] = useState<ProspectiveLatest | null>(null);
  const [batches, setBatches] = useState<ProspectiveBatchSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [batchDetail, setBatchDetail] = useState<ProspectiveBatchDetail | null>(null);
  const [evaluation, setEvaluation] = useState<ProspectiveEvaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getProspectiveLatest(controller.signal),
      listProspectiveBatches(controller.signal),
      getProspectiveEvaluation(controller.signal).catch(() => null),
    ])
      .then(([lat, list, ev]) => {
        setLatest(lat);
        setBatches(list);
        setEvaluation(ev);
        if (list.length) setSelectedId(String(list[list.length - 1]?.id ?? ""));
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
    if (!selectedId) {
      setBatchDetail(null);
      return;
    }
    const controller = new AbortController();
    getProspectiveBatch(selectedId, controller.signal)
      .then(setBatchDetail)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      });
    return () => controller.abort();
  }, [selectedId]);

  const batchCount =
    latest?.batch_count ?? latest?.paired_prediction_count ?? batches.length;
  const isEmptyProud = !loading && (batchCount == null || Number(batchCount) === 0);

  const matureCount =
    evaluation?.mature_dates ?? evaluation?.mature_count ?? latest?.mature_outcome_count ?? 0;
  const maturityLabel = sampleMaturityLabel(
    evaluation?.sample_maturity ?? Number(matureCount),
  );

  const portA = portfolioOf(latest, "v0");
  const portB = portfolioOf(latest, "v1");
  const agreement = latest?.agreement ?? batchDetail?.agreement ?? null;

  const predictions: ProspectivePredictionRow[] = useMemo(
    () => batchDetail?.predictions ?? batchDetail?.rows ?? [],
    [batchDetail],
  );

  if (error && !latest) return <PageState kind="error">{error}</PageState>;
  if (loading) {
    return <PageState kind="loading" title="Загрузка проспективного сравнения…" />;
  }

  return (
    <section className="research-prospective">
      <PageHeader
        title="Проспективное сравнение V0 / V1"
        description="Одинаковые условия, отличается только модель. Эксперимент идёт только вперёд."
        helpPageId="research_prospective"
        actions={
          <Link to="/research" className="secondary button-link">
            ← Лаборатория
          </Link>
        }
      />

      <div className="info-panel">
        Парный проспективный эксперимент: обе модели видят один и тот же срез признаков; исполнение
        — следующее открытие. Это не исторический бэктест и не рекомендация.{" "}
        <MetricHelp metricId="paired_prospective_model" />
      </div>

      {isEmptyProud ? (
        <div className="card proud-empty" data-testid="prospective-empty-proud">
          <h2>Эксперимент запущен. Ждём первый новый рыночный день.</h2>
          <p className="muted">
            Портфели стартуют с виртуального капитала; парных прогнозов и сделок пока нет. Пустое
            состояние здесь — ожидаемый научный старт, а не ошибка.
          </p>
          <div className="metric-grid">
            <MetricCard label="Портфель V0 (стоимость)" value={formatMoney(portA.nav ?? 1_000_000)} />
            <MetricCard label="Портфель V0 (кэш)" value={formatMoney(portA.cash ?? 1_000_000)} />
            <MetricCard label="Портфель V1 (стоимость)" value={formatMoney(portB.nav ?? 1_000_000)} />
            <MetricCard label="Портфель V1 (кэш)" value={formatMoney(portB.cash ?? 1_000_000)} />
          </div>
        </div>
      ) : null}

      <div className="card" data-testid="prospective-pipeline">
        <h3>Статус конвейера</h3>
        <ol className="pipeline-stages">
          {PIPELINE_STAGES.map((stage) => {
            const done = stageDone(latest, stage.flag, stage.id);
            return (
              <li
                key={stage.id}
                className={done ? "pipeline-done" : "pipeline-pending"}
                data-done={done ? "true" : "false"}
              >
                {stage.label}
              </li>
            );
          })}
        </ol>
      </div>

      <div className="card" data-testid="sample-maturity">
        <h3>
          Зрелость выборки <MetricHelp metricId="sample_maturity" />
        </h3>
        <p>
          {maturityLabel}
          {matureCount != null ? (
            <span className="muted"> · зрелых дат: {Number(matureCount)}</span>
          ) : null}
        </p>
        {Number(matureCount) < 20 ? (
          <p className="field-hint">Победителя объявлять рано: наблюдений ещё мало.</p>
        ) : null}
      </div>

      {!isEmptyProud ? (
        <>
          <div className="diagnostics-two-col">
            <div className="card">
              <h3>{portA.human_name ?? "Портфель модели V0"}</h3>
              <div className="metric-grid">
                <MetricCard label="Стоимость портфеля" value={formatMoney(portA.nav)} />
                <MetricCard label="Кэш" value={formatMoney(portA.cash)} />
                <MetricCard label="Просадка" value={formatPercent(portA.drawdown)} />
                <MetricCard
                  label="Оборот"
                  value={
                    portA.turnover_ratio != null
                      ? `${Number(portA.turnover_ratio).toFixed(1)}×`
                      : "—"
                  }
                />
              </div>
            </div>
            <div className="card">
              <h3>{portB.human_name ?? "Портфель модели V1"}</h3>
              <div className="metric-grid">
                <MetricCard label="Стоимость портфеля" value={formatMoney(portB.nav)} />
                <MetricCard label="Кэш" value={formatMoney(portB.cash)} />
                <MetricCard label="Просадка" value={formatPercent(portB.drawdown)} />
                <MetricCard
                  label="Оборот"
                  value={
                    portB.turnover_ratio != null
                      ? `${Number(portB.turnover_ratio).toFixed(1)}×`
                      : "—"
                  }
                />
              </div>
            </div>
          </div>

          <div className="card" data-testid="model-agreement">
            <h3>
              Согласие моделей <MetricHelp metricId="rank_correlation" />
            </h3>
            <p className="field-hint">
              Это показывает, насколько модели думают одинаково, но не говорит, какая из них права.{" "}
              <MetricHelp metricId="top20_overlap" />
            </p>
            <div className="metric-grid">
              <MetricCard
                label="Корреляция рангов"
                value={
                  agreement?.rank_correlation != null
                    ? Number(agreement.rank_correlation).toFixed(3)
                    : "—"
                }
                helpId="rank_correlation"
              />
              <MetricCard
                label="Пересечение Top 20"
                value={formatPercent(agreement?.top20_overlap)}
                helpId="top20_overlap"
              />
              <MetricCard
                label="Совпадение №1"
                value={yesNo(agreement?.top1_agreement)}
              />
              <MetricCard
                label="Пересечение выбранных"
                value={formatPercent(agreement?.selected_overlap)}
              />
            </div>
          </div>

          <div className="card" data-testid="prospective-predictions">
            <h3>Парный прогноз</h3>
            <label>
              Дата / batch
              <select
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value)}
                aria-label="Выбор batch"
              >
                {batches.map((b) => (
                  <option key={String(b.id)} value={String(b.id)}>
                    {b.as_of_date ?? b.id} · {b.status ?? ""}
                  </option>
                ))}
              </select>
            </label>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Тикер</th>
                    <th className="numeric">V0 ожид. доходность</th>
                    <th className="numeric">Ранг V0</th>
                    <th className="numeric">V1 рейтинговый балл</th>
                    <th className="numeric">Ранг V1</th>
                    <th className="numeric">Δ ранга</th>
                    <th>V0 выбрана</th>
                    <th>V1 выбрана</th>
                    <th>Состояние</th>
                  </tr>
                </thead>
                <tbody>
                  {!predictions.length ? (
                    <tr>
                      <td colSpan={9}>Нет строк прогноза для выбранного batch.</td>
                    </tr>
                  ) : (
                    predictions.map((row, idx) => (
                      <tr key={`${row.ticker ?? row.instrument_id ?? idx}`}>
                        <td>{row.ticker ?? row.instrument_id ?? "—"}</td>
                        <td className="numeric" data-testid="v0-expected-return">
                          {formatPercent(row.v0_expected_return)}
                        </td>
                        <td className="numeric">{row.v0_rank ?? "—"}</td>
                        <td className="numeric" data-testid="v1-ranking-score">
                          {formatRankingScore(row.v1_ranking_score)}
                        </td>
                        <td className="numeric">{row.v1_rank ?? "—"}</td>
                        <td className="numeric">{row.rank_delta ?? "—"}</td>
                        <td>{yesNo(row.v0_selected)}</td>
                        <td>{yesNo(row.v1_selected)}</td>
                        <td>{row.state ?? "—"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <p className="field-hint">
              Рейтинговый балл V1 — число для порядка, не процент доходности.{" "}
              <MetricHelp metricId="ranking_score" />
            </p>
          </div>
        </>
      ) : null}

      <details>
        <summary>Технические детали</summary>
        <pre className="tech-block">
          {JSON.stringify(
            {
              experiment: latest?.experiment ?? {
                status: latest?.status,
                activated_at: latest?.activated_at,
              },
              batch_count: batchCount,
              mature_count: matureCount,
            },
            null,
            2,
          )}
        </pre>
      </details>
    </section>
  );
}
