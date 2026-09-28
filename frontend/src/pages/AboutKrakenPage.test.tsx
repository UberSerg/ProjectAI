import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KrakenRoleProvider } from "../role/KrakenRoleContext";
import { ROLE_STORAGE_KEY } from "../role/types";
import { AboutKrakenPage } from "./AboutKrakenPage";

vi.mock("../api/system", () => ({
  reportClientError: vi.fn(),
}));

describe("AboutKrakenPage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("USER sees V1.0, release date, and can expand history notes", () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <AboutKrakenPage />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("about-display-version")).toHaveTextContent("Kraken V1.0");
    expect(screen.getByTestId("about-release-title")).toHaveTextContent("First Release");
    expect(screen.getByTestId("about-release-date")).toHaveTextContent("27.09.2026");
    expect(screen.getByTestId("about-whats-new")).toBeInTheDocument();
    expect(screen.queryByTestId("about-owner-meta")).not.toBeInTheDocument();

    expect(screen.getByTestId("history-date-1.0.0")).toHaveTextContent("27.09.2026");
    // Current version is expanded by default.
    expect(screen.getByTestId("history-details-1.0.0")).toBeInTheDocument();
    expect(screen.getByTestId("history-whats-new-1.0.0")).toHaveTextContent(
      "Автоматический догон рынка после простоя",
    );
    expect(screen.queryByTestId("history-technical-1.0.0")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("history-toggle-1.0.0"));
    expect(screen.queryByTestId("history-details-1.0.0")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("history-toggle-1.0.0"));
    expect(screen.getByTestId("history-details-1.0.0")).toBeInTheDocument();
  });

  it("OWNER sees semver/tag and technical notes without replacing USER summary", () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "OWNER");
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <AboutKrakenPage />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("about-owner-meta")).toBeInTheDocument();
    expect(screen.getByTestId("about-semver")).toHaveTextContent("1.0.0");
    expect(screen.getByTestId("about-git-tag")).toHaveTextContent("v1.0.0");
    expect(screen.getByTestId("history-summary-1.0.0")).toHaveTextContent(
      "Первый зафиксированный рабочий релиз",
    );
    expect(screen.getByTestId("history-technical-1.0.0")).toBeInTheDocument();
    expect(screen.getByTestId("history-technical-1.0.0").textContent).not.toEqual(
      screen.getByTestId("history-summary-1.0.0").textContent,
    );
  });
});
