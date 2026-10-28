import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim() !== "");
}

function scalarLabel(value: unknown): string | null {
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (typeof value === "string" && value.trim()) return value.trim();
  if (!isRecord(value)) return null;
  const inner = value.value;
  if (typeof inner === "number" || typeof inner === "boolean") return String(inner);
  if (typeof inner === "string" && inner.trim()) return inner.trim();
  return null;
}

function modelNotes(signal: { abstain_reason?: string | null; limitations?: string[] }): string {
  const parts = [signal.abstain_reason, ...(signal.limitations ?? [])].filter(
    (item): item is string => Boolean(item && item.trim()),
  );
  return parts.length > 0 ? parts.join("; ") : "нет";
}

function TextList({
  items,
  empty,
  testId,
}: {
  items?: string[] | null;
  empty: string;
  testId?: string;
}) {
  const rows = listOrEmpty(items);
  if (rows.length === 0) {
    return (
      <p data-testid={testId}>
        <SignalStateBadge state="UNKNOWN" /> {empty}
      </p>
    );
  }
  return (
    <ul data-testid={testId}>
      {rows.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function MetricList({ rows }: { rows: { key: string; value: string }[] }) {
  if (rows.length === 0) return null;
  return (
    <dl className="intel-dl">
      {rows.map((row) => (
        <div key={row.key}>
          <dt>{row.key}</dt>
          <dd>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function industrialMetricRows(metrics: Record<string, unknown>): { key: string; value: string }[] {
  const rows: { key: string; value: string }[] = [];
  const facts = isRecord(metrics.facts) ? metrics.facts : null;
  if (facts) {
    for (const [code, raw] of Object.entries(facts)) {
      const label = scalarLabel(isRecord(raw) ? raw.value : raw);
      if (label == null) continue;
      const currency =
        isRecord(raw) && typeof raw.currency === "string" && raw.currency ? ` ${raw.currency}` : "";
      rows.push({ key: code, value: `${label}${currency}` });
    }
  }
  const derived = isRecord(metrics.derived) ? metrics.derived : null;
  if (derived) {
    for (const [code, raw] of Object.entries(derived)) {
      const label = scalarLabel(raw);
      if (label == null) continue;
      rows.push({ key: code, value: label });
    }
  }
  return rows;
}

const NESTED_METRIC_KEYS = new Set(["facts", "derived", "freshness", "history", "flags", "semantics"]);

function flatMetricRows(metrics: Record<string, unknown>): { key: string; value: string }[] {
  const rows: { key: string; value: string }[] = [];
  for (const [code, raw] of Object.entries(metrics)) {
    if (NESTED_METRIC_KEYS.has(code)) continue;
    const label = scalarLabel(raw);
    if (label == null) continue;
    rows.push({ key: code, value: label });
  }
  return rows;
}

function eventRole(event: Record<string, unknown>): string {
  return typeof event.evidence_role === "string" ? event.evidence_role : "";
}

function eventDirectionState(event: Record<string, unknown>): string | null {
  if (eventRole(event) === "unscored_news") return null;
  if (typeof event.direction !== "string") return null;
  const text = event.direction.trim().toUpperCase();
  return text || null;
}

function roleLabel(role: string): string {
  if (role === "extracted_event") return "извлечённое событие";
  if (role === "unscored_news") return "новость без оценки";
  return role || "роль не указана";
}

export function CompanyIntelligencePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [instrumentIdInput, setInstrumentIdInput] = useState(searchParams.get("instrument_id") ?? "");
  const [asOfInput, setAsOfInput] = useState(searchParams.get("as_of") ?? "");
  const [snapshot, setSnapshot] = useState<IntelligenceSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  const returnPortfolioRaw = searchParams.get("portfolio_id");
  const returnPortfolioId = (() => {
    if (!returnPortfolioRaw) return null;
    const n = Number(returnPortfolioRaw);
    return Number.isFinite(n) && n > 0 ? n : null;
  })();
  const returnTab = searchParams.get("return_tab") === "decision" ? "decision" : "holdings";
  const backToPortfolioHref =
    returnPortfolioId != null
      ? `/portfolio/${returnPortfolioId}?tab=${returnTab}`
      : null;

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
    // Preserve return path to the previously selected portfolio.
    if (returnPortfolioId != null) next.set("portfolio_id", String(returnPortfolioId));
    if (searchParams.get("return_tab")) next.set("return_tab", searchParams.get("return_tab")!);
    setSearchParams(next);
  }

  async function onRefresh() {
    if (!snapshot || busy) return;
    const effectiveAsOf = searchParams.get("as_of")?.trim() || snapshot.as_of?.trim() || undefined;
    const instrumentId = snapshot.instrument_id;
    setBusy(true);
    setRefreshFailed(false);
    setRefreshNote("Обновление данных…");
    try {
      const result = await refreshIntelligence(instrumentId, {
        as_of: effectiveAsOf,
        force: true,
      });
      const next = await getIntelligenceSnapshot(instrumentId, effectiveAsOf);
      setSnapshot(next);
      setRefreshNote(result.message?.trim() || result.status || "Данные обновлены");
    } catch (reason: unknown) {
      setRefreshFailed(true);
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
        description="Сводка независимых аналитических моделей по инструменту. Advisory / research only — без ордеров, без Daily Decision / Candidate / Policy / Shadow и без брокера."
      />

      {backToPortfolioHref ? (
        <p data-testid="intel-back-to-portfolio">
          <Link to={backToPortfolioHref} className="btn secondary">
            ← Вернуться к портфелю №{returnPortfolioId}
          </Link>
        </p>
      ) : null}

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
        <button
          type="button"
          className="secondary"
          disabled={!snapshot || busy}
          onClick={() => void onRefresh()}
          data-testid="intel-refresh"
        >
          Обновить данные
        </button>
      </form>

      {refreshNote ? (
        <div
          className={refreshFailed ? "banner banner-warning" : "banner banner-info"}
          data-testid="intel-refresh-note"
          role={refreshFailed ? "alert" : "status"}
        >
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
                <dl className="intel-dl">
                  <div>
                    <dt>Confidence</dt>
                    <dd data-testid="intel-committee-confidence">
                      {committee.confidence == null ? "не задана" : String(committee.confidence)}
                    </dd>
                  </div>
                  <div>
                    <dt>Семантика confidence</dt>
                    <dd data-testid="intel-committee-confidence-semantic">
                      {committee.confidence_semantic?.trim() || "не задана"}
                    </dd>
                  </div>
                  <div>
                    <dt>Consensus</dt>
                    <dd>
                      {committee.consensus_strength == null ? "не рассчитано" : String(committee.consensus_strength)}
                    </dd>
                  </div>
                  <div>
                    <dt>Disagreement</dt>
                    <dd data-testid="intel-disagreement">
                      {committee.disagreement_score == null ? "не рассчитано" : String(committee.disagreement_score)}
                    </dd>
                  </div>
                </dl>
                <h3>Primary drivers</h3>
                <TextList
                  items={committee.primary_drivers}
                  empty="Драйверы не зафиксированы"
                  testId="intel-primary-drivers"
                />
                <h3>Counterarguments</h3>
                <TextList
                  items={committee.counterarguments}
                  empty="Контраргументы не зафиксированы"
                  testId="intel-counterarguments"
                />
                <h3>Blockers</h3>
                <TextList items={committee.blockers} empty="Блокеры не зафиксированы" />
                <h3>Data gaps</h3>
                <TextList
                  items={committee.data_gaps}
                  empty="Пробелы данных не зафиксированы"
                  testId="intel-data-gaps"
                />
              </>
            ) : (
              <p>
                <SignalStateBadge state="UNKNOWN" /> Committee недоступен
              </p>
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
                    <th>Confidence</th>
                    <th>Confidence semantic</th>
                    <th>Limitations</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.signals.length === 0 ? (
                    <tr>
                      <td colSpan={7}>
                        <SignalStateBadge state="UNKNOWN" /> Независимые модели не переданы
                      </td>
                    </tr>
                  ) : (
                    snapshot.signals.map((s) => (
                      <tr key={`${s.model_id}-${s.semantic}`}>
                        <td>
                          {s.model_id} <span className="intel-meta">v{s.model_version}</span>
                        </td>
                        <td>{s.semantic}</td>
                        <td>
                          <SignalStateBadge state={s.state} />
                        </td>
                        <td>{s.score == null ? "нет" : String(s.score)}</td>
                        <td>{s.confidence == null ? "нет" : String(s.confidence)}</td>
                        <td>{s.confidence_semantic?.trim() || "не задана"}</td>
                        <td>{modelNotes(s)}</td>
                      </tr>
                    ))
                  )}
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
                {intradaySignal.confidence_semantic
                  ? ` · confidence semantic ${intradaySignal.confidence_semantic}`
                  : null}
              </p>
            ) : (
              <p>
                <SignalStateBadge state="UNKNOWN" /> Внутридневная модель не передана
              </p>
            )}
            <IntradayFeatures summary={snapshot.intraday_summary} />
          </section>

          <FundamentalsSection summary={snapshot.fundamentals_summary} />

          <EventsSection events={snapshot.recent_events} />

          <MacroSection summary={snapshot.macro_summary} />

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
                <p data-testid="intel-risk-score">
                  Оценка риска: {risk.risk_score == null ? "не задана" : String(risk.risk_score)}
                </p>
                <TextList items={risk.risk_flags} empty="Флаги риска не зафиксированы" />
                <RiskDetails risk={risk} />
                {listOrEmpty(risk.limitations).length > 0 ? (
                  <TextList items={risk.limitations} empty="" />
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
            <h3>Provenance</h3>
            <dl className="intel-dl" data-testid="intel-provenance">
              <div>
                <dt>Fundamentals provider</dt>
                <dd>
                  {typeof snapshot.fundamentals_summary.provider === "string" &&
                  snapshot.fundamentals_summary.provider
                    ? snapshot.fundamentals_summary.provider
                    : "не указан"}
                </dd>
              </div>
              <div>
                <dt>Macro sources</dt>
                <dd>
                  {stringList(snapshot.macro_summary.sources).length > 0
                    ? stringList(snapshot.macro_summary.sources).join(", ")
                    : "не указаны"}
                </dd>
              </div>
              <div>
                <dt>Isolation</dt>
                <dd>
                  persist_registry={String(snapshot.production_isolation.persist_registry)} · broker_execution=
                  {String(snapshot.production_isolation.broker_execution)}
                </dd>
              </div>
            </dl>
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

function IntradayFeatures({ summary }: { summary: Record<string, unknown> }) {
  const features = isRecord(summary.features) ? summary.features : {};
  const rows = Object.entries(features)
    .map(([key, value]) => {
      const label = scalarLabel(value);
      return label == null ? null : { key, value: label };
    })
    .filter((row): row is { key: string; value: string } => row !== null);
  if (rows.length === 0) {
    return (
      <p>
        <SignalStateBadge state="UNKNOWN" /> Внутридневные признаки не рассчитаны
      </p>
    );
  }
  return <MetricList rows={rows} />;
}

function FundamentalsSection({ summary }: { summary: Record<string, unknown> }) {
  const kind = String(summary.issuer_kind ?? "UNKNOWN").toUpperCase();
  const bank = kind === "BANK_FI" || kind === "BANK" || kind === "FI";
  const industrial = kind === "INDUSTRIAL";
  const title = bank ? "Bank fundamentals" : industrial ? "Industrial fundamentals" : "Fundamentals";
  const metrics = isRecord(summary.metrics) ? summary.metrics : {};
  const rows = industrial ? industrialMetricRows(metrics) : flatMetricRows(metrics);
  const missing = stringList(summary.missing_metrics);
  const limitations = stringList(summary.limitations);
  return (
    <section className="panel intel-section" data-testid="intel-fundamentals">
      <h2>{title}</h2>
      <p>
        Status: <SignalStateBadge state={asText(summary.status)} /> · issuer kind {asText(summary.issuer_kind)}
      </p>
      <p className="intel-meta">period_end {asText(summary.period_end)}</p>
      {bank && rows.length === 0 ? (
        <p>
          <SignalStateBadge state="UNKNOWN" /> Банковские метрики не поступили
        </p>
      ) : null}
      {industrial && rows.length === 0 ? (
        <p>
          <SignalStateBadge state="UNKNOWN" /> Промышленные метрики не поступили
        </p>
      ) : null}
      {!bank && !industrial ? (
        <p>
          <SignalStateBadge state="UNKNOWN" /> Тип эмитента не определён — банковские и промышленные метрики не
          подставлены
        </p>
      ) : null}
      <MetricList rows={rows} />
      {missing.length > 0 ? (
        <div>
          <h3>Missing metrics</h3>
          <ul>
            {missing.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {limitations.length > 0 ? (
        <div>
          <h3>Limitations</h3>
          <ul>
            {limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function EventsSection({ events }: { events: Record<string, unknown>[] }) {
  return (
    <section className="panel intel-section" data-testid="intel-events">
      <h2>News / events</h2>
      <p className="intel-meta">
        Направление извлечённого события сохранено как есть и не является уверенностью модели. UNKNOWN и ABSTAIN не
        приравниваются к NEUTRAL. Новость без извлечённого события остаётся без направления.
      </p>
      {events.length === 0 ? (
        <p>
          <SignalStateBadge state="UNKNOWN" /> События ещё не интегрированы
        </p>
      ) : (
        <div className="table-wrap">
          <table data-testid="intel-event-list">
            <thead>
              <tr>
                <th>Role</th>
                <th>Type</th>
                <th>Materiality</th>
                <th>Direction</th>
                <th>Published</th>
                <th>Known at</th>
                <th>Provider</th>
                <th>Title</th>
                <th>Source</th>
                <th>Mapping</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev, idx) => {
                const role = eventRole(ev);
                const direction = eventDirectionState(ev);
                const materiality =
                  typeof ev.materiality === "string" && ev.materiality.trim()
                    ? ev.materiality.trim().toUpperCase()
                    : null;
                return (
                  <tr
                    key={`${asText(ev.id)}-${asText(ev.source_document_id)}-${idx}`}
                    data-testid={`intel-event-${idx}`}
                    data-evidence-role={role || undefined}
                  >
                    <td>{roleLabel(role)}</td>
                    <td>{asText(ev.event_type)}</td>
                    <td data-testid={`intel-event-materiality-${idx}`}>
                      {materiality == null ? (
                        "нет"
                      ) : materiality === "UNKNOWN" || materiality === "ABSTAIN" ? (
                        <SignalStateBadge state={materiality} />
                      ) : (
                        materiality
                      )}
                    </td>
                    <td>
                      {direction == null ? (
                        <span data-testid={`intel-event-direction-${idx}`} data-state="UNSCORED">
                          не оценено
                        </span>
                      ) : (
                        <SignalStateBadge state={direction} testId={`intel-event-direction-${idx}`} />
                      )}
                    </td>
                    <td>{formatDateTime(typeof ev.published_at === "string" ? ev.published_at : null)}</td>
                    <td>{formatDateTime(typeof ev.known_at === "string" ? ev.known_at : null)}</td>
                    <td>{asText(ev.provider)}</td>
                    <td>{asText(ev.title)}</td>
                    <td>{asText(ev.source_document_id)}</td>
                    <td>{typeof ev.mapping_basis === "string" && ev.mapping_basis ? ev.mapping_basis : "не указано"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function MacroSection({ summary }: { summary: Record<string, unknown> }) {
  const regimes = isRecord(summary.regimes) ? summary.regimes : {};
  const regimeRows = Object.entries(regimes)
    .map(([key, value]) => {
      const label = scalarLabel(value);
      return label == null ? null : { key, value: label };
    })
    .filter((row): row is { key: string; value: string } => row !== null);
  const observations = isRecord(summary.observations) ? summary.observations : {};
  const observationRows = Object.entries(observations)
    .map(([key, value]) => {
      const label = scalarLabel(value);
      return label == null ? null : { key, value: label };
    })
    .filter((row): row is { key: string; value: string } => row !== null);
  return (
    <section className="panel intel-section" data-testid="intel-macro">
      <h2>Macro / regime</h2>
      <p>
        Status: <SignalStateBadge state={asText(summary.status)} />
      </p>
      {regimeRows.length === 0 ? (
        <p>
          <SignalStateBadge state="UNKNOWN" /> Режим не определён
        </p>
      ) : (
        <MetricList rows={regimeRows} />
      )}
      {observationRows.length === 0 ? (
        <p>
          <SignalStateBadge state="UNKNOWN" /> Макронаблюдения не заданы
        </p>
      ) : (
        <MetricList rows={observationRows} />
      )}
      {stringList(summary.limitations).length > 0 ? (
        <TextList items={stringList(summary.limitations)} empty="" />
      ) : null}
    </section>
  );
}

function RiskDetails({
  risk,
}: {
  risk: {
    liquidity_state?: string | null;
    volatility_state?: string | null;
    event_risk?: string | null;
    data_risk?: string | null;
    concentration_risk?: string | null;
  };
}) {
  const rows = [
    ["Liquidity", risk.liquidity_state],
    ["Volatility", risk.volatility_state],
    ["Event risk", risk.event_risk],
    ["Data risk", risk.data_risk],
    ["Concentration", risk.concentration_risk],
  ].filter((row): row is [string, string] => typeof row[1] === "string" && row[1].trim() !== "");
  if (rows.length === 0) {
    return (
      <p>
        <SignalStateBadge state="UNKNOWN" /> Дополнительные риск-состояния не заданы
      </p>
    );
  }
  return (
    <ul>
      {rows.map(([label, value]) => (
        <li key={label}>
          {label}: <SignalStateBadge state={value} />
        </li>
      ))}
    </ul>
  );
}
