import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  getResearchOptions,
  launchResearchRun,
  listResearchRuns,
  planQuickSuite,
  type LaunchResponse,
  type ResearchOptions,
  type ResearchRunSummary,
} from "../api/researchLab";
import { PageHeader, PageState, StatusBadge } from "../components/Ui";
import { MetricHelp } from "../help";
import { CbrHurdleBlock } from "../features/researchLab/CbrHurdleBlock";
import {
  MAX_COMPARE_RUNS,
  MIN_COMPARE_RUNS,
  REGISTRY_SORTS,
  bpsLabel,
  experimentName,
  launchOutcomeMessage,
  policyHumanName,
  riskHumanName,
  runStatusLabel,
} from "../features/researchLab/labels";
import { formatDateRange, formatPercent, shortHash } from "../utils/format";
import { labels } from "../utils/labels";

function daysBetween(from?: string | null, to?: string | null): number | null {
  if (!from || !to) return null;
  const a = Date.parse(from);
  const b = Date.parse(to);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return Math.round((b - a) / 86_400_000);
}

export function ResearchLabPage() {
  const navigate = useNavigate();
  const [options, setOptions] = useState<ResearchOptions | null>(null);
  const [runs, setRuns] = useState<ResearchRunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [launchResult, setLaunchResult] = useState<LaunchResponse | null>(null);

  const [candidateId, setCandidateId] = useState("");
  const [policyId, setPolicyId] = useState("");
  const [riskId, setRiskId] = useState("");
  const [commissionBps, setCommissionBps] = useState(10);
  const [customCost, setCustomCost] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [capital, setCapital] = useState(1_000_000);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [execOpen, setExecOpen] = useState(false);
  const [techOpen, setTechOpen] = useState(false);

  const [filterPolicy, setFilterPolicy] = useState("");
  const [filterRisk, setFilterRisk] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterSegment, setFilterSegment] = useState("");
  const [sort, setSort] = useState("newest");
  const [selected, setSelected] = useState<number[]>([]);
  const [suiteMsg, setSuiteMsg] = useState<string | null>(null);

  const reloadRuns = (signal?: AbortSignal) =>
    listResearchRuns(
      {
        limit: 100,
        policy_id: filterPolicy || undefined,
        risk_id: filterRisk || undefined,
        status: filterStatus || undefined,
        segment: filterSegment || undefined,
        sort,
      },
      signal,
    ).then(setRuns);

  useEffect(() => {
    const controller = new AbortController();
    getResearchOptions(controller.signal)
      .then((opts) => {
        setOptions(opts);
        setCandidateId(opts.defaults.candidate_id);
        setPolicyId(opts.defaults.policy_id);
        setRiskId(opts.defaults.risk_id);
        setCommissionBps(opts.defaults.commission_bps);
        setCapital(opts.defaults.initial_capital);
        setDateFrom(opts.defaults.date_from ?? "");
        setDateTo(opts.defaults.date_to ?? "");
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    reloadRuns(controller.signal).catch((reason: unknown) => {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setError(errorMessage(reason));
      }
    });
    return () => controller.abort();
  }, [filterPolicy, filterRisk, filterStatus, filterSegment, sort]);

  const selectedPolicy = options?.policies.find((p) => p.id === policyId);
  const selectedRisk = options?.risk_policies.find((r) => r.id === riskId);
  const selectedCandidate = options?.candidates.find((c) => c.id === candidateId);
  const isRankingCandidate =
    selectedCandidate?.prediction_semantic === "RANKING_SCORE" ||
    selectedCandidate?.candidate_version === "v1_ranker";
  const candidateOutputLabel =
    selectedCandidate?.output_label ??
    (isRankingCandidate ? "Рейтинговый балл" : "Прогноз изменения цены");
  const holdoutSeg = options?.prediction_segments.find((s) => !s.launchable);
  const periodDays = daysBetween(dateFrom, dateTo);
  const shortWarn =
    periodDays != null &&
    options?.period_warnings?.short_calendar_days != null &&
    periodDays < options.period_warnings.short_calendar_days;

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= MAX_COMPARE_RUNS) return prev;
      return [...prev, id];
    });
  };

  const onLaunch = async (force = false) => {
    setBusy(true);
    setLaunchResult(null);
    setError(null);
    try {
      const result = await launchResearchRun({
        candidate_id: candidateId,
        segment: "DEVELOPMENT_OOS",
        policy_id: policyId,
        risk_id: riskId,
        commission_bps: commissionBps,
        date_from: dateFrom || null,
        date_to: dateTo || null,
        initial_capital: capital,
        name: name || null,
        note: note || null,
        force_rerun: force,
      });
      setLaunchResult(result);
      await reloadRuns();
    } catch (reason: unknown) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const onPlanSuite = async () => {
    setSuiteMsg(null);
    try {
      const plan = await planQuickSuite({
        candidate_id: candidateId,
        date_from: dateFrom,
        date_to: dateTo,
        initial_capital: capital,
      });
      setSuiteMsg(
        `${plan.label}: ${plan.total} конфигураций, ${plan.already_exist} уже есть, ${plan.will_run} будет запущено. Это не оптимизация.`,
      );
    } catch (reason: unknown) {
      setError(errorMessage(reason));
    }
  };

  if (error && !options) return <PageState kind="error">{error}</PageState>;
  if (!options) return <PageState kind="loading" title="Загрузка лаборатории…" />;

  return (
    <section className="research-lab">
      <PageHeader
        title={labels.nav.lab}
        description="Исследовательский кокпит: исторические эксперименты, диагностика моделей, проспективное A/B и живой Shadow."
        helpPageId="research_lab"
        actions={
          <Link to="/shadow" className="secondary button-link">
            {labels.nav.liveExperiment}
          </Link>
        }
      />

      <CbrHurdleBlock />

      <div className="info-panel research-lab-note" data-testid="research-not-live">
        <strong>Исследовательский контекст.</strong> Лаборатория использует исторические данные.
        Результат симуляции показывает, что произошло бы при выбранных правилах на известных
        исторических периодах. Это не живой эксперимент и не доказательство будущей доходности.
        <div className="muted" style={{ marginTop: 8 }}>
          Shadow Portfolio работает только вперёд и не пересчитывает прошлое.{" "}
          <MetricHelp metricId="research_not_live" />
        </div>
      </div>

      <div className="card-grid research-cockpit-cards" data-testid="research-cockpit-cards">
        <a className="card cockpit-card" href="#historical-lab">
          <h3>Историческая лаборатория</h3>
          <p className="muted">
            Запуск и сравнение исторических экспериментов на Development OOS.
          </p>
        </a>
        <Link className="card cockpit-card" to="/research/diagnostics">
          <h3>Диагностика моделей</h3>
          <p className="muted">
            Почему такой результат: верх рейтинга, стабильность, режимы, экономика.
          </p>
        </Link>
        <Link className="card cockpit-card" to="/research/prospective-models">
          <h3>Проспективное сравнение V0/V1</h3>
          <p className="muted">Парный эксперимент только вперёд: одинаковые условия, разная модель.</p>
        </Link>
        <Link className="card cockpit-card" to="/shadow">
          <h3>Живой эксперимент</h3>
          <p className="muted">
            Shadow Portfolio и ежедневный исследовательский цикл — только вперёд.
          </p>
        </Link>
      </div>

      <div className="card research-wizard" id="historical-lab">
        <h2>Новый эксперимент</h2>
        <p className="muted">
          Здесь можно запускать исторические эксперименты на уже сохранённых out-of-sample прогнозах.
          Эксперименты не меняют живой Shadow Portfolio и не переобучают модель.
        </p>

        <fieldset className="wizard-section">
          <legend>
            1. Источник прогнозов <MetricHelp metricId="development_oos" />
          </legend>
          <label className="radio-row">
            <input type="radio" checked readOnly />
            Development OOS — исторические прогнозы вне обучающей выборки
          </label>
          <p className="field-hint">
            Модель не обучалась на тех наблюдениях, на которых затем проверялся соответствующий
            walk-forward прогноз.
          </p>
          {holdoutSeg ? (
            <div className="holdout-block" data-testid="holdout-protected">
              <label className="radio-row disabled">
                <input type="radio" disabled />
                {holdoutSeg.human_label}
              </label>
              <span className="badge badge-warning">{holdoutSeg.badge}</span>
              <p className="field-hint">
                {holdoutSeg.explanation} <MetricHelp metricId="observed_holdout" />
              </p>
            </div>
          ) : null}
        </fieldset>

        <fieldset className="wizard-section">
          <legend>
            2. Модель <MetricHelp metricId="candidate_model" />
          </legend>
          <select value={candidateId} onChange={(e) => setCandidateId(e.target.value)}>
            {options.candidates.map((c) => (
              <option key={c.id} value={c.id} disabled={!c.eligible}>
                {c.human_name}
              </option>
            ))}
          </select>
          {selectedCandidate ? (
            <>
              <p className="field-hint">
                {selectedCandidate.technical_line} · статус исследования:{" "}
                {selectedCandidate.research_verdict}. Output: {candidateOutputLabel}
                {isRankingCandidate ? " · горизонт 20 торговых дней" : ""}. Стратегия — решение, Risk —
                ограничения, Execution — исполнение.{" "}
                {isRankingCandidate ? <MetricHelp metricId="ranking_score" /> : null}
              </p>
              {isRankingCandidate ? (
                <p className="field-hint" data-testid="ranking-candidate-help">
                  Модель оценивает относительную привлекательность инструментов на одну дату.
                  Рейтинговый балл используется для определения порядка, а не является прогнозом
                  доходности в процентах. Баллы разных моделей напрямую между собой не сравниваются.{" "}
                  <MetricHelp metricId="ranking_model" />
                </p>
              ) : null}
            </>
          ) : null}
        </fieldset>

        <fieldset className="wizard-section">
          <legend>
            3. Портфельная стратегия <MetricHelp metricId="portfolio_policy" />
          </legend>
          {options.policies.map((p) => (
            <label key={p.id} className="radio-row">
              <input
                type="radio"
                name="policy"
                checked={policyId === p.id}
                onChange={() => setPolicyId(p.id)}
              />
              <span>
                <strong>{p.human_name}</strong>
                <span className="muted"> · {p.technical_id}</span>
                <div className="field-hint">{p.description}</div>
              </span>
            </label>
          ))}
          {selectedPolicy ? (
            <details>
              <summary>Параметры стратегии (только чтение)</summary>
              <pre className="tech-block">{JSON.stringify(selectedPolicy.parameters, null, 2)}</pre>
              {policyId.includes("HYSTERESIS") ? (
                <p className="field-hint">
                  Пример удержания: неделя 1 — ранг 5 → покупка; неделя 2 — ранг 11 (вне Top 20, но в
                  Top 35) → удержание; неделя 3 — ранг 20 (вне зоны) → выход.
                </p>
              ) : null}
            </details>
          ) : null}
        </fieldset>

        <fieldset className="wizard-section">
          <legend>
            4. Управление риском <MetricHelp metricId="risk_policy" />
          </legend>
          {options.risk_policies.map((r) => (
            <label key={r.id} className="radio-row">
              <input
                type="radio"
                name="risk"
                checked={riskId === r.id}
                onChange={() => setRiskId(r.id)}
              />
              <span>
                <strong>{r.human_name}</strong>
                <span className="muted"> · {r.technical_id}</span>
                <div className="field-hint">{r.description}</div>
              </span>
            </label>
          ))}
          {selectedRisk ? (
            <details>
              <summary>Параметры риска (только чтение)</summary>
              <pre className="tech-block">{JSON.stringify(selectedRisk.parameters, null, 2)}</pre>
            </details>
          ) : null}
        </fieldset>

        <fieldset className="wizard-section">
          <legend>
            5. Издержки <MetricHelp metricId="simulation_cost" />
          </legend>
          <p className="field-hint">
            1 базисный пункт (bp) = 0.01 процентного пункта. Пресеты задают commission_bps;
            slippage_bps = 0. Это условный исследовательский friction, не тариф брокера.
          </p>
          <div className="chip-row">
            {options.cost_presets.map((p) => (
              <button
                key={p.bps}
                type="button"
                className={!customCost && commissionBps === p.bps ? "primary" : "secondary"}
                onClick={() => {
                  setCustomCost(false);
                  setCommissionBps(p.bps);
                }}
              >
                {p.human_label}
              </button>
            ))}
            {options.cost_custom.allowed ? (
              <button
                type="button"
                className={customCost ? "primary" : "secondary"}
                onClick={() => setCustomCost(true)}
              >
                {options.cost_custom.human_label}
              </button>
            ) : null}
          </div>
          {customCost ? (
            <label>
              bps (0–{options.cost_custom.max_bps})
              <input
                type="number"
                min={0}
                max={options.cost_custom.max_bps}
                value={commissionBps}
                onChange={(e) => setCommissionBps(Number(e.target.value))}
              />
            </label>
          ) : null}
        </fieldset>

        <fieldset className="wizard-section">
          <legend>
            6. Период <MetricHelp metricId="research_period" />
          </legend>
          <div className="form-row">
            <label>
              С
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
            </label>
            <label>
              По
              <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
            </label>
          </div>
          <p className="field-hint">
            Доступно: {options.defaults.date_from} → {options.defaults.date_to}
          </p>
          {shortWarn ? (
            <p className="warning-inline">Короткий период может давать нестабильные выводы.</p>
          ) : null}
        </fieldset>

        <fieldset className="wizard-section">
          <legend>7. Капитал</legend>
          <label>
            Стартовый капитал (₽)
            <input
              type="number"
              min={options.capital_bounds.min}
              max={options.capital_bounds.max}
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
            />
          </label>
          <p className="field-hint">
            Размер виртуального капитала. При fractional shares он обычно не меняет структуру
            процентной доходности. Это не реальные деньги.
          </p>
          <label>
            Название (необязательно)
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Hysteresis · 10 bps" />
          </label>
          <label>
            Заметка (не влияет на config hash)
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Проверяю влияние комиссий." />
          </label>
        </fieldset>

        <fieldset className="wizard-section">
          <legend>8. Итоговая конфигурация</legend>
          <details open={execOpen} onToggle={(e) => setExecOpen((e.target as HTMLDetailsElement).open)}>
            <summary>Как исполняется симуляция</summary>
            <ul className="muted">
              <li>Execution: {options.execution_assumptions.execution}</li>
              <li>Fractional shares: {String(options.execution_assumptions.fractional_shares)}</li>
              <li>Dividends: {options.execution_assumptions.dividends}</li>
              <li>Benchmark: {options.execution_assumptions.benchmark}</li>
              <li>No leverage: {String(options.execution_assumptions.no_leverage)}</li>
            </ul>
          </details>
          <div className="summary-box" data-testid="config-summary">
            <div>Модель: {selectedCandidate?.human_name}</div>
            <div>Output: {candidateOutputLabel}</div>
            {isRankingCandidate ? <div>Horizon: 20 торговых дней</div> : null}
            <div>Прогнозы: Development OOS</div>
            <div>Стратегия: {selectedPolicy?.human_name}</div>
            <div>Risk: {selectedRisk?.human_name}</div>
            <div>
              Период: {dateFrom} → {dateTo}
            </div>
            <div>Издержки: {bpsLabel(commissionBps)}</div>
            <div>Старт: {capital.toLocaleString("ru-RU")} ₽</div>
            <div>Execution: Next Open</div>
          </div>
          <div className="form-row">
            <button type="button" className="primary" disabled={busy} onClick={() => onLaunch(false)}>
              {busy ? "Выполняется…" : "Запустить эксперимент"}
            </button>
            <button type="button" className="secondary" onClick={onPlanSuite}>
              Пакет сравнения (план)
            </button>
          </div>
          {suiteMsg ? <p className="field-hint">{suiteMsg}</p> : null}
          {launchResult ? (
            <div className="launch-result" data-testid="launch-result">
              <p>{launchResult.message || launchOutcomeMessage(launchResult.outcome)}</p>
              {launchResult.outcome === "REUSE_EXISTING" ? (
                <p data-testid="reuse-banner">Такой эксперимент уже существует.</p>
              ) : null}
              <Link to={`/research/${launchResult.run.id}`}>Открыть результат</Link>
              {" · "}
              <Link to={`/simulator/${launchResult.run.id}`}>Симуляция</Link>
              {launchResult.outcome === "REUSE_EXISTING" ? (
                <>
                  {" · "}
                  <button type="button" className="secondary" onClick={() => onLaunch(true)}>
                    Запустить повторно
                  </button>
                </>
              ) : null}
            </div>
          ) : null}
          {error ? <PageState kind="error">{error}</PageState> : null}
        </fieldset>
      </div>

      <div className="card">
        <h2>История экспериментов</h2>
        <p className="muted">
          Высокая доходность ≠ автоматически лучший эксперимент. Смотрите просадку и оборот рядом.{" "}
          <MetricHelp metricId="fair_comparison" />
        </p>
        <div className="form-row filters">
          <select value={filterPolicy} onChange={(e) => setFilterPolicy(e.target.value)} aria-label="Фильтр политики">
            <option value="">Все стратегии</option>
            {options.policies.map((p) => (
              <option key={p.id} value={p.id}>
                {p.human_name}
              </option>
            ))}
          </select>
          <select value={filterRisk} onChange={(e) => setFilterRisk(e.target.value)} aria-label="Фильтр риска">
            <option value="">Все risk</option>
            {options.risk_policies.map((r) => (
              <option key={r.id} value={r.id}>
                {r.human_name}
              </option>
            ))}
          </select>
          <select value={filterSegment} onChange={(e) => setFilterSegment(e.target.value)} aria-label="Фильтр сегмента">
            <option value="">Все сегменты</option>
            <option value="DEVELOPMENT_OOS">Development OOS</option>
            <option value="FINAL_HOLDOUT">FINAL HOLDOUT</option>
          </select>
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} aria-label="Фильтр статуса">
            <option value="">Все статусы</option>
            <option value="SUCCESS">Готов</option>
            <option value="FAILED">Ошибка</option>
          </select>
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Сортировка">
            {REGISTRY_SORTS.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="primary"
            disabled={selected.length < MIN_COMPARE_RUNS}
            onClick={() => navigate(`/research/compare?runs=${selected.join(",")}`)}
          >
            Сравнить ({selected.length})
          </button>
        </div>

        {!runs ? (
          <PageState kind="loading" title="Загрузка истории…" />
        ) : !runs.length ? (
          <PageState kind="empty">
            Экспериментов пока нет. Первый запуск создаст исторический research-прогон на Development
            OOS и откроет его в дашборде симулятора.
          </PageState>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th />
                  <th>Название</th>
                  <th>Дата</th>
                  <th>Модель</th>
                  <th>Стратегия</th>
                  <th>Risk</th>
                  <th>Период</th>
                  <th>Издержки</th>
                  <th className="numeric">Доходность</th>
                  <th className="numeric">Max DD</th>
                  <th className="numeric">Оборот</th>
                  <th>Статус</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => {
                  const m = run.metrics ?? {};
                  return (
                    <tr key={run.id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selected.includes(run.id)}
                          onChange={() => toggleSelect(run.id)}
                          aria-label={`Выбрать ${run.id}`}
                        />
                      </td>
                      <td>
                        <Link to={`/research/${run.id}`}>{experimentName(run)}</Link>
                        {run.research?.observed_holdout ? (
                          <span className="badge badge-warning" title="Уже наблюдавшийся holdout">
                            HOLDOUT
                          </span>
                        ) : null}
                      </td>
                      <td>{run.created_at?.slice(0, 10) ?? "—"}</td>
                      <td title={run.candidate_config_hash ?? undefined}>
                        {shortHash(run.candidate_config_hash)}
                      </td>
                      <td>{policyHumanName(run.spec?.policy_name, options)}</td>
                      <td>{riskHumanName(run.spec?.risk_name, options)}</td>
                      <td>{formatDateRange(run.date_from, run.date_to)}</td>
                      <td>{bpsLabel(run.spec?.commission_bps)}</td>
                      <td className="numeric">{formatPercent(m.total_price_return)}</td>
                      <td className="numeric">{formatPercent(m.max_drawdown)}</td>
                      <td className="numeric">
                        {m.turnover_ratio != null ? `${Number(m.turnover_ratio).toFixed(1)}×` : "—"}
                      </td>
                      <td>
                        <StatusBadge status={run.status} />
                        <span className="sr-only">{runStatusLabel(run.status)}</span>
                      </td>
                      <td>
                        <Link to={`/simulator/${run.id}`}>Симуляция</Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <details open={techOpen} onToggle={(e) => setTechOpen((e.target as HTMLDetailsElement).open)}>
        <summary>Технические детали каталога</summary>
        <pre className="tech-block">{JSON.stringify({ holdout_start: options.holdout_start }, null, 2)}</pre>
      </details>
    </section>
  );
}
