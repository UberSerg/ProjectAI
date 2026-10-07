/** Official Kraken release history for in-app «О Kraken».

Each entry is an immutable snapshot of what that version contained at release time.

Technical repository VERSION (`1.0.0`) is separate from the investor-visible
product release label (e.g. Kraken 1.02). Do not invent GitHub Release tags
for product notes that were not tagged.
*/

export interface KrakenReleaseNotes {
  /** Product or SemVer key, e.g. 1.02 or 1.0.0 */
  version: string;
  /** Display, e.g. Kraken 1.02 */
  displayVersion: string;
  title: string;
  /**
   * Canonical release date YYYY-MM-DD.
   * Never invent; never replace on later builds.
   */
  date: string;
  /** Git tag when an official tag exists, e.g. v1.0.0. Optional for product notes. */
  gitTag?: string | null;
  /** Annotated release commit SHA when known from the tag. */
  releaseCommitSha?: string | null;
  /** Human USER summary for that version. */
  summary: string;
  highlights: string[];
  /** Human USER changes: «что изменилось — зачем это пользователю». */
  whatsNew: string[];
  /** Optional OWNER / engineering notes; must not replace USER summary. */
  technicalNotes?: string[];
}

/**
 * Technical package/semver from build env or repository VERSION.
 * Must stay `1.0.0` unless an explicit VERSION bump is requested.
 */
export const KRAKEN_VERSION =
  (import.meta.env.VITE_KRAKEN_VERSION as string | undefined)?.trim() || "1.0.0";

/**
 * Investor-visible product release key shown in «О Kraken» and the sidebar.
 * Independent of technical `VERSION` / `KRAKEN_VERSION`.
 */
export const KRAKEN_PRODUCT_VERSION = "1.04";

/**
 * Newest first. Historical entries must keep their own notes forever —
 * never render current changelog under older versions.
 *
 * 1.01 / 1.02 / 1.03 / 1.04 are product micro-releases (no git tag / GitHub Release).
 * 1.01 notes restored from the 28.09.2026 local frontend edit on
 * feature/brain-foundation-v2 (never pushed; lost from main after BFV2 merge).
 * V1.0 date/tag/commit from GitHub Release `v1.0.0`
 * (published_at 2026-09-27T09:43:33Z, commit b815b1ae…).
 */
export const KRAKEN_RELEASES: KrakenReleaseNotes[] = [
  {
    version: "1.04",
    displayVersion: "Kraken 1.04",
    title: "Research Evidence и каноническая кампания",
    date: "2026-10-04",
    summary:
      "Kraken 1.04 завершает построение полноценного research/evidence-контура. Каноническая кампания показала, что текущий набор V4 fundamentals/events не улучшает OOS-сигнал относительно BASE. Это зафиксированный baseline для следующего этапа развития intelligence stack.",
    highlights: [
      "Dataset V4 research foundation",
      "Research Evidence Engine",
      "Каноническая кампания на локальных данных",
      "Immutable evidence dossier",
      "Без promotion Candidate",
    ],
    whatsNew: [
      "Dataset V4 — research-only: PIT fundamentals и events, тот же historical universe и механические labels, что у V3; пропуски остаются native NaN.",
      "Research Evidence Engine: детерминированный identity эксперимента, paired V3/V4, chronological OOS, ablation, stability, next-open economics и prospective bridge.",
      "Завершена Canonical Evidence Campaign на реальных локальных данных: V3 run 655 и V4 run 659, по 42 988 samples, PIT PASS, 0 нарушений.",
      "Каноническое окно 2022-04-01 → 2026-09-01; OOS оценивает date_to включительно (3 folds, 14 400 предсказаний).",
      "Economics: 36/36 robustness-ячеек; первичный сценарий — ranking V4_FULL, top 20%, 20 сессий, 30 bps/side, EOD → next OPEN, PRICE_RETURN без дивидендов.",
      "Текущий V4_FULL не улучшил OOS-сигнал относительно BASE. Это не winner и не production-ready сигнал.",
      "Production isolation: ACTIVE DatasetSpec остаётся v1, Candidate V0/V1 остаются на Dataset V2. Promotion Candidate нет.",
      "Кампания resumable: recovery прерванных DatasetBuild, live progress.json; progress не входит в semantic identity.",
      "Первый COMPLETE dossier сохранён как immutable audit из-за неполного OOS-окна; канонический итоговый dossier — отдельный fingerprint.",
    ],
    technicalNotes: [
      "Technical VERSION remains 1.0.0. No git tag / GitHub Release for Kraken 1.04.",
      "Canonical dossier fe5609a2ced6082992d923bc57cf99655d73e2787c119564de42bc48803bf233.",
      "Superseded audit dossier caf1d5703aae7c2c008015e82cc1086cf68d0fa71f138eb05eb39bec2a25cd75 (OOS_EVALUATION_BOUNDARY_MISMATCH).",
      "evaluation_end_policy=CAMPAIGN_DATE_TO_INCLUSIVE; development_end_exclusive=2026-09-02.",
      "Ablation mean rank IC: BASE +0.0138; BASE+FUNDAMENTALS +0.0010; BASE+EVENTS −0.0134; V4_FULL −0.0106.",
      "Primary economics: strategy −30.28% vs eligible-universe EW −28.25%; max DD −41.17% / −40.05%.",
      "PIT_DAILY_CORE_ACTIVE_VERSION=1; Candidate V0/V1 dataset_spec_version=2; persist_registry=false.",
    ],
  },
  {
    version: "1.03",
    displayVersion: "Kraken 1.03",
    title: "Память решений и проверка рекомендаций",
    date: "2026-09-30",
    summary:
      "Kraken теперь умеет явно сохранять показанное пользователю Daily Decision и наблюдать, что происходило после него. История решений остаётся advisory: сохранение рекомендации не создаёт сделку и не меняет реальный портфель.",
    highlights: [
      "История Daily Decision",
      "5 / 20 / 60 торговых сессий",
      "Связь с фактическими операциями",
      "Immutable recommendation snapshots",
      "Честная provenance котировок",
    ],
    whatsNew: [
      "Добавлена Personal Decision Memory: пользователь может явно нажать «Зафиксировать решение» и сохранить текущую рекомендацию Kraken.",
      "Сохраняется именно то Daily Decision, которое было показано пользователю: deterministic fingerprint защищает от незаметного сохранения уже изменившегося решения.",
      "История решений хранится отдельно в Memory DB и не изменяет Personal Portfolio, кэш, contributed capital или журнал операций.",
      "Для действий фиксируется доступная на момент решения ценовая evidence с provenance источника и торговой сессии.",
      "Kraken отслеживает результат после 5, 20 и 60 торговых сессий.",
      "V1 использует PRICE_RETURN. В интерфейсе честно указано, что дивиденды не включены.",
      "Возможные совпадения рекомендации с фактическими PersonalOperation показываются как POSSIBLE_MATCH и не считаются причинной связью автоматически.",
      "Связь рекомендации с фактической операцией появляется только после явного подтверждения пользователя.",
      "PREVIOUS_CLOSE теперь относится к реальной предыдущей торговой сессии, а не к дате текущего board context.",
      "Усилена reproducibility: сохранённые решения, baseline evidence и outcomes не переписываются последующими изменениями портфеля, Candidate или FeeProfile.",
      "В репозитории закреплён zero-memory operating protocol Kraken, чтобы новый AI/agent мог корректно продолжить разработку без истории старого чата.",
    ],
  },
  {
    version: "1.02",
    displayVersion: "Kraken 1.02",
    title: "Портфель, комиссии и Shadow Realism",
    date: "2026-09-29",
    summary:
      "Существенно обновлены персональный портфель, Daily Decision и Shadow-контур. Kraken остаётся advisory-системой и не совершает реальные брокерские сделки самостоятельно.",
    highlights: [
      "Daily Decision с учётом комиссий",
      "Брокерские тарифы FeeEngine",
      "Shadow Realism V3",
      "Decision Journal",
      "Честные котировки фондов",
    ],
    whatsNew: [
      "Dataset V3 получил отдельный research evaluation-контур без автоматического переключения production Candidate.",
      "Daily Decision V2 теперь учитывает фактический Personal Portfolio, кэш, текущие позиции, Candidate Kraken, новый капитал, лоты и брокерские комиссии.",
      "Исправлена текущая оценка MOEX-фондов SBFR, SBMM, SBRB и FLOW.",
      "Добавлены BrokerAccount, FeeProfile и FeeRule для моделирования реальных брокерских тарифов.",
      "Добавлен профиль СберИнвестиции «Инвестиционный» и поддержка инструментальных правил комиссии.",
      "Daily Decision учитывает комиссии при расчёте доступных лотов и остатка кэша.",
      "Добавлен Shadow Realism V3.",
      "Выход бумаги за exit-band теперь вызывает REVIEW, а не автоматическую продажу.",
      "ROTATE выполняется только при достаточном экономическом преимуществе после комиссий и slippage.",
      "REVIEW_HOLD и DATA_HOLD защищены от скрытой продажи через перераспределение весов.",
      "Shadow gate, lot planner и fills используют согласованную FeeEngine-семантику.",
      "Неизвестная комиссия больше не считается нулевой.",
      "Добавлен Shadow Decision Journal с историей решений, кандидатов, orders, fills и modeled costs.",
      "Старые Shadow V1/V2 не переписываются и не получают выдуманный исторический decision trace.",
      "Улучшена работа Personal Portfolio с текущими ценами, себестоимостью и P&L.",
      "Усилена надёжность API/frontend и CI.",
    ],
  },
  {
    version: "1.01",
    displayVersion: "Kraken 1.01",
    title:
      "Kraken стал персональным инвестиционным контуром с несколькими портфелями и более сильной исследовательской базой",
    date: "2026-09-28",
    summary:
      "V1.01 — крупный внутренний шаг от набора отдельных аналитических экранов к Kraken Brain: система уже лучше понимает конкретный пользовательский портфель, умеет рассуждать о новом капитале и одновременно получила более строгую исследовательскую инфраструктуру для будущего обучения моделей.",
    highlights: [],
    whatsNew: [
      "Добавили Multi-Portfolio V2: теперь можно создавать несколько независимых пользовательских портфелей, переключаться между ними, переименовывать, удалять, очищать и вести каждый отдельно.",
      "Разделили настройку портфеля и реальный учёт: DRAFT позволяет спокойно собрать начальный состав, ACTIVE ведёт финансовую историю через журнал операций.",
      "Усилили финансовую корректность портфеля: пополнения не считаются прибылью, неизвестная себестоимость не превращается в фиктивный P&L, улучшена изоляция портфелей и защита конкурентных операций.",
      "Добавили светлую и тёмную темы Kraken и доработали интерфейс управления портфелями.",
      "Развили Daily Decision до V2: Kraken теперь умеет анализировать новый капитал, например 30 000 ₽, не изменяя реальный портфель.",
      "Для нового капитала появились сценарии: ничего не делать, оставить деньги кэшем, направить их в недовесы портфеля, использовать текущий план Kraken или рассмотреть fixed-income как отдельный ориентир.",
      "Распределение нового капитала теперь считается в реальных рублёвых недовесах к целевым весам, с учётом цен, лотов, остаточного кэша и доступности данных.",
      "Разделили целевой объём, реально рассчитываемый объём по лотам и advisory-only идеи. Kraken больше не показывает исследовательский ориентир так, будто сделка уже исполнима.",
      "Добавили контроль свежести Candidate: устаревший или неподтверждённый кандидат не может использоваться для точного плана покупок.",
      "Dataset V3 получил полноценный research-контур для сравнения с Dataset V2: покрытие, исторический universe, inactive-инструменты, PIT-качество, hashes и другие диагностические метрики.",
      "Добавили экспериментальное V2↔V3 OOS-сравнение моделей без переключения production Candidate на Dataset V3.",
      "Закрыли временную утечку в OOS-исследовании: обучающая выборка больше не может использовать forward-label, который пересекает начало тестового периода.",
      "Research-сравнение Dataset V2/V3 больше не может случайно изменить активную production-версию DatasetSpec.",
      "Dataset V3 остаётся строго research-only. Production Candidate продолжает работать на Dataset V2, а пользовательские решения не получают экспериментальные V3-сигналы автоматически.",
      "Исправили неоднозначность состояний Research Cycle FAILED/BLOCKED и сделали исследовательский цикл стабильнее.",
      "Продолжили сводить пользовательскую аналитику к единому Personal Portfolio source of truth.",
    ],
  },
  {
    version: "1.0.0",
    displayVersion: "Kraken V1.0",
    title: "First Release",
    date: "2026-09-27",
    gitTag: "v1.0.0",
    releaseCommitSha: "b815b1ae389e18c0c1a2a922007e543f214d9fde",
    summary:
      "Первый зафиксированный рабочий релиз Kraken — персональной инвестиционно-аналитической системы для российского рынка.",
    highlights: [
      "Анализ портфеля",
      "Рекомендации по действиям",
      "Восстановление Shadow после простоя",
      "Догон рыночных данных MOEX",
      "Режимы USER / OWNER",
      "Desktop-кабинет",
    ],
    whatsNew: [
      "Сборка портфеля и ребаланс — сразу видно, как распределить капитал по позициям с учётом лотов MOEX.",
      "Карточки рекомендаций с объяснениями — понятный контекст на доступных данных, без «магии модели».",
      "Автоматический догон рынка после простоя — Kraken сам подтягивает пропущенные торговые дни MOEX.",
      "Виртуальные Shadow-портфели — решения и сделки без реальных денег, с честным восстановлением день за днём.",
      "Тёмный desktop-кабинет и режимы USER / OWNER — разный уровень детализации интерфейса (не production-логин).",
      "Экран покрытия данных для владельца — честно видно, где данные READY, а где ещё PARTIAL.",
    ],
    technicalNotes: [
      "Market recovery сравнивает local complete EOD с expected completed MOEX session.",
      "Shadow catch-up: Forward as-of по сессиям, idempotent replay.",
      "Presentation role: localStorage kraken.presentationRole (не IAM).",
    ],
  },
];

export function currentRelease(): KrakenReleaseNotes {
  return (
    KRAKEN_RELEASES.find((r) => r.version === KRAKEN_PRODUCT_VERSION) ??
    KRAKEN_RELEASES[0]
  );
}

export const KRAKEN_DISPLAY_VERSION = currentRelease().displayVersion;
