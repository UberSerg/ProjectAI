import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AppShell } from "./AppShell";

function renderShell(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="*" element={<div>page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppShell investor-first nav", () => {
  it("includes research-hub, candidate, bonds, companies/fundamentals", () => {
    renderShell();
    const nav = screen.getByTestId("primary-nav");
    expect(nav.querySelector('a[href="/research-hub"]')).toBeTruthy();
    expect(nav.querySelector('a[href="/portfolio/candidate"]')).toBeTruthy();
    expect(nav.querySelector('a[href="/bonds"]')).toBeTruthy();
    expect(nav.querySelector('a[href="/fundamentals"]')).toBeTruthy();
    expect(nav.querySelector('a[href="/investment-decision"]')).toBeTruthy();
    expect(nav.querySelector('a[href="/calibration"]')).toBeTruthy();
  });

  it("does not list analytics, technical, relations, allocation as primary links", () => {
    renderShell();
    const nav = screen.getByTestId("primary-nav");
    expect(nav.querySelector('a[href="/analytics"]')).toBeNull();
    expect(nav.querySelector('a[href="/technical"]')).toBeNull();
    expect(nav.querySelector('a[href="/relations"]')).toBeNull();
    expect(nav.querySelector('a[href="/allocation"]')).toBeNull();
    expect(nav.querySelector('a[href="/portfolio"]')).toBeNull();
  });
});
