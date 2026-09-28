const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type RequestOptions = Omit<RequestInit, "body"> & { body?: unknown };

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body !== undefined) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/v1${path}`, {
      ...options,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(error instanceof Error ? error.message : "Network request failed", 0);
  }

  const contentType = response.headers.get("content-type") ?? "";
  const payload: unknown = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const message =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? String(payload.detail)
        : `Request failed (${response.status})`;
    throw new ApiError(message, response.status, payload);
  }
  return payload as T;
}

export function queryString(values: Record<string, string | number | boolean | undefined>): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

/** USER-facing copy for the retired single-portfolio endpoints. */
export const PORTFOLIO_RELOAD_MESSAGE =
  "Не удалось загрузить выбранный портфель. Обновите страницу.";

const RETIRED_PORTFOLIO_PATTERNS = [
  /PRIMARY_RETIRED/i,
  /manual-portfolios\/primary/i,
  /personal-portfolios\/primary/i,
  /singleton/i,
  /getPersonalPrimary/i,
  /activatePersonalJournal/i,
];

function safeStringify(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value) ?? "";
  } catch {
    return "";
  }
}

function mentionsRetiredPortfolio(raw: string): boolean {
  return RETIRED_PORTFOLIO_PATTERNS.some((re) => re.test(raw));
}

/** Retired-endpoint internals must never reach USER copy. */
function userSafeMessage(raw: string): string {
  return mentionsRetiredPortfolio(raw) ? PORTFOLIO_RELOAD_MESSAGE : raw;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (mentionsRetiredPortfolio(`${error.message} ${safeStringify(error.details)}`)) {
      return PORTFOLIO_RELOAD_MESSAGE;
    }
    const details = error.details;
    if (typeof details === "object" && details !== null && "detail" in details) {
      const detail = (details as { detail: unknown }).detail;
      if (typeof detail === "object" && detail !== null) {
        const row = detail as { message?: unknown; code?: unknown };
        if (typeof row.message === "string" && row.message.trim()) return userSafeMessage(row.message);
        if (typeof row.code === "string" && row.code.trim()) return userSafeMessage(row.code);
      }
      if (typeof detail === "string") return userSafeMessage(detail);
    }
    return typeof error.message === "string" ? userSafeMessage(error.message) : "Ошибка запроса";
  }
  return userSafeMessage(error instanceof Error ? error.message : "Unexpected error");
}
