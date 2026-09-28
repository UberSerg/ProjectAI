/** Visual theme of the Kraken UI. Independent from the presentation role (separate storage keys). */
export type KrakenTheme = "light" | "dark";

/** Keep in sync with the inline pre-paint init in index.html. */
export const THEME_STORAGE_KEY = "kraken.theme";

export const DEFAULT_THEME: KrakenTheme = "dark";

export const THEME_ORDER: readonly KrakenTheme[] = ["light", "dark"];

export const THEME_LABELS: Record<KrakenTheme, string> = {
  light: "Светлая",
  dark: "Тёмная",
};

export function normalizeTheme(raw: unknown): KrakenTheme {
  return raw === "light" || raw === "dark" ? raw : DEFAULT_THEME;
}

export function readStoredTheme(): KrakenTheme {
  try {
    return normalizeTheme(localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return DEFAULT_THEME;
  }
}

export function writeStoredTheme(theme: KrakenTheme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* storage unavailable — theme still applies for this session */
  }
}

/** Root marker for CSS tokens plus the native form/scrollbar scheme. */
export function applyThemeToDocument(theme: KrakenTheme): void {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
}
