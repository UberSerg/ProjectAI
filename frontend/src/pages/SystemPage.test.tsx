import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as systemApi from "../api/system";
import { SystemPage } from "./SystemPage";

vi.mock("../api/system");

function mockOverview() {
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
  vi.mocked(systemApi.getTechEvents).mockResolvedValue([]);
}

describe("SystemPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows mapped DB labels and not_monitored scheduler", async () => {
    mockOverview();

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

  it("opens diagnostics tab with technology journal", async () => {
    mockOverview();
    vi.mocked(systemApi.getTechEvents).mockResolvedValue([
      {
        id: "1",
        timestamp: "2026-08-30T12:00:00Z",
        level: "ERROR",
        component: "frontend",
        event_type: "frontend_runtime_error",
        message: "boom",
      },
    ]);

    render(
      <MemoryRouter>
        <SystemPage />
      </MemoryRouter>,
    );

    await screen.findByText("Основная БД");
    fireEvent.click(screen.getByRole("button", { name: "Диагностика" }));
    expect(await screen.findByRole("heading", { name: /Технологический журнал/i })).toBeInTheDocument();
    expect(await screen.findByText("boom")).toBeInTheDocument();
  });

  it("opens diagnostics modal and auto-copies report", async () => {
    mockOverview();
    vi.mocked(systemApi.getDiagnosticsText).mockResolvedValue(
      "ProjectAI Diagnostic Report\n=== HEALTH ===\nok",
    );
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText },
    });

    render(
      <MemoryRouter>
        <SystemPage />
      </MemoryRouter>,
    );

    await screen.findByText("Основная БД");
    fireEvent.click(screen.getByRole("button", { name: "Скопировать диагностический отчёт" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByDisplayValue(/ProjectAI Diagnostic Report/)).toBeInTheDocument();
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    expect(screen.getByText("Диагностический отчёт скопирован")).toBeInTheDocument();
  });

  it("shows clipboard fallback when auto-copy fails", async () => {
    mockOverview();
    vi.mocked(systemApi.getDiagnosticsText).mockResolvedValue("report body");
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: {
        writeText: vi.fn().mockRejectedValue(new Error("denied")),
      },
    });

    render(
      <MemoryRouter>
        <SystemPage />
      </MemoryRouter>,
    );

    await screen.findByText("Основная БД");
    fireEvent.click(screen.getByRole("button", { name: "Скопировать диагностический отчёт" }));

    expect(await screen.findByText(/Автокопирование недоступно/i)).toBeInTheDocument();
    expect(screen.getByDisplayValue("report body")).toBeInTheDocument();
  });
});
