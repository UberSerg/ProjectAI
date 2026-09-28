import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ThemeSwitch } from "./ThemeSwitch";
import { DEFAULT_THEME, THEME_STORAGE_KEY, normalizeTheme, readStoredTheme } from "./theme";
import { getKrakenTheme, initKrakenTheme } from "./useKrakenTheme";

function root() {
  return document.documentElement;
}

describe("kraken theme resolution", () => {
  beforeEach(() => {
    localStorage.clear();
    root().removeAttribute("data-theme");
    root().style.colorScheme = "";
  });

  it("falls back to dark when nothing is stored", () => {
    expect(DEFAULT_THEME).toBe("dark");
    expect(readStoredTheme()).toBe("dark");
    expect(initKrakenTheme()).toBe("dark");
    expect(root().dataset.theme).toBe("dark");
  });

  it("keeps a stored dark theme", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    expect(readStoredTheme()).toBe("dark");
    expect(initKrakenTheme()).toBe("dark");
  });

  it("restores a stored light theme", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    expect(readStoredTheme()).toBe("light");
    expect(initKrakenTheme()).toBe("light");
    expect(root().dataset.theme).toBe("light");
    expect(root().style.colorScheme).toBe("light");
  });

  it("falls back to dark for invalid stored values", () => {
    for (const raw of ["", "solarized", "LIGHT", "null"]) {
      localStorage.setItem(THEME_STORAGE_KEY, raw);
      expect(readStoredTheme()).toBe("dark");
    }
    expect(normalizeTheme(undefined)).toBe("dark");
    expect(normalizeTheme(42)).toBe("dark");
    expect(normalizeTheme("light")).toBe("light");
  });
});

describe("ThemeSwitch", () => {
  beforeEach(() => {
    localStorage.clear();
    initKrakenTheme();
  });

  it("marks the current theme as selected and exposes both options", () => {
    render(<ThemeSwitch />);
    expect(screen.getByTestId("theme-switch")).toHaveAttribute("data-theme-value", "dark");
    expect(screen.getByTestId("theme-switch-dark")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("theme-switch-dark")).toHaveClass("active");
    expect(screen.getByTestId("theme-switch-light")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Светлая" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Тёмная" })).toBeInTheDocument();
  });

  it("writes the document root marker when switching", () => {
    render(<ThemeSwitch />);
    fireEvent.click(screen.getByTestId("theme-switch-light"));
    expect(root().dataset.theme).toBe("light");
    expect(root().style.colorScheme).toBe("light");
    expect(screen.getByTestId("theme-switch-light")).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByTestId("theme-switch-dark"));
    expect(root().dataset.theme).toBe("dark");
    expect(root().style.colorScheme).toBe("dark");
  });

  it("persists the choice in localStorage", () => {
    render(<ThemeSwitch />);
    fireEvent.click(screen.getByTestId("theme-switch-light"));
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(getKrakenTheme()).toBe("light");

    fireEvent.click(screen.getByTestId("theme-switch-dark"));
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("does not touch the presentation role key", () => {
    localStorage.setItem("kraken.presentationRole", "OWNER");
    render(<ThemeSwitch />);
    fireEvent.click(screen.getByTestId("theme-switch-light"));
    expect(localStorage.getItem("kraken.presentationRole")).toBe("OWNER");
  });
});
