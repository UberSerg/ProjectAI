import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
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
import { formatDate, formatNumber, PageState, StatusBadge } from "../components/Ui";

interface InstrumentData {
  instrument: Instrument;
  candles: Candle[];
  batches: Batch[];
  issues: DataQualityIssue[];
}

export function InstrumentPage() {
  const { instrumentId = "" } = useParams();
  const [data, setData] = useState<InstrumentData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getInstrument(instrumentId, controller.signal),
      getCandles(instrumentId, 30, controller.signal),
      getBatches(instrumentId, controller.signal),
      getDataQualityIssues(instrumentId, controller.signal),
    ])
      .then(([instrument, candles, batches, issues]) => setData({ instrument, candles, batches, issues }))
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(errorMessage(reason));
      });
    return () => controller.abort();
  }, [instrumentId]);

  if (error) return <PageState kind="error">Unable to load instrument: {error}</PageState>;
  if (!data) return <PageState kind="loading">Loading instrument…</PageState>;

  const { instrument, candles, batches, issues } = data;
  const low = candles.length ? Math.min(...candles.map((candle) => candle.low)) : null;
  const high = candles.length ? Math.max(...candles.map((candle) => candle.high)) : null;

  return (
    <section>
      <Link className="back-link" to="/market">← Market Data</Link>
      <div className="page-header">
        <div><h1>{instrument.symbol}</h1><p className="subtitle">{instrument.name}</p></div>
        <StatusBadge status={instrument.is_active ? "active" : "inactive"} />
      </div>

      <div className="card-grid">
        <article className="metric-card"><span className="metric-label">Asset</span><strong>{instrument.asset_class}</strong><small>{instrument.exchange ?? "No exchange"} · {instrument.currency}</small></article>
        <article className="metric-card"><span className="metric-label">Coverage</span><strong>{formatNumber(instrument.records_count)} records</strong><small>{formatDate(instrument.first_timestamp)} — {formatDate(instrument.last_timestamp)}</small></article>
        <article className="metric-card"><span className="metric-label">30-day range</span><strong>{low == null ? "—" : `${low} — ${high}`}</strong><small>{candles.length} daily candles returned</small></article>
      </div>

      <div className="detail-grid">
        <article className="panel">
          <h2>Source mappings</h2>
          {instrument.mappings?.length ? instrument.mappings.map((mapping) => <div className="key-value" key={`${mapping.source}-${mapping.source_symbol}`}><span>{mapping.source}</span><strong>{mapping.source_symbol}</strong></div>) : <p className="muted">{instrument.sources.join(", ") || "No mappings available."}</p>}
        </article>
        <article className="panel">
          <h2>Data quality issues</h2>
          {issues.length ? issues.map((issue) => <div className="issue" key={issue.id}><StatusBadge status={issue.severity} /><div><strong>{issue.issue_type}</strong><p>{issue.message}</p><small>{formatDate(issue.detected_at)}</small></div></div>) : <p className="muted">No unresolved issues.</p>}
        </article>
      </div>

      <h2>Last 30 daily candles</h2>
      {candles.length ? <div className="table-wrap"><table><thead><tr><th>Date</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th><th>Source</th></tr></thead><tbody>{candles.map((candle) => <tr key={`${candle.timestamp}-${candle.source ?? ""}`}><td>{formatDate(candle.timestamp)}</td><td className="numeric">{candle.open}</td><td className="numeric">{candle.high}</td><td className="numeric">{candle.low}</td><td className="numeric">{candle.close}</td><td className="numeric">{formatNumber(candle.volume)}</td><td>{candle.source ?? "—"}</td></tr>)}</tbody></table></div> : <PageState kind="empty">No daily candles available.</PageState>}

      <h2>Recent batches</h2>
      {batches.length ? <div className="table-wrap"><table><thead><tr><th>ID</th><th>Source</th><th>Status</th><th>Started</th><th>Finished</th><th>Received</th><th>Written</th></tr></thead><tbody>{batches.map((batch) => <tr key={batch.id}><td className="mono">{batch.id}</td><td>{batch.source}</td><td><StatusBadge status={batch.status} /></td><td>{formatDate(batch.started_at)}</td><td>{formatDate(batch.finished_at)}</td><td className="numeric">{formatNumber(batch.records_received)}</td><td className="numeric">{formatNumber(batch.records_written)}</td></tr>)}</tbody></table></div> : <PageState kind="empty">No recent batches.</PageState>}
    </section>
  );
}
