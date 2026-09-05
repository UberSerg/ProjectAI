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

  return (
    <div className="allocation-page">
      <PageHeader
        title="Качество прогнозов Kraken"
        description="Prediction → Calibration → Confidence. Прогноз не равен гарантии."
        helpPageId="prediction_calibration"
      />
      {error ? <div className="banner banner-warning">{error}</div> : null}

      <p className="muted">
        Pipeline: {report.pipeline}. Сравнение без автовыбора победителя.{" "}
        <Link to="/investment-decision">Инвестиционное решение</Link>
      </p>

      <div className="card-grid">
        <div className="card">
          <h3>{v0.title}</h3>
          <p className="muted">{v0.id} · {v0.semantic}</p>
          <div className="card-grid">
            <MetricCard
              label="Зрелые outcomes"
              value={String(v0.calibration.sample_count)}
              helpId="mature_outcome"
            />
            <MetricCard
              label="Pending"
              value={String(v0.calibration.pending_count)}
              helpId="evaluated_prediction"
            />
            <MetricCard
              label="Calibration"
              value={v0.calibration.calibration_status}
              helpId="prediction_calibration"
            />
            <MetricCard
              label="Confidence"
              value={v0.confidence.confidence_level}
              helpId="confidence_level"
            />
          </div>
          <p>
            Bias: {v0.calibration.bias == null ? "—" : v0.calibration.bias.toFixed(4)} (
            {v0.calibration.bias_sign ?? "—"})
          </p>
          <p>MAE: {v0.calibration.mae == null ? "—" : v0.calibration.mae.toFixed(4)}</p>
          <p>Direction accuracy: {rate(v0.calibration.direction_accuracy)}</p>
          <p className="muted">{v0.confidence.reason_ru}</p>
          <StatusBadge status={v0.confidence.confidence_level.toLowerCase()} />
        </div>

        <div className="card">
          <h3>{v1.title}</h3>
          <p className="muted">{v1.id} · {v1.semantic}</p>
          <p>
            RANKING_SCORE — не процент доходности. Калибровка return % для V1 запрещена.
          </p>
          <div className="card-grid">
            <MetricCard
              label="Sample"
              value={String(v1.calibration.sample_count)}
              helpId="ranking_score"
            />
            <MetricCard
              label="Spearman IC"
              value={
                v1.calibration.mean_spearman_rank_ic == null
                  ? "—"
                  : v1.calibration.mean_spearman_rank_ic.toFixed(3)
              }
              helpId="ranking_score"
            />
            <MetricCard
              label="Top20 realized"
              value={rate(v1.calibration.mean_top20_realized)}
              helpId="ranking_score"
            />
            <MetricCard
              label="Confidence"
              value={v1.confidence.confidence_level}
              helpId="confidence_level"
            />
          </div>
          <p className="muted">{v1.confidence.reason_ru}</p>
        </div>
      </div>

      <div className="card">
        <h3>Prediction bucket vs Realized (V0)</h3>
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
      </div>
    </div>
  );
}
