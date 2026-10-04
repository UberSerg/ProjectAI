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

  it("USER sees Kraken 1.04, release date, and cumulative history 1.04→1.03→1.02→1.01→V1.0", () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "USER");
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <AboutKrakenPage />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("about-display-version")).toHaveTextContent("Kraken 1.04");
    expect(screen.getByTestId("about-release-date")).toHaveTextContent("04.10.2026");
    expect(screen.getByTestId("about-product-line")).toHaveTextContent("Kraken 1.04");
    expect(screen.queryByTestId("about-owner-meta")).not.toBeInTheDocument();

    const details = screen.getByTestId("about-whats-new");
    expect(details).toBeInTheDocument();
    expect(screen.getByTestId("about-whats-new-summary")).toHaveTextContent("Что нового");
    // Closed by default — open for investor detail.
    fireEvent.click(screen.getByTestId("about-whats-new-summary"));
    expect(screen.getByTestId("about-whats-new-list")).toHaveTextContent(
      "не улучшил OOS-сигнал относительно BASE",
    );
    expect(screen.getByTestId("about-whats-new-list")).toHaveTextContent("42 988");
    expect(screen.getByTestId("about-whats-new-list")).not.toHaveTextContent(
      "Personal Decision Memory",
    );

    expect(screen.getByTestId("history-date-1.04")).toHaveTextContent("04.10.2026");
    expect(screen.getByTestId("history-details-1.04")).toBeInTheDocument();
    expect(screen.getByTestId("history-whats-new-1.04")).toHaveTextContent(
      "не улучшил OOS-сигнал относительно BASE",
    );
    expect(screen.queryByTestId("history-technical-1.04")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("history-toggle-1.03"));
    expect(screen.getByTestId("history-date-1.03")).toHaveTextContent("30.09.2026");
    expect(screen.getByTestId("history-details-1.03")).toBeInTheDocument();
    expect(screen.getByTestId("history-whats-new-1.03")).toHaveTextContent(
      "Personal Decision Memory",
    );
    expect(screen.queryByTestId("history-technical-1.03")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("history-toggle-1.02"));
    expect(screen.getByTestId("history-details-1.02")).toBeInTheDocument();
    expect(screen.getByTestId("history-date-1.02")).toHaveTextContent("29.09.2026");
    expect(screen.getByTestId("history-whats-new-1.02")).toHaveTextContent("Shadow Decision Journal");
    expect(screen.getByTestId("history-whats-new-1.02")).not.toHaveTextContent(
      "Personal Decision Memory",
    );

    fireEvent.click(screen.getByTestId("history-toggle-1.01"));
    expect(screen.getByTestId("history-details-1.01")).toBeInTheDocument();
    expect(screen.getByTestId("history-date-1.01")).toHaveTextContent("28.09.2026");
    expect(screen.getByTestId("history-whats-new-1.01")).toHaveTextContent("Multi-Portfolio V2");
    expect(screen.getByTestId("history-whats-new-1.01")).not.toHaveTextContent(
      "Shadow Realism V3",
    );

    fireEvent.click(screen.getByTestId("history-toggle-1.0.0"));
    expect(screen.getByTestId("history-details-1.0.0")).toBeInTheDocument();
    expect(screen.getByTestId("history-whats-new-1.0.0")).toHaveTextContent(
      "Автоматический догон рынка после простоя",
    );
    expect(screen.getByTestId("history-whats-new-1.0.0")).not.toHaveTextContent(
      "Shadow Realism V3",
    );
  });

  it("OWNER sees technical VERSION 1.0.0 without replacing product notes", () => {
    localStorage.setItem(ROLE_STORAGE_KEY, "OWNER");
    render(
      <MemoryRouter>
        <KrakenRoleProvider>
          <AboutKrakenPage />
        </KrakenRoleProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("about-display-version")).toHaveTextContent("Kraken 1.04");
    expect(screen.getByTestId("about-owner-meta")).toBeInTheDocument();
    expect(screen.getByTestId("about-semver")).toHaveTextContent("1.0.0");
    expect(screen.getByTestId("about-product-version")).toHaveTextContent("1.04");
    expect(screen.getByTestId("about-git-tag")).toHaveTextContent("v1.0.0");
    expect(screen.getByTestId("history-summary-1.04")).toHaveTextContent(
      "не улучшает OOS-сигнал относительно BASE",
    );
    fireEvent.click(screen.getByTestId("history-toggle-1.03"));
    expect(screen.getByTestId("history-summary-1.03")).toHaveTextContent(
      "явно сохранять показанное пользователю Daily Decision",
    );
    fireEvent.click(screen.getByTestId("history-toggle-1.02"));
    expect(screen.getByTestId("history-summary-1.02")).toHaveTextContent(
      "персональный портфель, Daily Decision и Shadow-контур",
    );
  });
});
