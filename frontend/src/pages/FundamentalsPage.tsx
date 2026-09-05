import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  getFundamentalsCoverage,
  getFundamentalsMlReadiness,
  getFundamentalsQuality,
  getFundamentalsSummary,
  issuerDisplayName,
  listFundamentalIssuers,
  qualityHumanMessage,
  type FundamentalIssuer,
  type FundamentalsCoverageYear,
  type FundamentalsMlReadiness,
  type FundamentalsQuality,
  type FundamentalsSummary,
} from "../api/fundamentals";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { MetricHelp } from "../help";
import { formatDate, formatDateTime, formatNumber } from "../utils/format";

function coverageCount(row: FundamentalsCoverageYear): number {
  return Number(row.issuers_with_fundamentals ?? row.issuers ?? row.count ?? 0) || 0;
}

function softLoad<T>(promise: Promise<T>, fallback: T): Promise<{ value: T; error?: string }> {
  return promise
    .then((value) => ({ value }))
    .catch((reason: unknown) => {
      if (reason instanceof DOMException && reason.name === "AbortError") throw reason;
      return { value: fallback, error: errorMessage(reason) };
    });
}

function readinessLabel(status?: string | null): string {
  const raw = (status ?? "").toUpperCase();
  if (raw === "READY") return "Готово";
  if (raw === "PARTIAL") return "Частично";
  if (raw === "NOT_READY" || raw === "DEFERRED") return "Не готово";
  return status?.trim() || "Не готово";
}

export function FundamentalsPage() {
  const [summary, setSummary] = useState<FundamentalsSummary | null>(null);
  const [coverage, setCoverage] = useState<FundamentalsCoverageYear[]>([]);
  const [quality, setQuality] = useState<FundamentalsQuality | null>(null);
  const [ml, setMl] = useState<FundamentalsMlReadiness | null>(null);
  const [issuers, setIssuers] = useState<FundamentalIssuer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [partialNotes, setPartialNotes] = useState<string[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([
      softLoad(getFundamentalsSummary(controller.signal), {} as FundamentalsSummary),
      softLoad(getFundamentalsCoverage(controller.signal), [] as FundamentalsCoverageYear[]),
      softLoad(getFundamentalsQuality(controller.signal), {} as FundamentalsQuality),
      softLoad(getFundamentalsMlReadiness(controller.signal), {} as FundamentalsMlReadiness),
      softLoad(listFundamentalIssuers({ limit: 100 }, controller.signal), {
        items: [] as FundamentalIssuer[],
      }),
    ])
      .then(([sum, cov, qual, ready, iss]) => {
        setSummary(sum.value);
        setCoverage(cov.value);
        setQuality(qual.value);
        setMl(ready.value);
        setIssuers(iss.value.items ?? []);
        const notes = [sum.error, cov.error, qual.error, ready.error, iss.error].filter(
          Boolean,
        ) as string[];
        setPartialNotes(notes);
        const allFailed = notes.length === 5;
        if (allFailed) {
          setError(
            "Контур фундаментальных данных пока недоступен или провайдеры отложены. Пустые значения — ожидаемое состояние.",
          );
        }
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  const peak = useMemo(
    () => Math.max(1, ...coverage.map((row) => coverageCount(row))),
    [coverage],
  );

  const qualityStatus =
    quality?.status ?? quality?.pit_quality ?? summary?.pit_quality ?? summary?.status ?? "NOT_READY";
  const qualityMessage = qualityHumanMessage(
    qualityStatus,
    quality?.human_message ?? quality?.message ?? summary?.human_summary,
  );

  const v2Features = ml?.dataset_v2_features ?? ml?.current_dataset_v2_features ?? 90;
  const fundFeatures = ml?.fundamental_v1_candidate_features ?? null;
  const eventFeatures = ml?.event_v1_candidate_features ?? null;
  const v3Total = ml?.potential_v3_total ?? null;
  const blockers = ml?.main_blockers ?? ml?.blockers ?? [];
  const targets = ml?.target_readiness ?? [];

  if (loading) return <PageState kind="loading" title="Загрузка фундаментальных данных…" />;

  return (
    <div className="fundamentals-page" data-testid="fundamentals-page">
      <PageHeader
        title="Фундаментал и события"
        description="Финансовая отчётность, дивиденды и корпоративные события с учётом того, когда информация стала известна рынку."
        helpPageId="fundamentals"
      />

      <div className="card pit-explanation-card" data-testid="pit-explanation-card">
        <h3>
          Почему важна дата публикации? <MetricHelp metricId="publication_date" />
        </h3>
        <p>
          Отчёт за I квартал относится к марту, но если его опубликовали 15 мая, модель не может
          использовать его 1 апреля.
        </p>
        <p className="muted">
          В ProjectAI решение на дату <code>t</code> опирается только на факты с{" "}
          <MetricHelp metricId="known_at" /> ≤ <code>t</code> (
          <MetricHelp metricId="point_in_time" />
          ).
        </p>
      </div>

      {error ? (
        <div className="banner banner-warning" role="status" data-testid="fundamentals-empty-banner">
          {error}
        </div>
      ) : null}
      {!error && partialNotes.length > 0 ? (
        <div className="banner banner-warning" role="status" data-testid="fundamentals-partial-banner">
          Часть API ответила ошибкой или пусто — показываем доступное. Живые бесплатные ленты
          дивидендов/отчётности MOEX могут быть недоступны (NOT_READY / deferred).
        </div>
      ) : null}

      <div className="card-grid" data-testid="fundamentals-overview-cards">
        <MetricCard
          label="Эмитенты с привязкой"
          value={formatNumber(summary?.issuers_mapped ?? summary?.issuers)}
          helpId="fundamental_data"
        />
        <MetricCard label="Отчёты" value={formatNumber(summary?.reports)} helpId="financial_report" />
        <MetricCard
          label="Финансовые факты"
          value={formatNumber(summary?.financial_facts ?? summary?.facts)}
        />
        <MetricCard
          label="Дивидендные события"
          value={formatNumber(summary?.dividend_events ?? summary?.dividends)}
          helpId="dividend_approval"
        />
        <MetricCard
          label="Корпоративные события"
          value={formatNumber(summary?.corporate_events ?? summary?.events)}
          helpId="corporate_event"
        />
        <MetricCard
          label="Начало покрытия"
          value={formatDate(summary?.coverage_start)}
          helpId="coverage"
        />
        <MetricCard label="Последнее обновление" value={formatDateTime(summary?.latest_update)} />
        <MetricCard
          label="Качество PIT"
          value={<StatusBadge status={String(qualityStatus).toLowerCase()} />}
          helpId="point_in_time"
          hint={qualityMessage}
        />
      </div>

      {(summary?.providers?.length ?? 0) > 0 ? (
        <div className="card">
          <h3>Провайдеры</h3>
          <ul className="plain-list">
            {summary?.providers?.map((p, idx) => (
              <li key={`${p.code ?? p.name ?? idx}`}>
                <strong>{p.name ?? p.code ?? "Источник"}</strong>: {p.status ?? "—"}
                {p.note ? <span className="muted"> — {p.note}</span> : null}
                {p.deferred ? <span className="muted"> (отложен)</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="card" data-testid="fundamentals-coverage">
        <h3>
          Покрытие по годам <MetricHelp metricId="coverage" />
        </h3>
        {coverage.length === 0 ? (
          <p className="muted" data-testid="fundamentals-coverage-empty">
            Нет данных о покрытии эмитентов по годам. Это ожидаемо, пока отчётность не загружена из
            доверенного источника.
          </p>
        ) : (
          <div className="coverage-bars" aria-label="Эмитенты с usable fundamentals по годам">
            {coverage.map((row) => {
              const count = coverageCount(row);
              return (
                <div key={row.year} className="coverage-bar-row" title={`${row.year}: ${count}`}>
                  <span className="coverage-year">{row.year}</span>
                  <div className="coverage-track">
                    <div className="coverage-fill" style={{ width: `${(100 * count) / peak}%` }} />
                  </div>
                  <span className="coverage-count">{count}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="card" data-testid="fundamentals-quality">
        <h3>Качество данных</h3>
        <p>{qualityMessage}</p>
        <div className="metric-grid">
          <MetricCard label="Привязки эмитентов" value={formatNumber(quality?.issuer_mappings)} />
          <MetricCard label="Неизвестные привязки" value={formatNumber(quality?.unknown_mappings)} />
          <MetricCard
            label="Отчёты без known_at"
            value={formatNumber(quality?.reports_without_known_at)}
            helpId="known_at"
          />
          <MetricCard label="Неоднозначные факты" value={formatNumber(quality?.ambiguous_facts)} />
          <MetricCard
            label="Пересмотры"
            value={formatNumber(quality?.restatements)}
            helpId="restatement"
          />
          <MetricCard label="Отклонённые строки" value={formatNumber(quality?.rejected_rows)} />
        </div>
      </div>

      <div className="card" data-testid="fundamentals-ml-readiness">
        <h3>
          Готовность к следующей модели <MetricHelp metricId="fundamental_data" />
        </h3>
        <p className="muted">
          Статус: <strong>{readinessLabel(ml?.status ?? qualityStatus)}</strong>. Не утверждаем
          «Candidate V2 ready», пока это не подтверждено данными.
        </p>
        <div className="metric-grid">
          <MetricCard label="Текущий Dataset V2" value={`${formatNumber(v2Features)} признаков`} />
          <MetricCard
            label="Fundamental V1 (кандидаты)"
            value={formatNumber(fundFeatures)}
            helpId="fundamental_data"
          />
          <MetricCard
            label="Event V1 (кандидаты)"
            value={formatNumber(eventFeatures)}
            helpId="corporate_event"
          />
          <MetricCard label="Потенциал V3" value={formatNumber(v3Total)} />
          <MetricCard label="Покрытие" value={ml?.coverage == null ? "—" : String(ml.coverage)} />
          <MetricCard label="PIT-нарушения" value={formatNumber(ml?.pit_violations ?? 0)} />
        </div>
        {blockers.length > 0 ? (
          <div>
            <h4>Основные блокеры</h4>
            <ul className="plain-list">
              {blockers.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="muted">Блокеры не перечислены API — типично при NOT_READY / отсутствии лент.</p>
        )}

        <div className="research-target-block" data-testid="fundamentals-research-targets">
          <h4>Исследовательские цели (без обучения)</h4>
          <p>
            Следующая модель может учиться не просто угадывать доходность акции, а отвечать на более
            полезный вопрос: превысит ли акция денежную альтернативу или попадёт ли она в лучшую
            часть рынка.
          </p>
          <p className="muted">
            Кандидаты меток: абсолютная доходность 20d, excess vs cash 20d, Top20 future rank
            (cross-sectional). Обучение здесь не запускается.
          </p>
          {targets.length > 0 ? (
            <ul className="plain-list">
              {targets.map((t, idx) => (
                <li key={`${t.code ?? t.name ?? idx}`}>
                  <strong>{t.label ?? t.name ?? t.code ?? `Цель ${idx + 1}`}</strong>
                  {t.can_calculate != null ? ` — расчёт: ${String(t.can_calculate)}` : null}
                  {t.pit_concern ? <span className="muted">; PIT: {t.pit_concern}</span> : null}
                  {t.note ? <span className="muted">; {t.note}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">{ml?.research_summary ?? ml?.human_summary ?? null}</p>
          )}
        </div>
      </div>

      <div className="card" data-testid="fundamentals-issuers">
        <h3>Эмитенты</h3>
        {issuers.length === 0 ? (
          <p className="muted" data-testid="fundamentals-issuers-empty">
            Список эмитентов пуст. Identity из MOEX может появиться раньше дивидендов и отчётности —
            до появления строк раздел остаётся пустым честно.
          </p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Эмитент</th>
                  <th>ИНН</th>
                  <th>Ценные бумаги</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {issuers.map((issuer) => {
                  const securities = issuer.securities ?? issuer.mapped_securities ?? [];
                  return (
                    <tr key={String(issuer.id)}>
                      <td>{issuerDisplayName(issuer)}</td>
                      <td>{issuer.inn ?? issuer.emitent_inn ?? "—"}</td>
                      <td>
                        {securities.length
                          ? securities
                              .map((s) => s.ticker ?? s.secid ?? s.isin)
                              .filter(Boolean)
                              .join(", ")
                          : "—"}
                      </td>
                      <td>
                        <Link to={`/fundamentals/${issuer.id}`}>Открыть</Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
