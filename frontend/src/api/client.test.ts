import { describe, expect, it } from "vitest";
import { ApiError, PORTFOLIO_RELOAD_MESSAGE, errorMessage } from "./client";

describe("errorMessage", () => {
  it("keeps a plain backend message", () => {
    expect(errorMessage(new ApiError("Портфель не найден", 404))).toBe("Портфель не найден");
  });

  it("prefers a structured detail message", () => {
    const error = new ApiError("Request failed (400)", 400, {
      detail: { code: "LOT_INVALID", message: "Количество должно быть кратно лоту" },
    });
    expect(errorMessage(error)).toBe("Количество должно быть кратно лоту");
  });

  it("maps a PRIMARY_RETIRED code to USER copy", () => {
    const error = new ApiError("Request failed (410)", 410, {
      detail: { code: "PRIMARY_RETIRED", message: "Singleton portfolio retired" },
    });
    expect(errorMessage(error)).toBe(PORTFOLIO_RELOAD_MESSAGE);
  });

  it("maps the retired endpoint path to USER copy", () => {
    expect(errorMessage(new Error("/manual-portfolios/primary retired"))).toBe(
      PORTFOLIO_RELOAD_MESSAGE,
    );
  });

  it("maps retired singleton helper names to USER copy", () => {
    expect(errorMessage(new Error("getPersonalPrimary retired — use getPersonalPortfolio(id)"))).toBe(
      PORTFOLIO_RELOAD_MESSAGE,
    );
    expect(errorMessage(new Error("activatePersonalJournal retired"))).toBe(PORTFOLIO_RELOAD_MESSAGE);
  });

  it("never leaks retired wording through a nested detail string", () => {
    const error = new ApiError("Request failed (410)", 410, {
      detail: "Singleton /manual-portfolios/primary retired",
    });
    const message = errorMessage(error);
    expect(message).toBe(PORTFOLIO_RELOAD_MESSAGE);
    expect(message).not.toMatch(/singleton/i);
    expect(message).not.toMatch(/primary/i);
  });
});
