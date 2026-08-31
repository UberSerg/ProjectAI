import { useEffect, useMemo, useState } from "react";
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
import { Sparkline } from "../components/Sparkline";
import { MetricCard, PageState, StatusBadge } from "../components/Ui";
import { formatDate, formatDateTime, formatNumber, formatPercent, formatPrice, formatZScore } from "../utils/format";
import { labels } from "../utils/labels";

type Tab = "overview" | "quotes" | "batches" | "quality" | "analytics";

interface InstrumentData {
  instrument: Instrument & { last_close?: number | null; isin?: string | null };
  candles: Candle[];
  batches: Batch[];
  issues: DataQualityIssue[];
  features: InstrumentFeatures | null;
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
    ])
      .then(([instrument, candles, batches, issues, features]) =>
        setData({ instrument, candles, batches, issues, features }),
      )
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(errorMessage(reason));
      });
    return () => controller.abort();
  }, [instrumentId]);

  const closes = useMemo(() => data?.candles.map((c) => c.close) ?? [], [data]);
  const lastClose = data?.instrument.last_close ?? data?.candles.at(-1)?.close ?? null;

  if (error) {
    return <PageState kind="error">{error}</PageState>;
  }
  if (!data) return <PageState kind="loading" title="Загрузка инструмента…" />;

  const { instrument, candles, batches, issues, features } = data;
  const sources =
    instrument.sources?.length
      ? instrument.sources
      : [...new Set((instrument.mappings ?? []).map((m) => m.source))];

  return (
    <section>
      <nav className="breadcrumb" aria-label="Навигация">
        <Link to="/market">{labels.nav.market}</Link>
        <span aria-hidden>/</span>
        <span>{instrument.symbol}</span>
      </nav>
      <Link className="back-link" to="/market">
        ← {labels.nav.market}
      </Link>

      <div className="instrument-hero">
        <h1>
          {instrument.name}
          <span className="symbol">{instrument.symbol}</span>
        </h1>
        <p className="meta">
          {labels.assetClass(instrument.asset_class)} · {instrument.exchange ?? "—"} · {instrument.currency}
          {instrument.isin ? ` · ${instrument.isin}` : ""}
        </p>
      </div>

      <div className="card-grid">
        <MetricCard label="Последняя цена" value={formatPrice(lastClose)} />
        <MetricCard label="Последняя дата" value={formatDate(instrument.last_timestamp)} />
        <MetricCard label="Начало истории" value={formatDate(instrument.first_timestamp)} />
        <MetricCard label="Количество свечей" value={formatNumber(instrument.records_count)} />
        <MetricCard
          label="Качество данных"
          value={issues.some((i) => i.severity === "error") ? "Ошибки" : issues.length ? "Есть предупреждения" : "Без замечаний"}
          hint={`${issues.length} записей DQ`}
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
        <article className="panel">
          <h2>Цена закрытия</h2>
          <Sparkline values={closes} />
          <h2 style={{ marginTop: "1rem" }}>Последние свечи</h2>
          {candles.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Дата</th>
                    <th>Open</th>
                    <th>High</th>
                    <th>Low</th>
                    <th>Close</th>
                    <th>Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {[...candles].reverse().map((candle) => (
                    <tr key={`${candle.timestamp}-${candle.source ?? ""}`}>
                      <td>{formatDate(candle.timestamp)}</td>
                      <td className="numeric">{formatPrice(candle.open)}</td>
                      <td className="numeric">{formatPrice(candle.high)}</td>
                      <td className="numeric">{formatPrice(candle.low)}</td>
                      <td className="numeric">{formatPrice(candle.close)}</td>
                      <td className="numeric">{formatNumber(candle.volume)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <PageState kind="empty" title="Нет дневных свечей" />
          )}
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
          <h2>Проблемы качества</h2>
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
                  <span className="muted" title="Подозрительный ценовой разрыв">
                    {" "}
                    · Подозрительный ценовой разрыв
                  </span>
                </p>
              ) : null}
              <div className="card-grid" style={{ marginTop: "1rem" }}>
                <MetricCard
                  label="Доходность 1 день"
                  value={
                    hasInsufficientHistory(features.quality_flags, "return_1d")
                      ? "Недостаточно истории"
                      : formatPercent(features.return_1d)
                  }
                />
                <MetricCard
                  label="Доходность 5 дней"
                  value={
                    hasInsufficientHistory(features.quality_flags, "return_5d")
                      ? "Недостаточно истории"
                      : formatPercent(features.return_5d)
                  }
                />
                <MetricCard
                  label="Доходность 20 дней"
                  value={
                    hasInsufficientHistory(features.quality_flags, "return_20d")
                      ? "Недостаточно истории"
                      : formatPercent(features.return_20d)
                  }
                />
                <MetricCard label="Волатильность 5 дней" value={formatPercent(features.volatility_5d)} />
                <MetricCard label="Волатильность 20 дней" value={formatPercent(features.volatility_20d)} />
                <MetricCard label="Просадка 20 дней" value={formatPercent(features.drawdown_20d)} />
                <MetricCard label="Изменение объёма" value={formatPercent(features.volume_change_1d)} />
                <MetricCard label="Z-score объёма 20д" value={formatZScore(features.volume_zscore_20d)} />
              </div>
              {features.return_5d != null ? (
                <>
                  <h2 style={{ marginTop: "1rem" }}>Return 5d (история)</h2>
                  <Sparkline values={closes.slice(-30)} />
                </>
              ) : null}
            </>
          )}
        </article>
      ) : null}
    </section>
  );
}
