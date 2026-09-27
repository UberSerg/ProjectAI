import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../layout/AppShell";
import { navGroupsForRole, pathAllowedForRole } from "../layout/navConfig";
import { KrakenRoleProvider } from "./KrakenRoleContext";
import { ROLE_STORAGE_KEY } from "./types";

vi.mock("../api/system", () => ({
  reportClientError: vi.fn(),
}));

describe("role presentation nav", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("USER nav is short and excludes research/system", () => {
    const groups = navGroupsForRole("USER");
    const labels = groups.flatMap((g) => g.items.map((i) => i.label));
    expect(labels).toEqual(["Обзор", "Портфель", "Решения", "История"]);
    expect(pathAllowedForRole("/shadow", "USER")).toBe(false);
    expect(pathAllowedForRole("/system", "USER")).toBe(false);
    expect(pathAllowedForRole("/portfolio/mine", "USER")).toBe(true);
  });

  it("OWNER keeps technical navigation", () => {
    const labels = navGroupsForRole("OWNER").flatMap((g) => g.items.map((i) => i.label));
    expect(labels).toContain("Живой эксперимент");
    expect(labels).toContain("Система");
    expect(pathAllowedForRole("/shadow", "OWNER")).toBe(true);
  });

  it("role switch persists and changes nav", () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "OWNER");
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <AppShell />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("primary-nav")).toHaveAttribute("data-role", "OWNER");
    expect(screen.getByText("Живой эксперимент")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("role-switch-user"));
    expect(screen.getByTestId("primary-nav")).toHaveAttribute("data-role", "USER");
    expect(screen.queryByText("Живой эксперимент")).not.toBeInTheDocument();
    expect(localStorage.getItem(ROLE_STORAGE_KEY)).toBe("USER");
    expect(screen.getByTestId("role-mode-switch")).toBeInTheDocument();
    expect(screen.getByText(/Режим интерфейса/i)).toBeInTheDocument();
    expect(screen.getByText(/Presentation mode/i)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("role-switch-owner"));
    expect(screen.getByTestId("primary-nav")).toHaveAttribute("data-role", "OWNER");
    expect(localStorage.getItem(ROLE_STORAGE_KEY)).toBe("OWNER");
  });

  it("reload preserves role from localStorage", () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    const { unmount } = render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <AppShell />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("primary-nav")).toHaveAttribute("data-role", "USER");
    unmount();
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <AppShell />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("primary-nav")).toHaveAttribute("data-role", "USER");
    expect(screen.getByTestId("role-switch-user")).toHaveAttribute("aria-pressed", "true");
  });

  it("active role button uses high-contrast selected class", () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "OWNER");
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <AppShell />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("role-switch-owner")).toHaveClass("active");
    expect(screen.getByTestId("role-switch-user")).not.toHaveClass("active");
  });
});
