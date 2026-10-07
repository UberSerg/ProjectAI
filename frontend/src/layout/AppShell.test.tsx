import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { KrakenRoleProvider } from "../role/KrakenRoleContext";
import { ROLE_STORAGE_KEY } from "../role/types";
import { THEME_STORAGE_KEY } from "../theme/theme";
import { initKrakenTheme } from "../theme/useKrakenTheme";
import { AppShell } from "./AppShell";

function renderShell(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <KrakenRoleProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="*" element={<div>page</div>} />
          </Route>
        </Routes>
      </KrakenRoleProvider>
    </MemoryRouter>,
  );
}

describe("AppShell investor-first nav", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem(ROLE_STORAGE_KEY, "OWNER");
    initKrakenTheme();
  });

  it("includes research-hub, portfolios, candidate, bonds, companies/fundamentals", () => {
    renderShell();
    const nav = screen.getByTestId("primary-nav");
    expect(nav.querySelector('a[href="/research-hub"]')).toBeTruthy();
    expect(nav.querySelector('a[href="/portfolio"]')).toBeTruthy();
    expect(nav.querySelector('a[href="/portfolio/candidate"]')).toBeTruthy();
    expect(nav.querySelector('a[href="/instruments"]')).toBeTruthy();
    expect(nav.querySelector('a[href="/bonds"]')).toBeTruthy();
    expect(nav.querySelector('a[href="/fundamentals"]')).toBeTruthy();
    expect(nav.querySelector('a[href="/investment-decision"]')).toBeTruthy();
    expect(nav.querySelector('a[href="/calibration"]')).toBeTruthy();
  });

  it("puts portfolios manager first under portfolio group", () => {
    renderShell();
    const nav = screen.getByTestId("primary-nav");
    const links = [...nav.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    const portfolios = links.indexOf("/portfolio");
    const candidate = links.indexOf("/portfolio/candidate");
    expect(portfolios).toBeGreaterThanOrEqual(0);
    expect(candidate).toBeGreaterThan(portfolios);
  });

  it("does not list analytics, technical, relations, allocation as primary links", () => {
    renderShell();
    const nav = screen.getByTestId("primary-nav");
    expect(nav.querySelector('a[href="/analytics"]')).toBeNull();
    expect(nav.querySelector('a[href="/technical"]')).toBeNull();
    expect(nav.querySelector('a[href="/relations"]')).toBeNull();
    expect(nav.querySelector('a[href="/allocation"]')).toBeNull();
  });

  it("uses wide main layout without artificial reading max-width", () => {
    renderShell("/portfolio/candidate");
    const main = screen.getByTestId("app-main");
    expect(main).toHaveAttribute("data-layout", "wide");
    expect(main.className.split(/\s+/)).toEqual(expect.arrayContaining(["content", "content-wide"]));
    expect(main.className).not.toMatch(/content-reading|page-layout-reading/);
  });

  it("shows Kraken 1.04 version entry in sidebar footer", () => {
    renderShell();
    const entry = screen.getByTestId("version-entry");
    expect(entry).toHaveTextContent("Kraken 1.04");
    expect(entry).toHaveAttribute("href", "/about");
  });
});

describe("AppShell theme wiring", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem(ROLE_STORAGE_KEY, "OWNER");
    initKrakenTheme();
  });

  it("marks the theme on the document root instead of hardcoding it on the shell", () => {
    renderShell();
    const shell = document.querySelector('[data-product="kraken-personal-v1"]');
    expect(shell).not.toBeNull();
    expect(shell).not.toHaveAttribute("data-theme");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("offers the theme switch next to the version entry and role switch", () => {
    renderShell();
    const footer = screen.getByTestId("version-entry").parentElement;
    expect(footer).toContainElement(screen.getByTestId("theme-switch"));
    expect(footer).toContainElement(screen.getByTestId("role-mode-switch"));
  });

  it("keeps the selected theme when the presentation role changes", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    initKrakenTheme();
    renderShell();

    fireEvent.click(screen.getByTestId("role-switch-user"));

    expect(screen.getByTestId("primary-nav")).toHaveAttribute("data-role", "USER");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });
});

