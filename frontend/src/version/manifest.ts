/** Static version history for in-app «О Kraken». Not a CMS. */

export interface KrakenReleaseNotes {
  version: string;
  displayVersion: string;
  title: string;
  date: string;
  summary: string;
  highlights: string[];
  whatsNew: string[];
}

/** Keep in sync with root VERSION / CHANGELOG.md on each official release. */
export const KRAKEN_VERSION =
  (import.meta.env.VITE_KRAKEN_VERSION as string | undefined)?.trim() || "1.0.0";

export const KRAKEN_DISPLAY_VERSION = `Kraken V${KRAKEN_VERSION.split(".").slice(0, 2).join(".")}`;

export const KRAKEN_RELEASES: KrakenReleaseNotes[] = [
  {
    version: "1.0.0",
    displayVersion: "Kraken V1.0",
    title: "First Release",
    date: "2026-09-27",
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
      "Сборка портфеля, ребаланс и карточки рекомендаций с объяснениями",
      "Загрузка дневных котировок MOEX и автодогон после нескольких дней простоя",
      "Виртуальные Shadow-портфели с честным восстановлением день за днём",
      "Тёмный desktop-кабинет и простые/расширенные режимы интерфейса",
      "Диагностика для владельца и экран покрытия данных",
    ],
  },
];

export function currentRelease(): KrakenReleaseNotes {
  return (
    KRAKEN_RELEASES.find((r) => r.version === KRAKEN_VERSION) ?? KRAKEN_RELEASES[0]
  );
}
