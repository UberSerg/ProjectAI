import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DashboardPage } from "./DashboardPage";

describe("DashboardPage", () => {
  it("renders ERROR states when backend is unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("network down")),
    );

    render(<DashboardPage />);
    expect(screen.getByText("ProjectAI Dashboard")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getAllByText("ERROR").length).toBeGreaterThanOrEqual(1);
    });
  });
});
