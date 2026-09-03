import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getInstrumentFeaturesLatest,
  hasFeatureQualityWarning,
  hasInsufficientHistory,
  type InstrumentFeatures,
} from "../api/analytics";
import { errorMessage } from "../api/client";
import {
  getBatches,
  getCandles,
  getDataQualityIssues,
  getInstrument,
  type Batch,
  type Candle,
  type DataQualityIssue,
  type Instrument,
} from "../api/market";
import { getInstrumentTechnicalLatest, type TechnicalSignal } from "../api/technical";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { QuotesExplorer } from "../features/quotes/QuotesExplorer";
import { MetricHelp } from "../help";
import { formatDate, formatDateTime, formatNumber, formatPercent, formatPrice, formatZScore } from "../utils/format";
import { labels } from "../utils/labels";

type Tab = "overview" | "quotes" | "batches" | "quality" | "analytics" | "technical";

interface InstrumentData {
  instrument: Instrument & { last_close?: number | null; isin?: string | null };
  sparkCandles: Candle[];
  batches: Batch[];
  issues: DataQualityIssue[];
  features: InstrumentFeatures | null;
  technical: TechnicalSignal | null;
}

export function InstrumentPage() {
  const { instrumentId = "" } = useParams();
  const [data, setData] = useState<InstrumentData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(null);
    Promise.all([
      getInstrument(instrumentId, controller.signal),
      getCandles(instrumentId, 50, controller.signal),
      getBatches(instrumentId, controller.signal),
      getDataQualityIssues(instrumentId, controller.signal),
      getInstrumentFeaturesLatest(instrumentId, controller.signal).catch(() => null),
      getInstrumentTechnicalLatest(instrumentId, controller.signal).catch(() => null),
    ])
      .then(([instrument, sparkCandles, batches, issues, features, technical]) =>
        setData({ instrument, sparkCandles, batches, issues, features, technical }),
      )
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(errorMessage(reason));
      });
    return () => controller.abort();
  }, [instrumentId]);

  if (error) {
    return <PageState kind="error">{error}</PageState>;
  }
  if (!data) return <PageState kind="loading" title="Загрузка инструмента…" />;

  const { instrument, batches, issues, features, technical } = data;
  const lastClose = instrument.last_close ?? data.sparkCandles.at(-1)?.close ?? null;
  const sources =
    instrument.sources?.length
      ? instrument.sources
      : [...new Set((instrument.mappings ?? []).map((m) => m.source))];
  const factors = technical?.factor_contributions;

  return (
    <section>
      <nav className="breadcrumb" aria-label="Навигация">
        <Link to="/market">{labels.nav.market}</Link>
        <span aria-hidden>/</span>
        <span>{instrument.symbol}</span>
      </nav>

      <PageHeader
        title={`${instrument.name}`}
        description={`${instrument.symbol} · ${labels.assetClass(instrument.asset_class)} · ${instrument.exchange ?? "—"} · ${instrument.currency}${instrument.isin ? ` · ${instrument.isin}` : ""} · RAW котировки и производные признаки`}
        helpPageId="instrument"
      />

      <div className="card-grid">
        <MetricCard label="Последняя цена" value={formatPrice(lastClose)} helpId="last_price" />
        <MetricCard label="Последняя дата" value={formatDate(instrument.last_timestamp)} />
        <MetricCard label="Начало истории" value={formatDate(instrument.first_timestamp)} />
        <MetricCard label="Количество свечей" value={formatNumber(instrument.records_count)} />
        <MetricCard
          label="Качество данных"
          value={issues.some((i) => i.severity === "error") ? "Ошибки" : issues.length ? "Есть предупреждения" : "Без замечаний"}
          hint={`${issues.length} записей DQ`}
          helpId="data_quality"
        />
      </div>

      <div className="tabs" role="tablist">
        {(
          [
            ["overview", "Обзор"],
            ["quotes", "Котировки"],
            ["batches", "Загрузки"],
            ["quality", "Качество данных"],
            ["analytics", "Аналитика"],
            ["technical", "Технический анализ"],
          ] as const
        ).map(([id, title]) => (
          <button key={id} type="button" className={`tab${tab === id ? " active" : ""}`} onClick={() => setTab(id)}>
            {title}
          </button>
        ))}
      </div>

      {tab === "overview" ? (
        <article className="panel">
          <h2>Основные сведения</h2>
          <div className="key-value">
            <span>Статус</span>
            <StatusBadge status={instrument.is_active ? "active" : "inactive"} />
          </div>
          <div className="key-value">
            <span>Источники</span>
            <strong>{sources.length ? sources.join(", ") : "—"}</strong>
          </div>
          <div className="key-value">
            <span>Актуальность</span>
            <strong>{labels.dataFreshness(instrument.last_timestamp)}</strong>
          </div>
          <h2 style={{ marginTop: "1rem" }}>Привязки источников</h2>
          {instrument.mappings?.length ? (
            instrument.mappings.map((mapping) => (
              <div className="key-value" key={`${mapping.source}-${mapping.source_symbol}`}>
                <span>{mapping.source}</span>
                <strong className="mono">{mapping.source_symbol}</strong>
              </div>
            ))
          ) : (
            <p className="muted">Нет детальных mapping.</p>
          )}
        </article>
      ) : null}

      {tab === "quotes" ? (
        <article className="panel quotes-panel">
          <h2>
            Котировки <MetricHelp metricId="raw_candles" />
          </h2>
          <QuotesExplorer
            instrumentId={instrumentId}
            symbol={instrument.symbol}
            firstTimestamp={instrument.first_timestamp}
            lastTimestamp={instrument.last_timestamp}
            recordsCount={instrument.records_count}
          />
        </article>
      ) : null}

      {tab === "batches" ? (
        <article className="panel">
          <h2>Последние загрузки</h2>
          {batches.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Источник</th>
                    <th>Статус</th>
                    <th>Начало</th>
                    <th>Завершение</th>
                    <th>Получено</th>
                  </tr>
                </thead>
                <tbody>
                  {batches.map((batch) => (
                    <tr key={batch.id}>
                      <td className="mono">{batch.id}</td>
                      <td>{batch.source}</td>
                      <td>
                        <StatusBadge status={batch.status} />
                      </td>
                      <td>{formatDateTime(batch.started_at)}</td>
                      <td>{formatDateTime(batch.finished_at)}</td>
                      <td className="numeric">{formatNumber(batch.records_received)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <PageState kind="empty" title="Нет загрузок по инструменту" />
          )}
        </article>
      ) : null}

      {tab === "quality" ? (
        <article className="panel">
          <h2>
            Проблемы качества <MetricHelp metricId="data_quality" />
          </h2>
          <p className="muted">Показаны доступные записи DQ. Модель append-only — исторические записи могут накапливаться.</p>
          {issues.length ? (
            issues.map((issue) => (
              <div className="issue" key={issue.id}>
                <StatusBadge status={issue.severity} />
                <div>
                  <strong>{labels.issueType(issue.issue_type)}</strong>
                  <p>{issue.message}</p>
                  <small className="muted">
                    {formatDateTime(issue.detected_at)} · <span className="mono">{issue.issue_type}</span>
                  </small>
                </div>
              </div>
            ))
          ) : (
            <p className="muted">Замечаний нет.</p>
          )}
        </article>
      ) : null}

      {tab === "analytics" ? (
        <article className="panel">
          <h2>Аналитика</h2>
          {!features ? (
            <PageState kind="empty" title="Признаки ещё не рассчитаны" />
          ) : (
            <>
              <div className="key-value">
                <span>Feature set</span>
                <strong className="mono">
                  {features.feature_set_code ?? "basic_daily"} v{features.feature_version}
                </strong>
              </div>
              <div className="key-value">
                <span>Дата расчёта</span>
                <strong>{formatDate(features.date)}</strong>
              </div>
              {hasFeatureQualityWarning(features.quality_flags) ? (
                <p>
                  <StatusBadge status="warning" /> Данные требуют проверки
                  <span className="muted"> · Подозрительный ценовой разрыв</span>
                </p>
              ) : null}
              <div className="card-grid" style={{ marginTop: "1rem" }}>
                <MetricCard
                  label="Доходность 1 день"
                  helpId="return_1d"
                  value={
                    hasInsufficientHistory(features.quality_flags, "return_1d")
                      ? "Недостаточно истории"
                      : formatPercent(features.return_1d)
                  }
                />
                <MetricCard
                  label="Доходность 5 дней"
                  helpId="return_5d"
                  value={
                    hasInsufficientHistory(features.quality_flags, "return_5d")
                      ? "Недостаточно истории"
                      : formatPercent(features.return_5d)
                  }
                />
                <MetricCard
                  label="Доходность 20 дней"
                  helpId="return_20d"
                  value={
                    hasInsufficientHistory(features.quality_flags, "return_20d")
                      ? "Недостаточно истории"
                      : formatPercent(features.return_20d)
                  }
                />
                <MetricCard label="Волатильность 5 дней" value={formatPercent(features.volatility_5d)} helpId="volatility_5d" />
                <MetricCard label="Волатильность 20 дней" value={formatPercent(features.volatility_20d)} helpId="volatility_20d" />
                <MetricCard label="Просадка 20 дней" value={formatPercent(features.drawdown_20d)} helpId="drawdown_20d" />
                <MetricCard label="Изменение объёма" value={formatPercent(features.volume_change_1d)} helpId="volume_change_1d" />
                <MetricCard label="Z-score объёма 20д" value={formatZScore(features.volume_zscore_20d)} helpId="volume_zscore_20d" />
              </div>
            </>
          )}
        </article>
      ) : null}

      {tab === "technical" ? (
        <article className="panel">
          <h2>Технический анализ</h2>
          {!technical ? (
            <PageState kind="empty" title="Технический сигнал ещё не рассчитан" />
          ) : (
            <>
              <div className="key-value">
                <span>Модель</span>
                <strong className="mono">
                  {technical.model_code}_v{technical.model_version}
                </strong>
              </div>
              <div className="key-value">
                <span>На дату</span>
                <strong>{formatDate(technical.as_of_date)}</strong>
              </div>
              <div className="key-value">
                <span>Состояние</span>
                <strong>{labels.direction(technical.direction)}</strong>
              </div>
              <div className="key-value">
                <span>Качество</span>
                <strong>{technical.is_valid ? "валид" : "невалид"}</strong>
              </div>
              <div className="card-grid" style={{ marginTop: "1rem" }}>
                <MetricCard label="Score" value={technical.score.toFixed(2)} helpId="technical_score" />
                <MetricCard label="Confidence" value={formatPercent(technical.confidence)} helpId="confidence" />
                <MetricCard
                  label="RSI14"
                  value={technical.rsi14 != null ? technical.rsi14.toFixed(1) : "—"}
                  helpId="rsi14"
                />
                <MetricCard label="SMA20 dist" value={formatPercent(technical.sma20_distance)} helpId="sma20_distance" />
                <MetricCard label="EMA20 dist" value={formatPercent(technical.ema20_distance)} helpId="ema20_distance" />
                <MetricCard label="ATR14%" value={formatPercent(technical.atr14_pct)} helpId="atr14_pct" />
                <MetricCard label="Return 5d" value={formatPercent(technical.return_5d)} helpId="return_5d" />
                <MetricCard label="Return 20d" value={formatPercent(technical.return_20d)} helpId="return_20d" />
                <MetricCard label="Volume Z 20d" value={formatZScore(technical.volume_zscore_20d)} helpId="volume_zscore_20d" />
              </div>
              <h2 style={{ marginTop: "1rem" }}>Вклад факторов</h2>
              <div className="card-grid">
                <MetricCard label="Trend" value={factors?.trend != null ? factors.trend.toFixed(3) : "—"} />
                <MetricCard label="Momentum" value={factors?.momentum != null ? factors.momentum.toFixed(3) : "—"} />
                <MetricCard label="RSI" value={factors?.rsi != null ? factors.rsi.toFixed(3) : "—"} />
                <MetricCard label="Volume" value={factors?.volume != null ? factors.volume.toFixed(3) : "—"} />
              </div>
            </>
          )}
        </article>
      ) : null}
    </section>
  );
}
