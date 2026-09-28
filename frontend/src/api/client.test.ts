import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  PORTFOLIO_RELOAD_MESSAGE,
  apiRequest,
  errorMessage,
  extractBackendErrorMessage,
} from "./client";
import { createPersonalPortfolio } from "./personalPortfolios";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("extractBackendErrorMessage", () => {
  it("uses a simple FastAPI detail string", () => {
    expect(extractBackendErrorMessage({ detail: "simple" })).toBe("simple");
  });

  it("prefers domain detail.message", () => {
    expect(
      extractBackendErrorMessage({
        detail: { code: "PORTFOLIO_NAME_EXISTS", message: "Портфель с таким названием уже существует." },
      }),
    ).toBe("Портфель с таким названием уже существует.");
  });

  it("humanizes a FastAPI validation array", () => {
    const message = extractBackendErrorMessage({
      detail: [{ loc: ["body", "name"], msg: "Field required", type: "missing" }],
    });
    expect(message).toBe("Название: Field required");
    expect(message).not.toContain("[object Object]");
  });

  it("joins multiple validation entries", () => {
    const message = extractBackendErrorMessage({
      detail: [
        { loc: ["body", "name"], msg: "Field required", type: "missing" },
        { loc: ["body", "description"], msg: "Input should be a valid string", type: "string_type" },
      ],
    });
    expect(message).toContain("Название: Field required");
    expect(message).toContain("Описание: Input should be a valid string");
    expect(message).not.toContain("[object Object]");
  });

  it("falls back for unknown object detail", () => {
    expect(extractBackendErrorMessage({ detail: { weird: true } }, 422)).toBe("Ошибка запроса (422)");
  });

  it("keeps plain text backend responses", () => {
    expect(extractBackendErrorMessage("backend exploded", 500)).toBe("backend exploded");
  });
});

describe("errorMessage regression matrix", () => {
  it("handles simple detail", () => {
    expect(errorMessage(new ApiError("x", 400, { detail: "simple" }))).toBe("simple");
  });

  it("handles domain detail", () => {
    expect(
      errorMessage(
        new ApiError("x", 409, {
          detail: { code: "PORTFOLIO_NAME_EXISTS", message: "Портфель с таким названием уже существует." },
        }),
      ),
    ).toBe("Портфель с таким названием уже существует.");
  });

  it("handles validation array without [object Object]", () => {
    const message = errorMessage(
      new ApiError("[object Object]", 422, {
        detail: [{ loc: ["body", "name"], msg: "Field required", type: "missing" }],
      }),
    );
    expect(message).toBe("Название: Field required");
    expect(message).not.toContain("[object Object]");
  });

  it("handles unknown object detail", () => {
    expect(errorMessage(new ApiError("[object Object]", 422, { detail: { weird: 1 } }))).toBe(
      "Ошибка запроса (422)",
    );
  });

  it("handles plain text payload", () => {
    expect(errorMessage(new ApiError("plain", 500, "plain failure"))).toBe("plain failure");
  });

  it("handles network errors", () => {
    expect(errorMessage(new ApiError("Failed to fetch", 0))).toBe("Failed to fetch");
  });

  it("maps retired singleton message to safe portfolio reload copy", () => {
    expect(
      errorMessage(
        new ApiError("Request failed (410)", 410, {
          detail: { code: "PRIMARY_RETIRED", message: "Singleton portfolio retired" },
        }),
      ),
    ).toBe(PORTFOLIO_RELOAD_MESSAGE);
  });

  it("keeps a plain backend message", () => {
    expect(errorMessage(new ApiError("Портфель не найден", 404))).toBe("Портфель не найден");
  });

  it("maps the retired endpoint path to USER copy", () => {
    expect(errorMessage(new Error("/manual-portfolios/primary retired"))).toBe(PORTFOLIO_RELOAD_MESSAGE);
  });

  it("maps retired singleton helper names to USER copy", () => {
    expect(errorMessage(new Error("getPersonalPrimary retired — use getPersonalPortfolio(id)"))).toBe(
      PORTFOLIO_RELOAD_MESSAGE,
    );
    expect(errorMessage(new Error("activatePersonalJournal retired"))).toBe(PORTFOLIO_RELOAD_MESSAGE);
  });

  it("never leaks retired wording through a nested detail string", () => {
    const message = errorMessage(
      new ApiError("Request failed (410)", 410, {
        detail: "Singleton /manual-portfolios/primary retired",
      }),
    );
    expect(message).toBe(PORTFOLIO_RELOAD_MESSAGE);
    expect(message).not.toMatch(/singleton/i);
    expect(message).not.toMatch(/primary/i);
  });
});

describe("apiRequest body serialization contract", () => {
  it("serializes a raw object body exactly once", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      expect(init?.body).toBe('{"a":1}');
      expect(JSON.parse(String(init?.body))).toEqual({ a: 1 });
      expect(typeof JSON.parse(String(init?.body))).toBe("object");
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/probe", { method: "POST", body: { a: 1 } });
    expect(fetchMock).toHaveBeenCalledOnce();
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("builds ApiError.message from FastAPI validation detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            detail: [{ loc: ["body", "name"], msg: "Field required", type: "missing" }],
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(apiRequest("/probe", { method: "POST", body: {} })).rejects.toMatchObject({
      status: 422,
      message: "Название: Field required",
    });
  });
});

describe("createPersonalPortfolio request body", () => {
  it("sends a JSON object once, not a double-encoded string", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      const raw = String(init?.body);
      const parsed = JSON.parse(raw);
      expect(typeof parsed).toBe("object");
      expect(parsed).toEqual({ name: "Основной", description: "demo" });
      expect(typeof parsed).not.toBe("string");
      return new Response(
        JSON.stringify({
          portfolio: { id: 1, name: "Основной", lifecycle_state: "DRAFT", status: "DRAFT" },
          summary: {},
          positions: [],
          operations: [],
          recommendation_disclaimer: "",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    await createPersonalPortfolio({ name: "Основной", description: "demo" });
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
