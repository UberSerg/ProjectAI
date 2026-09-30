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
export const KRAKEN_PRODUCT_VERSION = "1.02";

/**
 * Newest first. Historical entries must keep their own notes forever —
 * never render current changelog under older versions.
 *
 * 1.01 / 1.02 are product micro-releases (no git tag / GitHub Release).
 * 1.01 notes restored from the 28.09.2026 local frontend edit on
 * feature/brain-foundation-v2 (never pushed; lost from main after BFV2 merge).
 * V1.0 date/tag/commit from GitHub Release `v1.0.0`
 * (published_at 2026-09-27T09:43:33Z, commit b815b1ae…).
 */
export const KRAKEN_RELEASES: KrakenReleaseNotes[] = [
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
