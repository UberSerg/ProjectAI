import { render, screen } from "@testing-library/react";
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

  it("USER sees simple V1.0 view without owner build metadata", () => {
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
    expect(screen.getByTestId("about-whats-new")).toBeInTheDocument();
    expect(screen.queryByTestId("about-owner-meta")).not.toBeInTheDocument();
  });

  it("OWNER sees semver and build metadata block", () => {
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
  });
});
