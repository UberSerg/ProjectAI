import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import { getCalibrationReport, type CalibrationReport } from "../api/investment";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";

function rate(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

function barWidth(pred: number | null, real: number | null): { p: number; r: number } {
  const vals = [Math.abs(pred ?? 0), Math.abs(real ?? 0), 0.01];
  const max = Math.max(...vals);
  return {
    p: pred == null ? 0 : Math.min(100, (Math.abs(pred) / max) * 100),
    r: real == null ? 0 : Math.min(100, (Math.abs(real) / max) * 100),
  };
}

function heroConclusion(report: CalibrationReport): { title: string; body: string } {
  const status = report.candidate_v0.calibration.calibration_status.toUpperCase();
  const level = report.candidate_v0.confidence.confidence_level.toUpperCase();
  const mature = report.candidate_v0.calibration.sample_count;
  const pending = report.candidate_v0.calibration.pending_count;

  if (status === "INSUFFICIENT_SAMPLE" || level === "UNKNOWN") {
    return {
      title: "Пока рано опираться на прогнозы акций",
      body:
        "Зрелых исходов недостаточно (или уверенность неизвестна). В таком состоянии Kraken не должен наращивать долю акций «по модели» — капитал осторожнее, пока выборка не созреет.",
    };
  }
  if (status.includes("POOR") || status.includes("MISCALIBR")) {
    return {
      title: "Модель пока плохо совпадает с реальностью",
      body:
        "Калибровка показывает расхождение прогноза и факта. Доверие к equity-сигналу снижается — это влияет на инвестиционное решение и лимиты акций.",
    };
  }
  return {
    title: "Есть база, чтобы оценивать доверие к прогнозам",
    body: `Сейчас доступно ${mature} зрелых исходов и ${pending} ещё в ожидании горизонта. Смотрите статус калибровки и уровень уверенности ниже — это вход в решение по капиталу, не обещание доходности.`,
  };
}

export function CalibrationPage() {
  const [report, setReport] = useState<CalibrationReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    getCalibrationReport(controller.signal)
      .then(setReport)
      .catch((reason: unknown) => setError(errorMessage(reason)))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  if (loading) return <PageState kind="loading" title="Загрузка качества прогнозов…" />;
  if (!report) {
    return (
      <PageState kind="error" title="Не удалось загрузить калибровку">
        {error ?? "Нет данных"}
      </PageState>
    );
  }

  const v0 = report.candidate_v0;
  const v1 = report.candidate_v1;
  const hero = heroConclusion(report);

  return (
    <div className="allocation-page">
      <PageHeader
        title="Качество прогнозов"
        description="Насколько прогнозам акций можно доверять прямо сейчас — и как это влияет на долю капитала."
        helpPageId="prediction_calibration"
      />
      <p className="page-purpose">
        Это экран доверия к модели, не экран доходности. Если выборка мала или статус UNKNOWN — Kraken
        ограничивает опору на equity в{" "}
        <Link to="/investment-decision">инвестиционном решении</Link> и{" "}
        <Link to="/portfolio/candidate">кандидате портфеля</Link>.
      </p>
      {error ? <div className="banner banner-warning">{error}</div> : null}

      <div className="card ds-card-hero" data-testid="calibration-hero">
        <div className="ds-card-title">Вывод для инвестора</div>
        <div className="ds-card-headline" data-testid="calibration-hero-title">
          {hero.title}
        </div>
        <p style={{ margin: "0.5rem 0 0" }} data-testid="calibration-hero-body">
          {hero.body}
        </p>
        <p className="muted" style={{ margin: "0.75rem 0 0" }}>
          {v0.confidence.reason_ru}
        </p>
      </div>

      <div className="card-grid">
        <MetricCard
          label="Зрелые outcomes"
          value={String(v0.calibration.sample_count)}
          helpId="mature_outcome"
          hint="Прогнозы, у которых горизонт уже закрылся"
        />
        <MetricCard
          label="Pending (ждут горизонта)"
          value={String(v0.calibration.pending_count)}
          helpId="evaluated_prediction"
          hint="Ещё рано судить — исход не созрел"
        />
        <MetricCard
          label="Статус калибровки"
          value={v0.calibration.calibration_status}
          helpId="prediction_calibration"
        />
        <MetricCard
          label="Уверенность"
          value={
            <>
              <StatusBadge status={v0.confidence.confidence_level.toLowerCase()} />{" "}
              {v0.confidence.confidence_level}
            </>
          }
          helpId="confidence_level"
        />
      </div>

      <div className="card">
        <h3>Влияние на портфель</h3>
        <p>
          Пока confidence неизвестна или выборка недостаточна, доля акций в решении ограничивается:
          Kraken не «верит модели на слово». Это видно в инвестиционном решении и кандидате портфеля —
          не как баг, а как осторожный режим.
        </p>
        <p className="muted">
          Pipeline: {report.pipeline}. Сравнение без автовыбора победителя.
        </p>
      </div>

      <div className="card-grid">
        <div className="card">
          <h3>{v0.title}</h3>
          <p className="muted">
            {v0.id} · {v0.semantic}
          </p>
          <p className="muted">{v0.calibration.uncertainty_note}</p>
        </div>
        <div className="card">
          <h3>{v1.title}</h3>
          <p className="muted">
            {v1.id} · {v1.semantic}
          </p>
          <p>RANKING_SCORE — не процент доходности. Калибровка return % для V1 запрещена.</p>
          <p className="muted">{v1.confidence.reason_ru}</p>
          <div className="card-grid">
            <MetricCard label="Sample" value={String(v1.calibration.sample_count)} helpId="ranking_score" />
            <MetricCard
              label="Confidence"
              value={v1.confidence.confidence_level}
              helpId="confidence_level"
            />
          </div>
        </div>
      </div>

      <details className="card" data-testid="calibration-metrics-details">
        <summary>
          <strong>Метрики модели</strong>
          <span className="muted"> — Bias, MAE, Spearman, buckets</span>
        </summary>
        <div className="metric-grid" style={{ marginTop: "1rem" }}>
          <MetricCard
            label="Bias"
            value={v0.calibration.bias == null ? "—" : v0.calibration.bias.toFixed(4)}
            hint={v0.calibration.bias_sign ?? undefined}
            helpId="model_bias"
          />
          <MetricCard
            label="MAE"
            value={v0.calibration.mae == null ? "—" : v0.calibration.mae.toFixed(4)}
            helpId="prediction_error"
          />
          <MetricCard label="Direction accuracy" value={rate(v0.calibration.direction_accuracy)} />
          <MetricCard
            label="Spearman IC (V1)"
            value={
              v1.calibration.mean_spearman_rank_ic == null
                ? "—"
                : v1.calibration.mean_spearman_rank_ic.toFixed(3)
            }
            helpId="ranking_score"
          />
          <MetricCard label="Top20 realized (V1)" value={rate(v1.calibration.mean_top20_realized)} />
        </div>

        <h4>Prediction bucket vs Realized (V0)</h4>
        <p className="muted">
          Если прогнозы модели систематически выше реальности, Kraken уменьшает доверие к ним.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Bucket</th>
                <th>n</th>
                <th>Ожидание модели</th>
                <th>Фактический результат</th>
                <th>Chart</th>
              </tr>
            </thead>
            <tbody>
              {report.chart_data.v0_buckets.map((b) => {
                const w = barWidth(b.average_prediction, b.average_realized_return);
                return (
                  <tr key={b.bucket}>
                    <td>{b.bucket}</td>
                    <td>{b.sample_count}</td>
                    <td>{rate(b.average_prediction)}</td>
                    <td>{rate(b.average_realized_return)}</td>
                    <td style={{ minWidth: 160 }}>
                      <div className="muted" style={{ fontSize: 12 }}>
                        pred
                      </div>
                      <div
                        style={{
                          height: 8,
                          width: `${w.p}%`,
                          background: "var(--accent, #3b82f6)",
                          marginBottom: 4,
                        }}
                      />
                      <div className="muted" style={{ fontSize: 12 }}>
                        realized
                      </div>
                      <div
                        style={{
                          height: 8,
                          width: `${w.r}%`,
                          background: "var(--ok, #16a34a)",
                        }}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
