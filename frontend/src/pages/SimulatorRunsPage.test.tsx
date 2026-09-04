import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as simulatorApi from "../api/simulator";
import { HelpProvider } from "../help";
import { SimulatorRunsPage } from "./SimulatorRunsPage";

vi.mock("../api/simulator");

function renderRuns() {
  return render(
    <HelpProvider>
      <MemoryRouter initialEntries={["/simulator"]}>
        <Routes>
          <Route path="/simulator" element={<SimulatorRunsPage />} />
        </Routes>
      </MemoryRouter>
    </HelpProvider>,
  );
}

describe("SimulatorRunsPage", () => {
  it("loads runs table with segment badges and links to detail", async () => {
    vi.mocked(simulatorApi.listSimulatorRuns).mockResolvedValue([
      {
        id: 2,
        status: "SUCCESS",
        engineering_status: "PASS",
        segment: "DEVELOPMENT_OOS",
        date_from: "2024-01-02",
        date_to: "2025-12-30",
        candidate_config_hash: "abcdef0123456789",
        metrics: {
          initial_nav: 1_000_000,
          final_nav: 940_000,
          total_price_return: -0.06,
          max_drawdown: -0.12,
        },
        spec: {
          policy_name: "RANK_LONG_ONLY_V0",
          commission_bps: 0,
          initial_capital: 1_000_000,
        },
      },
      {
        id: 3,
        status: "SUCCESS",
        engineering_status: "PASS",
        segment: "FINAL_HOLDOUT",
        date_from: "2026-01-05",
        date_to: "2026-08-06",
        candidate_config_hash: "abcdef0123456789",
        metrics: {
          initial_nav: 1_000_000,
          final_nav: 910_000,
          total_price_return: -0.09,
          max_drawdown: -0.15,
        },
        spec: {
          policy_name: "RANK_LONG_ONLY_V0",
          commission_bps: 0,
          initial_capital: 1_000_000,
        },
      },
    ]);

    renderRuns();
    expect(await screen.findByText("Симуляции")).toBeInTheDocument();
    expect(screen.getByText("DEV OOS")).toBeInTheDocument();
    expect(screen.getByText("HOLDOUT")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /HOLDOUT/i })).toHaveAttribute("href", "/simulator/3");
    expect(screen.getAllByText("abcdef01").length).toBeGreaterThanOrEqual(2);
  });

  it("shows empty and error states", async () => {
    vi.mocked(simulatorApi.listSimulatorRuns).mockResolvedValue([]);
    const { unmount } = renderRuns();
    expect(await screen.findByText(/нет сохранённых прогонов/i)).toBeInTheDocument();
    unmount();

    vi.mocked(simulatorApi.listSimulatorRuns).mockRejectedValue(new Error("offline"));
    renderRuns();
    expect(await screen.findByText("Не удалось получить данные")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("offline")).toBeInTheDocument();
    });
  });
});
