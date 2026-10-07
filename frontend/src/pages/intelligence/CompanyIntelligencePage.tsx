import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { errorMessage } from "../../api/client";
import {
  getIntelligenceSnapshot,
  refreshIntelligence,
  type IntelligenceSnapshot,
} from "../../api/intelligence";
import { PageHeader, PageState } from "../../components/Ui";
import { formatDate, formatDateTime } from "../../utils/format";
import { labels } from "../../utils/labels";
import { SignalStateBadge } from "./SignalStateBadge";

function asText(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "—";
}

function listOrEmpty(items?: string[] | null): string[] {
  return items?.filter(Boolean) ?? [];
}

export function CompanyIntelligencePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [instrumentIdInput, setInstrumentIdInput] = useState(searchParams.get("instrument_id") ?? "");
  const [asOfInput, setAsOfInput] = useState(searchParams.get("as_of") ?? "");
  const [snapshot, setSnapshot] = useState<IntelligenceSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (instrumentId: number, asOf?: string, signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const data = await getIntelligenceSnapshot(instrumentId, asOf || undefined, signal);
        setSnapshot(data);
      } catch (reason: unknown) {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
          setSnapshot(null);
        }
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    const raw = searchParams.get("instrument_id");
    if (!raw) return;
    const id = Number(raw);
    if (!Number.isFinite(id) || id <= 0) return;
    const controller = new AbortController();
    void load(id, searchParams.get("as_of") ?? undefined, controller.signal);
    return () => controller.abort();
  }, [searchParams, load]);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const id = Number(instrumentIdInput.trim());
    if (!Number.isFinite(id) || id <= 0) {
      setError("Укажите корректный instrument_id");
      return;
    }
    const next = new URLSearchParams();
    next.set("instrument_id", String(id));
    if (asOfInput.trim()) next.set("as_of", asOfInput.trim());
    setSearchParams(next);
  }

  async function onRefresh() {
    if (!snapshot) return;
    setBusy(true);
    setRefreshNote(null);
    try {
      const result = await refreshIntelligence(snapshot.instrument_id, {
        as_of: asOfInput.trim() || undefined,
      });
      setRefreshNote(result.message ?? result.status);
    } catch (reason: unknown) {
      setRefreshNote(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  const committee = snapshot?.committee;
  const risk = snapshot?.risk;
  const technicalSignal = snapshot?.signals.find((s) => s.semantic === "TECHNICAL");
  const intradaySignal = snapshot?.signals.find((s) => s.semantic === "INTRADAY");

  return (
    <section className="intel-page" data-testid="company-intelligence-page">
      <PageHeader
        title={labels.nav.companyIntelligence}
        description="Сводка независимых аналитических моделей по инструменту. Advisory / research only — без ордеров и без production Candidate."
      />

      <form className="intel-lookup filters" onSubmit={onSubmit} data-testid="intel-lookup-form">
        <label>
          Instrument ID
          <input
            value={instrumentIdInput}
            onChange={(e) => setInstrumentIdInput(e.target.value)}
            placeholder="например 1"
            data-testid="intel-instrument-id"
          />
        </label>
        <label>
          as_of
          <input
            type="date"
            value={asOfInput}
            onChange={(e) => setAsOfInput(e.target.value)}
            data-testid="intel-as-of"
          />
        </label>
        <button type="submit" className="btn btn-primary" disabled={loading}>
          Загрузить
        </button>
        <button type="button" className="secondary" disabled={!snapshot || busy} onClick={() => void onRefresh()}>
          Refresh (stub)
        </button>
      </form>

      {refreshNote ? (
        <div className="banner banner-warning" data-testid="intel-refresh-note">
          {refreshNote}
        </div>
      ) : null}
      {error ? (
        <div className="banner banner-warning" data-testid="intel-error">
          {error}
        </div>
      ) : null}

      {loading && !snapshot ? <PageState kind="loading" title="Загрузка company intelligence…" /> : null}

      {!loading && !snapshot && !error ? (
        <PageState kind="empty" title="Укажите instrument_id, чтобы открыть сводку" />
      ) : null}

      {snapshot ? (
        <div className="intel-sections">
          <section className="panel intel-section" data-testid="intel-identity">
            <h2>Identity / as_of</h2>
            <dl className="intel-dl">
              <div>
                <dt>Symbol</dt>
                <dd>{snapshot.symbol ?? "—"}</dd>
              </div>
              <div>
                <dt>Name</dt>
                <dd>{snapshot.name ?? "—"}</dd>
              </div>
              <div>
                <dt>Instrument ID</dt>
                <dd>{snapshot.instrument_id}</dd>
              </div>
              <div>
                <dt>as_of</dt>
                <dd>{formatDate(snapshot.as_of)}</dd>
              </div>
              <div>
                <dt>generated_at</dt>
                <dd>{formatDateTime(snapshot.generated_at)}</dd>
              </div>
              <div>
                <dt>Freshness</dt>
                <dd>{snapshot.freshness ?? "—"}</dd>
              </div>
            </dl>
          </section>

          <section className="panel intel-section" data-testid="intel-committee">
            <h2>Committee</h2>
            {committee ? (
              <>
                <p className="intel-lead">
                  Advisory: <SignalStateBadge state={committee.advisory_state} testId="intel-advisory-state" />
                  <span className="intel-meta"> policy {committee.committee_policy_version ?? "—"}</span>
                </p>
                <ul className="intel-kv">
                  <li>
                    Consensus: {committee.consensus_strength ?? "—"} · Disagreement:{" "}
                    {committee.disagreement_score ?? "—"}
                  </li>
                </ul>
                {listOrEmpty(committee.blockers).length > 0 ? (
                  <div>
                    <h3>Blockers</h3>
                    <ul>
                      {committee.blockers!.map((b) => (
                        <li key={b}>{b}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {listOrEmpty(committee.data_gaps).length > 0 ? (
                  <div>
                    <h3>Data gaps</h3>
                    <ul>
                      {committee.data_gaps!.map((g) => (
                        <li key={g}>{g}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </>
            ) : (
              <p>Committee недоступен</p>
            )}
          </section>

          <section className="panel intel-section" data-testid="intel-models">
            <h2>Independent models</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Semantic</th>
                    <th>State</th>
                    <th>Score</th>
                    <th>Reason / limitations</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.signals.map((s) => (
                    <tr key={`${s.model_id}-${s.semantic}`}>
                      <td>
                        {s.model_id} <span className="intel-meta">v{s.model_version}</span>
                      </td>
                      <td>{s.semantic}</td>
                      <td>
                        <SignalStateBadge state={s.state} />
                      </td>
                      <td>{s.score ?? "—"}</td>
                      <td>{s.abstain_reason ?? s.limitations?.[0] ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel intel-section" data-testid="intel-technical">
            <h2>Technical</h2>
            {technicalSignal ? (
              <p>
                <SignalStateBadge state={technicalSignal.state} /> {technicalSignal.model_id} · horizon{" "}
                {technicalSignal.horizon}
              </p>
            ) : (
              <p>
                <SignalStateBadge state="UNKNOWN" /> Нет технического сигнала
              </p>
            )}
          </section>

          <section className="panel intel-section" data-testid="intel-intraday">
            <h2>Intraday</h2>
            <p>
              Coverage:{" "}
              <SignalStateBadge state={asText(snapshot.intraday_summary.coverage_status)} /> · interval{" "}
              {asText(snapshot.intraday_summary.interval)} · bars {asText(snapshot.intraday_summary.bars_used)}
            </p>
            {intradaySignal ? (
              <p>
                Model state: <SignalStateBadge state={intradaySignal.state} />
              </p>
            ) : null}
          </section>

          <section className="panel intel-section" data-testid="intel-fundamentals">
            <h2>Fundamentals</h2>
            <p>
              Status: <SignalStateBadge state={asText(snapshot.fundamentals_summary.status)} /> · issuer kind{" "}
              {asText(snapshot.fundamentals_summary.issuer_kind)}
            </p>
            <p className="intel-meta">period_end {asText(snapshot.fundamentals_summary.period_end)}</p>
          </section>

          <section className="panel intel-section" data-testid="intel-events">
            <h2>News / events</h2>
            {snapshot.recent_events.length === 0 ? (
              <p>
                <SignalStateBadge state="UNKNOWN" /> События ещё не интегрированы
              </p>
            ) : (
              <ul>
                {snapshot.recent_events.slice(0, 8).map((ev, idx) => (
                  <li key={idx}>{asText(ev.title ?? ev.event_type ?? ev.id)}</li>
                ))}
              </ul>
            )}
          </section>

          <section className="panel intel-section" data-testid="intel-macro">
            <h2>Macro</h2>
            <p>
              Status: <SignalStateBadge state={asText(snapshot.macro_summary.status)} />
            </p>
          </section>

          <section className="panel intel-section" data-testid="intel-knowledge">
            <h2>Knowledge rules</h2>
            {snapshot.knowledge_evaluations.length === 0 ? (
              <p>
                <SignalStateBadge state="UNKNOWN" /> Оценок правил пока нет
              </p>
            ) : (
              <ul>
                {snapshot.knowledge_evaluations.map((row, idx) => (
                  <li key={idx}>
                    {asText(row.rule_id)} · <SignalStateBadge state={asText(row.state)} /> · {asText(row.why)}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="panel intel-section" data-testid="intel-risk">
            <h2>Risk</h2>
            {risk ? (
              <>
                <p>
                  State: <SignalStateBadge state={risk.risk_state} testId="intel-risk-state" />
                </p>
                {listOrEmpty(risk.risk_flags).length > 0 ? (
                  <ul>
                    {risk.risk_flags!.map((f) => (
                      <li key={f}>{f}</li>
                    ))}
                  </ul>
                ) : null}
              </>
            ) : (
              <p>
                <SignalStateBadge state="UNKNOWN" /> Risk assessment отсутствует
              </p>
            )}
          </section>

          <section className="panel intel-section" data-testid="intel-coverage">
            <h2>Coverage / provenance</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Domain</th>
                    <th>Status</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.coverage.map((c) => (
                    <tr key={c.domain}>
                      <td>{c.domain}</td>
                      <td>
                        <SignalStateBadge state={c.status} />
                      </td>
                      <td>{c.detail ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="intel-meta">
              Isolation: persist_registry=
              {String(snapshot.production_isolation.persist_registry)} · broker_execution=
              {String(snapshot.production_isolation.broker_execution)}
            </p>
            {snapshot.limitations.length > 0 ? (
              <ul>
                {snapshot.limitations.map((lim) => (
                  <li key={lim}>{lim}</li>
                ))}
              </ul>
            ) : null}
          </section>

          <section className="panel intel-section" data-testid="intel-what-would-change">
            <h2>What would change decision</h2>
            {listOrEmpty(committee?.what_would_change_decision).length > 0 ? (
              <ul>
                {committee!.what_would_change_decision!.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p>Нет зафиксированных условий смены advisory-состояния</p>
            )}
          </section>
        </div>
      ) : null}
    </section>
  );
}
