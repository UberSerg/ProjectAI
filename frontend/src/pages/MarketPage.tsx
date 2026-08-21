import { type FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  getInstruments,
  runBackfill,
  runDataQuality,
  runMarketUpdate,
  type Instrument,
  type Page,
  type WorkflowAccepted,
} from "../api/market";
import { formatDate, formatNumber, PageState, StatusBadge } from "../components/Ui";

const PAGE_SIZE = 25;

export function MarketPage() {
  const navigate = useNavigate();
  const [result, setResult] = useState<Page<Instrument> | null>(null);
  const [search, setSearch] = useState("");
  const [assetClass, setAssetClass] = useState("");
  const [source, setSource] = useState("");
  const [active, setActive] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [backfillOpen, setBackfillOpen] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionResult, setActionResult] = useState<WorkflowAccepted | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getInstruments(
      {
        search,
        asset_class: assetClass,
        source,
        active: active === "" ? undefined : active === "true",
        page,
        page_size: PAGE_SIZE,
      },
      controller.signal,
    )
      .then(setResult)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(errorMessage(reason));
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [search, assetClass, source, active, page]);

  async function runAction(action: () => Promise<WorkflowAccepted>) {
    setActionBusy(true);
    setActionError(null);
    setActionResult(null);
    try {
      setActionResult(await action());
    } catch (reason) {
      setActionError(errorMessage(reason));
    } finally {
      setActionBusy(false);
    }
  }

  async function submitBackfill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const symbols = String(form.get("instruments") ?? "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    await runAction(() =>
      runBackfill({
        instruments: symbols.length ? symbols : undefined,
        date_from: String(form.get("date_from") ?? "") || undefined,
        date_to: String(form.get("date_to") ?? "") || undefined,
      }),
    );
    setBackfillOpen(false);
  }

  const totalPages = Math.max(1, Math.ceil((result?.total ?? 0) / PAGE_SIZE));

  return (
    <section>
      <div className="page-header">
        <div>
          <h1>Market Data</h1>
          <p className="subtitle">Instruments, coverage and ingestion controls</p>
        </div>
        <div className="button-row">
          <button disabled={actionBusy} onClick={() => void runAction(runMarketUpdate)}>Run Market Update</button>
          <button className="secondary" disabled={actionBusy} onClick={() => setBackfillOpen(true)}>Run Backfill</button>
          <button className="secondary" disabled={actionBusy} onClick={() => void runAction(runDataQuality)}>Run Data Quality</button>
        </div>
      </div>

      {actionResult ? (
        <div className="banner success">Workflow <strong>{actionResult.workflow_id}</strong> accepted: <StatusBadge status={actionResult.status} /></div>
      ) : null}
      {actionError ? <div className="banner error" role="alert">Action failed: {actionError}</div> : null}

      <div className="filters">
        <label>Search<input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Symbol or name" /></label>
        <label>Asset class<input value={assetClass} onChange={(event) => { setAssetClass(event.target.value); setPage(1); }} placeholder="equity, fx…" /></label>
        <label>Source<input value={source} onChange={(event) => { setSource(event.target.value); setPage(1); }} placeholder="Provider" /></label>
        <label>Status<select value={active} onChange={(event) => { setActive(event.target.value); setPage(1); }}><option value="">All</option><option value="true">Active</option><option value="false">Inactive</option></select></label>
      </div>

      {loading ? <PageState kind="loading">Loading instruments…</PageState> : null}
      {error ? <PageState kind="error">Unable to load market data: {error}</PageState> : null}
      {!loading && !error && result?.items.length === 0 ? <PageState kind="empty">No instruments match the current filters.</PageState> : null}
      {!loading && !error && result && result.items.length > 0 ? (
        <>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Symbol</th><th>Name</th><th>Asset Class</th><th>Exchange</th><th>Currency</th><th>Source</th><th>First Data</th><th>Last Data</th><th>Records</th><th>Status</th></tr></thead>
              <tbody>
                {result.items.map((instrument) => (
                  <tr key={instrument.id} className="clickable" onClick={() => navigate(`/market/${instrument.id}`)}>
                    <td><strong>{instrument.symbol}</strong></td><td>{instrument.name}</td><td>{instrument.asset_class}</td><td>{instrument.exchange ?? "—"}</td><td>{instrument.currency}</td><td>{instrument.sources.join(", ") || "—"}</td><td>{formatDate(instrument.first_timestamp)}</td><td>{formatDate(instrument.last_timestamp)}</td><td className="numeric">{formatNumber(instrument.records_count)}</td><td><StatusBadge status={instrument.is_active ? "active" : "inactive"} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <span>{formatNumber(result.total)} instruments</span>
            <button className="secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Previous</button>
            <span>Page {page} of {totalPages}</span>
            <button className="secondary" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>Next</button>
          </div>
        </>
      ) : null}

      {backfillOpen ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setBackfillOpen(false)}>
          <div className="modal" role="dialog" aria-modal="true" aria-labelledby="backfill-title" onMouseDown={(event) => event.stopPropagation()}>
            <h2 id="backfill-title">Run Backfill</h2>
            <p className="subtitle">Leave instruments empty to use the default universe.</p>
            <form onSubmit={(event) => void submitBackfill(event)}>
              <label>Instruments<input name="instruments" placeholder="AAPL, MSFT, EURUSD" /></label>
              <div className="form-row"><label>Date from<input name="date_from" type="date" /></label><label>Date to<input name="date_to" type="date" /></label></div>
              <div className="button-row"><button type="submit" disabled={actionBusy}>Start Backfill</button><button type="button" className="secondary" onClick={() => setBackfillOpen(false)}>Cancel</button></div>
            </form>
          </div>
        </div>
      ) : null}
    </section>
  );
}
