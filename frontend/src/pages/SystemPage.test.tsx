import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as systemApi from "../api/system";
import { SystemPage } from "./SystemPage";

vi.mock("../api/system");

describe("SystemPage", () => {
  it("shows mapped DB labels and not_monitored scheduler", async () => {
    vi.mocked(systemApi.getSystemHealth).mockResolvedValue({
      status: "ok",
      services: {
        backend: "ok",
        core_database: "ok",
        memory_database: "ok",
        redis: "ok",
        worker: "ok",
      },
    });
    vi.mocked(systemApi.getSystemInfo).mockResolvedValue({
      name: "ProjectAI",
      version: "0.1.0",
      environment: "local",
      api_version: "v1",
      market_update_enabled: false,
      raw_storage_path: "/data/raw",
    });

    render(
      <MemoryRouter>
        <SystemPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Основная БД")).toBeInTheDocument();
    expect(screen.getByText("База памяти")).toBeInTheDocument();
    expect(screen.getByText("Не контролируется")).toBeInTheDocument();
    expect(screen.getAllByText("Работает").length).toBeGreaterThanOrEqual(4);
  });
});
