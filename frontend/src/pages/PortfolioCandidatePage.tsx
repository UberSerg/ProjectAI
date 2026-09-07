import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  createPortfolioCandidateSnapshot,
  previewPortfolioCandidate,
  type PortfolioCandidate,
} from "../api/investment";
import {
  AllocationBars,
  DataQualityCard,
  EmptyState,
  ExplanationCard,
  HeroCard,
  MetricCard,
  PageHeader,
  PageState,
  RiskCard,
  StatusBadge,
  WarningCard,
} from "../components/Ui";

function TruncateReason({ text, limit = 140 }: { text: string; limit?: number }) {
  const [open, setOpen] = useState(false);
  if (text.length <= limit) return <>{text}</>;
  return (
    <>
      {open ? text : `${text.slice(0, limit).trimEnd()}…`}{" "}
      <button type="button" className="why-toggle" onClick={() => setOpen((v) => !v)}>
        {open ? "Свернуть" : "Ещё"}
      </button>
    </>
  );
}

function money(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return `${n.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽`;
}

function pct(weight: number | null | undefined): string {
  if (weight == null) return "—";
  return `${(weight * 100).toFixed(0)}%`;
}

function copyComposition(candidate: PortfolioCandidate) {
  const lines = [
    "Research Portfolio Candidate",
    `id=${candidate.candidate_id}`,
    `as_of=${candidate.as_of ?? ""}`,
    `capital=${candidate.capital}`,
    "ticker,instrument,lots,units,price,amount,sleeve,status",
    ...candidate.positions.map(
      (p) =>
        `${p.symbol},${p.display_name},${p.lots},${p.units},${p.reference_price},${p.estimated_notional},${p.sleeve},${p.risk_status}`,
    ),
  ];
  void navigator.clipboard.writeText(lines.join("\n"));
}

export function PortfolioCandidatePage() {
  const [capital, setCapital] = useState(100000);
  const [candidate, setCandidate] = useState<PortfolioCandidate | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [whyOpen, setWhyOpen] = useState(false);
  const [techOpen, setTechOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = (nextCapital = capital, signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    previewPortfolioCandidate({ capital: nextCapital }, signal)
      .then(setCandidate)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(errorMessage(reason));
      })
      .finally(() => {
        if (!signal?.aborted) setLoading(false);
      });
  };

  useEffect(() => {
    const controller = new AbortController();
    load(capital, controller.signal);
    return () => controller.abort();
    // initial mount only — capital changes use explicit «Пересчитать»
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const alloc = candidate?.allocation;
  const exportCsv = useMemo(() => {
    if (!candidate) return "";
    const header = "ticker,instrument,lots,units,price,amount,sleeve,status";
    const rows = candidate.positions.map(
      (p) =>
        `${p.symbol},"${p.display_name}",${p.lots},${p.units},${p.reference_price},${p.estimated_notional},${p.sleeve},${p.risk_status}`,
    );
    return [header, ...rows].join("\n");
  }, [candidate]);

  if (loading && !candidate) {
    return <PageState kind="loading" title="Формируем кандидат портфеля…" />;
  }
  if (error && !candidate) {
    return (
      <PageState
        kind="error"
        title="Не удалось сформировать кандидата"
        action={
          <button type="button" onClick={() => load()}>
            Повторить
          </button>
        }
      >
        {error}
      </PageState>
    );
  }
  if (!candidate) {
    return (
      <EmptyState
        title="Кандидата пока нет"
        reason="Нажмите «Сформировать кандидата портфеля», когда данные будут доступны."
      />
    );
  }

  return (
    <section className="portfolio-candidate-page">
      <PageHeader
        title="Кандидат портфеля Kraken"
        description="Исследовательский портфель на основе текущих данных и правил риска. Не инструкция к покупке."
        helpPageId="portfolio_candidate"
        actions={
          <>
            <button type="button" className="why-toggle" onClick={() => load(capital)}>
              Сформировать кандидата портфеля
            </button>
            <button
              type="button"
              className="why-toggle"
              onClick={() =>
                createPortfolioCandidateSnapshot({ capital })
                  .then(setCandidate)
                  .catch((reason: unknown) => setError(errorMessage(reason)))
              }
            >
              Сохранить snapshot
            </button>
          </>
        }
      />

      {error ? <div className="banner banner-warning">{error}</div> : null}

      <div className="ds-card ds-card-quality" style={{ marginBottom: "1rem" }}>
        <strong>{candidate.readiness.mode_ru}</strong>
        <p className="muted" style={{ margin: "0.35rem 0 0.5rem" }}>
          {candidate.readiness.banner_ru}
        </p>
        <ul className="plain-list">
          {candidate.readiness.reasons_ru.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </div>

      <HeroCard
        eyebrow="Что сделать с капиталом?"
        headline={`${money(candidate.capital)} · статус ${candidate.status}`}
        actions={
          <>
            <button type="button" className="why-toggle" onClick={() => setWhyOpen((v) => !v)}>
              {whyOpen ? "Скрыть «Почему?»" : "Почему?"}
            </button>
            <button
              type="button"
              className="why-toggle"
              onClick={() => {
                copyComposition(candidate);
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? "Скопировано" : "Скопировать состав"}
            </button>
            <a
              className="why-toggle"
              href={`data:text/csv;charset=utf-8,${encodeURIComponent(exportCsv)}`}
              download={`research-portfolio-candidate-${candidate.candidate_id}.csv`}
            >
              Экспорт CSV
            </a>
          </>
        }
      >
        <div className="investment-calculator" style={{ marginBottom: "1rem" }}>
          <label>
            Капитал, ₽{" "}
            <input
              type="number"
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
            />
          </label>
          <button type="button" onClick={() => load(capital)}>
            Пересчитать лоты
          </button>
        </div>
        <p className="muted" style={{ marginTop: 0 }}>
          Данные на {candidate.as_of ?? "—"}. Сформирован {candidate.generated_at}.
          {candidate.freshness?.stale ? ` ${candidate.freshness.stale_note_ru}` : ""}
        </p>
        {alloc ? (
          <>
            <AllocationBars
              equity={alloc.equity.target_weight}
              fixedIncome={alloc.fixed_income.target_weight}
              cash={alloc.cash.target_weight}
            />
            <div className="card-grid">
              <MetricCard
                label="Акции (цель → факт)"
                value={`${pct(alloc.equity.target_weight)} → ${money(alloc.equity.actual_rub)}`}
                helpId="target_allocation"
              />
              <MetricCard
                label="Облигации (цель → факт)"
                value={`${pct(alloc.fixed_income.target_weight)} → ${money(alloc.fixed_income.actual_rub)}`}
                helpId="actual_allocation"
              />
              <MetricCard
                label="Деньги итого"
                value={money(candidate.cash.total_cash_rub)}
                helpId="strategic_cash"
                hint={`Целевой Cash ${money(candidate.cash.strategic_target_rub)}; остаток лотов ${money(candidate.cash.lot_remainder_rub)}`}
              />
            </div>
            <p className="muted">
              Фактическое распределение может отличаться, потому что реальные инструменты покупаются
              целыми лотами.
            </p>
          </>
        ) : null}

        <div className="reveal-panel" hidden={!whyOpen}>
          <ExplanationCard title="Простыми словами" level={1}>
            {candidate.level_explanations?.level_1_ru}
          </ExplanationCard>
          <ExplanationCard title="Подробнее" level={2}>
            {candidate.level_explanations?.level_2_ru}
          </ExplanationCard>
        </div>
      </HeroCard>

      <h2>Что конкретно входит</h2>
      {candidate.positions.length ? (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Инструмент</th>
                  <th>Лотов</th>
                  <th>Сумма</th>
                  <th>Вес</th>
                  <th>Статус</th>
                  <th>Почему</th>
                </tr>
              </thead>
              <tbody>
                {candidate.positions.map((p) => (
                  <tr key={`${p.symbol}-${p.sleeve}`}>
                    <td>
                      <strong>{p.display_name}</strong>
                      <div className="muted">{p.symbol}</div>
                    </td>
                    <td>{p.lots}</td>
                    <td>{money(p.estimated_notional)}</td>
                    <td>{pct(p.actual_weight)}</td>
                    <td>
                      <StatusBadge status={p.risk_status} />
                      {!p.executable ? (
                        <div className="muted">не executable</div>
                      ) : null}
                    </td>
                    <td style={{ maxWidth: "18rem", whiteSpace: "normal" }}>
                      <TruncateReason text={p.reason_ru} />
                      {p.warnings_ru?.length ? (
                        <div className="muted">{p.warnings_ru[0]}</div>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <EmptyState
          title="Нет рыночных позиций"
          reason={
            candidate.empty_states?.all_cash_ru ||
            "Kraken оставил капитал в Cash — это нормальное решение, не ошибка."
          }
        />
      )}

      <h2>Почему так</h2>
      <div className="card-grid">
        {(candidate.reasons_ru.length ? candidate.reasons_ru : ["Смотрите Risk Gate и confidence."])
          .slice(0, 5)
          .map((reason) => (
            <ExplanationCard key={reason.slice(0, 48)} title="Причина" level={1}>
              <TruncateReason text={reason} limit={220} />
            </ExplanationCard>
          ))}
      </div>

      <h2>Основные риски</h2>
      <div className="card-grid">
        <RiskCard title="Предупреждения">
          {candidate.warnings.length ? (
            <ul className="plain-list">
              {candidate.warnings.slice(0, 6).map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : (
            <p>Явных предупреждений нет — это не значит «без риска».</p>
          )}
        </RiskCard>
        <WarningCard title="Качество equity-сигнала">
          <p>
            <strong>{candidate.decision_quality.equity_confidence_label_ru}</strong>
          </p>
          <p className="muted">{candidate.decision_quality.equity_confidence_reason_ru}</p>
          <p>
            <Link to="/calibration">Качество прогнозов →</Link>
          </p>
        </WarningCard>
        <DataQualityCard title="CBR hurdle">
          <p>
            Ключевая ставка:{" "}
            {candidate.benchmark.cbr_hurdle_annual == null
              ? "нет данных"
              : `${(candidate.benchmark.cbr_hurdle_annual * 100).toFixed(2)}%`}
          </p>
          <p className="muted">{candidate.benchmark.note_ru}</p>
        </DataQualityCard>
      </div>

      <h2>Что Kraken не включил</h2>
      {candidate.rejected_candidates.length ? (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Инструмент</th>
                  <th>Возможность</th>
                  <th>Статус</th>
                  <th>Причина</th>
                </tr>
              </thead>
              <tbody>
                {candidate.rejected_candidates.map((r) => (
                  <tr key={`${r.symbol}-${r.reason_ru}`}>
                    <td>{r.display_name}</td>
                    <td>{r.opportunity_hint ?? "—"}</td>
                    <td>
                      <StatusBadge status={r.risk_status} />
                    </td>
                    <td style={{ whiteSpace: "normal", maxWidth: "22rem" }}>{r.reason_ru}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <EmptyState
          title="Явных отклонений нет"
          reason="Либо кандидаты прошли gate как research-only, либо universe пуст."
        />
      )}

      <h2>Что изменилось</h2>
      <div className="card">
        <p>{candidate.diff?.summary_ru}</p>
        {candidate.diff?.changes?.length ? (
          <ul className="plain-list">
            {candidate.diff.changes.map((c) => (
              <li key={c.text_ru}>{c.text_ru}</li>
            ))}
          </ul>
        ) : null}
      </div>

      <h2>Деньги</h2>
      <div className="card-grid">
        <MetricCard label="Инвестировано" value={money(candidate.money.invested)} />
        <MetricCard label="Комиссии (до налогов)" value={money(candidate.money.fees)} helpId="cash_remainder" />
        <MetricCard
          label="Целевой Cash"
          value={money(candidate.money.strategic_cash)}
          helpId="strategic_cash"
        />
        <MetricCard
          label="Остаток из-за лотов"
          value={money(candidate.money.lot_remainder)}
          helpId="cash_remainder"
        />
      </div>
      <p className="muted">
        {candidate.money.tax_note_ru} {candidate.money.broker_note_ru}
      </p>

      <div className="card">
        <button type="button" className="why-toggle" onClick={() => setTechOpen((v) => !v)}>
          {techOpen ? "Скрыть technical details" : "Technical details"}
        </button>
        <div className="reveal-panel" hidden={!techOpen}>
          <pre className="tech-block" style={{ whiteSpace: "pre-wrap" }}>
            {JSON.stringify(
              {
                candidate_id: candidate.candidate_id,
                version: candidate.version,
                provenance: candidate.provenance,
                level_3: candidate.level_explanations?.level_3,
                risk_summary: candidate.risk_assessment_summary,
              },
              null,
              2,
            )}
          </pre>
          <p className="muted">
            Candidate ≠ Simulator ≠ Shadow.{" "}
            <Link to="/investment-decision">Инвестиционное решение</Link> ·{" "}
            <Link to="/portfolio-risk">Проверка риска</Link>
          </p>
        </div>
      </div>
    </section>
  );
}
