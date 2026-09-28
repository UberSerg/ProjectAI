import { useCallback, useEffect, useSyncExternalStore } from "react";
import {
  applyThemeToDocument,
  normalizeTheme,
  readStoredTheme,
  writeStoredTheme,
  type KrakenTheme,
} from "./theme";

/**
 * Tiny module-level store instead of a provider: the theme is a single global
 * document-level concern, so every consumer must see the same value without
 * depending on where it sits in the React tree.
 */
const listeners = new Set<() => void>();
let current: KrakenTheme | null = null;

function emit(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getKrakenTheme(): KrakenTheme {
  return current ?? readStoredTheme();
}

export function setKrakenTheme(next: KrakenTheme): void {
  const theme = normalizeTheme(next);
  current = theme;
  applyThemeToDocument(theme);
  writeStoredTheme(theme);
  emit();
}

/** Early init before the first React render, and re-sync from storage. */
export function initKrakenTheme(): KrakenTheme {
  const theme = readStoredTheme();
  current = theme;
  applyThemeToDocument(theme);
  emit();
  return theme;
}

export interface KrakenThemeApi {
  theme: KrakenTheme;
  setTheme: (theme: KrakenTheme) => void;
  toggleTheme: () => void;
}

export function useKrakenTheme(): KrakenThemeApi {
  const theme = useSyncExternalStore(subscribe, getKrakenTheme, getKrakenTheme);

  useEffect(() => {
    applyThemeToDocument(theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setKrakenTheme(getKrakenTheme() === "dark" ? "light" : "dark");
  }, []);

  return { theme, setTheme: setKrakenTheme, toggleTheme };
}
