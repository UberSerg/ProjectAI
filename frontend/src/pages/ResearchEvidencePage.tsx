import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, errorMessage } from "../api/client";
import {
  CANONICAL_CAMPAIGN_VERSION,
  getResearchEvidenceCampaignDossier,
  getResearchEvidenceEconomics,
  getResearchEvidenceOverview,
  getResearchEvidenceProspective,
  launchCanonicalEvidenceCampaignV1,
  listResearchEvidenceCampaigns,
  runResearchEvidence,
  type EvidenceCampaignSummary,
  type EvidenceDossierV1,
  type EconomicsSummary,
  type ProspectiveSummary,
  type ResearchEvidenceOverview,
} from "../api/researchEvidence";
import { EmptyState, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { AblationTable } from "../features/researchEvidence/AblationTable";
import { CampaignHistoryList } from "../features/researchEvidence/CampaignHistoryList";
import { CampaignIdentityCard } from "../features/researchEvidence/CampaignIdentityCard";
import { CheckingSection } from "../features/researchEvidence/CheckingSection";
import { DataQualityCard } from "../features/researchEvidence/DataQualityCard";
import { DatasetCard } from "../features/researchEvidence/DatasetCard";
import { EconomicsSection } from "../features/researchEvidence/EconomicsSection";
import { HistoricalSignalSection } from "../features/researchEvidence/HistoricalSignalSection";
import { LimitationsList } from "../features/researchEvidence/LimitationsList";
import { PrimaryEconomicsCard } from "../features/researchEvidence/PrimaryEconomicsCard";
import { ProspectiveSection } from "../features/researchEvidence/ProspectiveSection";
import { RealOosTable } from "../features/researchEvidence/RealOosTable";
import { RobustnessMatrix } from "../features/researchEvidence/RobustnessMatrix";
import { StabilityTables } from "../features/researchEvidence/StabilityTables";
import {
  ENGINE_TITLE,
  EXACT_RERUN_LABEL,
  LAUNCH_CANONICAL_LABEL,
  RESEARCH_ONLY_BADGE,
} from "../features/researchEvidence/constants";
import { identityFromDossier, isDossierEmpty, sortCampaignsNewestFirst } from "../features/researchEvidence/campaignFormat";
import { isOverviewEmpty, isOverviewPartial } from "../features/researchEvidence/format";
import { useKrakenRole } from "../role/KrakenRoleContext";
import { labels } from "../utils/labels";

export function ResearchEvidencePage() {
  const { isOwner } = useKrakenRole();
  const [overview, setOverview] = useState<ResearchEvidenceOverview | null>(null);
  const [prospective, setProspective] = useState<ProspectiveSummary | null>(null);
  const [economics, setEconomics] = useState<EconomicsSummary | null>(null);
  const [campaigns, setCampaigns] = useState<EvidenceCampaignSummary[]>([]);
  const [dossier, setDossier] = useState<EvidenceDossierV1 | null>(null);
  const [selectedFingerprint, setSelectedFingerprint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadDossier = useCallback(async (fingerprint: string, signal?: AbortSignal) => {
    const data = await getResearchEvidenceCampaignDossier(fingerprint, signal);
    setDossier(data);
    setSelectedFingerprint(fingerprint);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    Promise.allSettled([
      getResearchEvidenceOverview(controller.signal),
      listResearchEvidenceCampaigns(controller.signal),
    ])
      .then(async ([overviewResult, campaignsResult]) => {
        if (overviewResult.status === "rejected") {
          const reason = overviewResult.reason;
          if (reason instanceof DOMException && reason.name === "AbortError") return;
          setError(errorMessage(reason instanceof ApiError ? reason : reason));
          return;
        }

        const data = overviewResult.value;
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

        if (campaignsResult.status === "fulfilled") {
          const sorted = sortCampaignsNewestFirst(campaignsResult.value);
          setCampaigns(sorted);
          const first = sorted[0];
          if (first?.fingerprint) {
            try {
              await loadDossier(first.fingerprint, controller.signal);
            } catch (reason: unknown) {
              if (reason instanceof DOMException && reason.name === "AbortError") return;
              setError(errorMessage(reason));
              setDossier({ empty: true });
            }
          } else {
            setDossier({ empty: true });
          }
        } else {
          const reason = campaignsResult.reason;
          if (reason instanceof DOMException && reason.name === "AbortError") return;
          setDossier({ empty: true });
        }
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(errorMessage(reason instanceof ApiError ? reason : reason));
      });
    return () => controller.abort();
  }, [loadDossier]);

  const experimentId = overview?.experiment?.id ?? null;
  const canExactRerun = Boolean(experimentId);
  const campaignExists = Boolean(selectedFingerprint || campaigns.length);

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

  const onLaunchCanonical = async (exactRerun = false) => {
    setBusy(true);
    setRunMsg(null);
    setError(null);
    try {
      const result = await launchCanonicalEvidenceCampaignV1({
        campaign_version: CANONICAL_CAMPAIGN_VERSION,
        exact_rerun: exactRerun ? true : null,
      });
      setRunMsg(result.message ?? result.status ?? "Каноническое исследование поставлено в очередь.");
      const fingerprint = result.fingerprint;
      const list = await listResearchEvidenceCampaigns();
      const sorted = sortCampaignsNewestFirst(list);
      setCampaigns(sorted);
      const next = fingerprint ?? sorted[0]?.fingerprint;
      if (next) await loadDossier(next);
    } catch (reason: unknown) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const onSelectCampaign = async (fingerprint: string) => {
    setError(null);
    try {
      await loadDossier(fingerprint);
    } catch (reason: unknown) {
      setError(errorMessage(reason));
    }
  };

  if (error && !overview && !dossier) {
    return (
      <PageState kind="error" title="Не удалось загрузить доказательства">
        {error}
      </PageState>
    );
  }
  if (!overview && !dossier) {
    return <PageState kind="loading" title="Загрузка доказательств…" />;
  }

  const empty = overview ? isOverviewEmpty(overview) : true;
  const partial = overview ? isOverviewPartial(overview) : false;
  const models = overview?.historical_models;
  const identity = identityFromDossier(dossier);
  const dossierEmpty = isDossierEmpty(dossier);
  const completeness = dossier?.evidence_completeness;

  return (
    <section className="research-lab research-evidence" data-testid="research-evidence-page">
      <PageHeader
        title={ENGINE_TITLE}
        description="OWNER-экран агрегатов Dataset V4, канонической кампании и исторических OOS-проверок. Это исследование, не готовность к живой торговле."
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
            className="primary"
            disabled={busy}
            data-testid="launch-canonical-campaign"
            onClick={() => void onLaunchCanonical(false)}
          >
            {LAUNCH_CANONICAL_LABEL}
          </button>
          {campaignExists ? (
            <button
              type="button"
              className="secondary"
              disabled={busy || !selectedFingerprint}
              data-testid="exact-rerun-canonical"
              onClick={() => void onLaunchCanonical(true)}
            >
              {EXACT_RERUN_LABEL}
            </button>
          ) : null}
          <button
            type="button"
            className="secondary"
            disabled={busy || !canExactRerun}
            onClick={() => void onRun()}
          >
            Пересчитать доказательства
          </button>
          <span className="field-hint" data-testid="evidence-rerun-hint">
            Канонический запуск использует только {CANONICAL_CAMPAIGN_VERSION}, без свободной вселенной.
            {canExactRerun
              ? " Пересчёт эксперимента — строго по замороженным DatasetRun."
              : " Для старого пересчёта нужен существующий эксперимент."}
          </span>
        </p>
      ) : null}

      <CampaignHistoryList
        campaigns={campaigns}
        selected={selectedFingerprint}
        onSelect={(fp) => void onSelectCampaign(fp)}
      />

      {dossierEmpty ? (
        <EmptyState
          title="Каноническое досье ещё не собрано"
          reason="OWNER может запустить CanonicalEvidenceCampaignV1. Пустое досье — валидный ответ, не ноль качества."
        />
      ) : (
        <>
          <CampaignIdentityCard identity={identity} />
          {completeness ? (
            <div className="card" data-testid="campaign-completeness">
              <h3>Полнота досье</h3>
              <p className="field-hint">Это статусы исполнения секций, не score и не готовность к торговле.</p>
              <ul className="plain-list">
                <li>DATA_INTEGRITY: {completeness.data_integrity ?? "нет данных"}</li>
                <li>HISTORICAL_OOS: {completeness.historical_oos ?? "нет данных"}</li>
                <li>ECONOMICS: {completeness.economics ?? "нет данных"}</li>
                <li>PROSPECTIVE: {completeness.prospective ?? "нет данных"}</li>
                <li>OWNER_REVIEW_STATE: {completeness.owner_review_state ?? "нет данных"}</li>
              </ul>
            </div>
          ) : null}
          <DataQualityCard quality={dossier?.data_quality} />
          <RealOosTable oos={dossier?.historical_oos} ablation={dossier?.ablation ?? overview?.ablation} />
          <StabilityTables stability={dossier?.stability} />
          <PrimaryEconomicsCard contract={dossier?.economics_primary} />
          <RobustnessMatrix matrix={dossier?.economics_robustness} />
        </>
      )}

      {empty && overview ? (
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
      <CheckingSection experiment={overview?.experiment} />
      <DatasetCard dataset={overview?.dataset} />

      <div className="card" data-testid="evidence-historical-heading">
        <h3>Исторический OOS сигнал</h3>
        <p className="field-hint">
          Regression и Ranker показаны отдельно. Смотрите Rank IC, spread, n и устойчивость по
          fold/year — не одну «точность».
        </p>
      </div>
      <HistoricalSignalSection regression={models?.regression} ranker={models?.ranker} />
      <AblationTable ablation={overview?.ablation} />
      <EconomicsSection economics={economics ?? overview?.economics} />
      <ProspectiveSection prospective={dossier?.prospective ?? prospective ?? overview?.prospective} />
      <LimitationsList limitations={dossier?.limitations ?? overview?.limitations} />
    </section>
  );
}
