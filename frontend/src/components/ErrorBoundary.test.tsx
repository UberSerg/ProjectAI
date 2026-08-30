import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

vi.mock("../api/system", () => ({
  reportClientError: vi.fn().mockResolvedValue(undefined),
}));

function Boom(): never {
  throw new Error("boom");
}

describe("ErrorBoundary", () => {
  it("shows friendly fallback instead of blank screen", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <MemoryRouter>
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>
      </MemoryRouter>,
    );

    expect(screen.getByText("Не удалось открыть раздел")).toBeInTheDocument();
    expect(screen.getByText(/технологический журнал/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "На главную" })).toBeInTheDocument();

    spy.mockRestore();
  });
});
