import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, errorMessage } from "../api/client";
import {
  getResearchEvidenceEconomics,
  getResearchEvidenceOverview,
  getResearchEvidenceProspective,
  runResearchEvidence,
  type EconomicsSummary,
  type ProspectiveSummary,
  type ResearchEvidenceOverview,
} from "../api/researchEvidence";
import { EmptyState, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { AblationTable } from "../features/researchEvidence/AblationTable";
import { CheckingSection } from "../features/researchEvidence/CheckingSection";
import { DatasetCard } from "../features/researchEvidence/DatasetCard";
import { EconomicsSection } from "../features/researchEvidence/EconomicsSection";
import { HistoricalSignalSection } from "../features/researchEvidence/HistoricalSignalSection";
import { LimitationsList } from "../features/researchEvidence/LimitationsList";
import { ProspectiveSection } from "../features/researchEvidence/ProspectiveSection";
import { ENGINE_TITLE, RESEARCH_ONLY_BADGE } from "../features/researchEvidence/constants";
import { isOverviewEmpty, isOverviewPartial } from "../features/researchEvidence/format";
import { useKrakenRole } from "../role/KrakenRoleContext";
import { labels } from "../utils/labels";

export function ResearchEvidencePage() {
  const { isOwner } = useKrakenRole();
  const [overview, setOverview] = useState<ResearchEvidenceOverview | null>(null);
  const [prospective, setProspective] = useState<ProspectiveSummary | null>(null);
  const [economics, setEconomics] = useState<EconomicsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    getResearchEvidenceOverview(controller.signal)
      .then(async (data) => {
        setOverview(data);
        const experimentId = data.experiment?.id;
        const [prospectiveResult, economicsResult] = await Promise.allSettled([
          getResearchEvidenceProspective(controller.signal),
          experimentId
            ? getResearchEvidenceEconomics(experimentId, controller.signal)
            : Promise.resolve(data.economics ?? null),
        ]);
        if (prospectiveResult.status === "fulfilled") {
          setProspective(prospectiveResult.value);
        } else {
          setProspective(data.prospective ?? null);
        }
        if (economicsResult.status === "fulfilled") {
          setEconomics(economicsResult.value ?? data.economics ?? null);
        } else {
          setEconomics(data.economics ?? null);
        }
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(errorMessage(reason instanceof ApiError ? reason : reason));
      });
    return () => controller.abort();
  }, []);

  const experimentId = overview?.experiment?.id ?? null;
  const canExactRerun = Boolean(experimentId);

  const onRun = async () => {
    if (!experimentId) return;
    setBusy(true);
    setRunMsg(null);
    setError(null);
    try {
      const result = await runResearchEvidence({ experiment_id: experimentId });
      setRunMsg(result.message ?? result.status ?? "Запрос на пересчёт отправлен.");
    } catch (reason: unknown) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  if (error && !overview) {
    return (
      <PageState kind="error" title="Не удалось загрузить доказательства">
        {error}
      </PageState>
    );
  }
  if (!overview) {
    return <PageState kind="loading" title="Загрузка доказательств…" />;
  }

  const empty = isOverviewEmpty(overview);
  const partial = isOverviewPartial(overview);
  const models = overview.historical_models;

  return (
    <section className="research-lab research-evidence" data-testid="research-evidence-page">
      <PageHeader
        title={ENGINE_TITLE}
        description="OWNER-экран агрегатов Dataset V4 и исторических OOS-проверок. Это исследование, не готовность к живой торговле."
        actions={
          <>
            <span data-testid="research-only-badge">
              <StatusBadge status="research_only" label={RESEARCH_ONLY_BADGE} />
            </span>
            <Link to="/research" className="secondary button-link">
              {labels.nav.researchLab}
            </Link>
          </>
        }
      />

      <div className="info-panel research-lab-note" data-testid="research-evidence-not-live">
        <strong>Только исследование.</strong> Экран не означает готовность к живой торговле, не
        повышает Candidate и не запускает сделки. Исторические метрики и проспективные наблюдения
        живут в разных блоках и не усредняются.
      </div>

      {error ? (
        <div className="banner banner-warning" role="alert" data-testid="evidence-inline-error">
          {error}
        </div>
      ) : null}
      {runMsg ? (
        <div className="banner banner-info" data-testid="evidence-run-result">
          {runMsg}
        </div>
      ) : null}

      {isOwner ? (
        <p className="page-actions" style={{ marginBottom: "1rem" }}>
          <button
            type="button"
            className="secondary"
            disabled={busy || !canExactRerun}
            onClick={() => void onRun()}
          >
            Пересчитать доказательства
          </button>
          <span className="field-hint" data-testid="evidence-rerun-hint">
            {canExactRerun
              ? "Пересчёт строго по замороженным DatasetRun этого эксперимента, без текущей вселенной."
              : "Нужен существующий эксперимент или явные dataset_v3_run_id / dataset_v4_run_id. Скрытый пересчёт по текущей вселенной недоступен."}
          </span>
        </p>
      ) : null}

      {empty ? (
        <EmptyState
          title="Доказательства ещё не собраны"
          reason="Overview пуст: нет эксперимента, датасета и исторических агрегатов. Ограничения ниже всё равно обязательны к прочтению."
        />
      ) : null}
      {partial ? (
        <div className="banner banner-warning" data-testid="evidence-partial">
          Частичные доказательства: часть блоков отсутствует или помечена как partial. Пустые ячейки
          — это «ещё нет данных», а не ноль качества.
        </div>
      ) : null}

      <h2 className="sr-only">{labels.nav.researchEvidence}</h2>
      <CheckingSection experiment={overview.experiment} />
      <DatasetCard dataset={overview.dataset} />

      <div className="card" data-testid="evidence-historical-heading">
        <h3>Исторический OOS сигнал</h3>
        <p className="field-hint">
          Regression и Ranker показаны отдельно. Смотрите Rank IC, spread, n и устойчивость по
          fold/year — не одну «точность».
        </p>
      </div>
      <HistoricalSignalSection regression={models?.regression} ranker={models?.ranker} />
      <AblationTable ablation={overview.ablation} />
      <EconomicsSection economics={economics ?? overview.economics} />
      <ProspectiveSection prospective={prospective ?? overview.prospective} />
      <LimitationsList limitations={overview.limitations} />
    </section>
  );
}
