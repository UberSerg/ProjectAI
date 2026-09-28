/** Official Kraken release history for in-app «О Kraken».

Each entry is an immutable snapshot of what that version contained at release time.
Keep in sync with root VERSION / CHANGELOG.md / GitHub Release on each official release.
Missing `date` or human notes = incomplete release.
*/

export interface KrakenReleaseNotes {
  /** SemVer, e.g. 1.0.0 */
  version: string;
  /** Display, e.g. Kraken V1.0 */
  displayVersion: string;
  title: string;
  /**
   * Canonical release date YYYY-MM-DD from official release metadata
   * (GitHub Release published_at / tag). Never invent; never replace on later builds.
   */
  date: string;
  /** Git tag, e.g. v1.0.0 */
  gitTag: string;
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

/** Keep in sync with root VERSION on each official release. */
export const KRAKEN_VERSION =
  (import.meta.env.VITE_KRAKEN_VERSION as string | undefined)?.trim() || "1.0.0";

export const KRAKEN_DISPLAY_VERSION = `Kraken V${KRAKEN_VERSION.split(".").slice(0, 2).join(".")}`;

/**
 * Newest first. Historical entries must keep their own notes forever —
 * never render current changelog under older versions.
 *
 * V1.0 date/tag/commit from GitHub Release `v1.0.0`
 * (published_at 2026-09-27T09:43:33Z, commit b815b1ae…).
 */
export const KRAKEN_RELEASES: KrakenReleaseNotes[] = [
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
    KRAKEN_RELEASES.find((r) => r.version === KRAKEN_VERSION) ?? KRAKEN_RELEASES[0]
  );
}
