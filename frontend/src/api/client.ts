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

const FIELD_LABELS: Record<string, string> = {
  name: "Название",
  description: "Описание",
  cash_rub: "Кэш",
  instrument_id: "Инструмент",
  units: "Количество",
  lots: "Лоты",
  average_price: "Средняя цена",
  amount: "Сумма",
  price: "Цена",
  operation_type: "Тип операции",
  occurred_at: "Дата операции",
};

function fieldLabel(loc: unknown): string | null {
  if (!Array.isArray(loc) || loc.length === 0) return null;
  const leaf = loc[loc.length - 1];
  if (typeof leaf !== "string" || leaf === "body") return null;
  return FIELD_LABELS[leaf] ?? leaf;
}

function formatValidationItem(item: unknown): string | null {
  if (typeof item !== "object" || item === null) return null;
  const row = item as { loc?: unknown; msg?: unknown };
  const msg = typeof row.msg === "string" ? row.msg.trim() : "";
  if (!msg) return null;
  const label = fieldLabel(row.loc);
  return label ? `${label}: ${msg}` : msg;
}

/**
 * Extract a human-readable message from a FastAPI / domain error payload.
 * Never returns JS object coercion like "[object Object]".
 */
export function extractBackendErrorMessage(payload: unknown, status?: number): string {
  const fallback = typeof status === "number" && status > 0 ? `Ошибка запроса (${status})` : "Ошибка запроса";

  if (typeof payload === "string") {
    const trimmed = payload.trim();
    return trimmed || fallback;
  }

  if (typeof payload !== "object" || payload === null) {
    return fallback;
  }

  const detail =
    "detail" in payload ? (payload as { detail: unknown }).detail : payload;

  if (typeof detail === "string") {
    const trimmed = detail.trim();
    return trimmed || fallback;
  }

  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => formatValidationItem(item))
      .filter((part): part is string => !!part);
    if (parts.length > 0) return parts.join("; ");
    return fallback;
  }

  if (typeof detail === "object" && detail !== null) {
    const row = detail as { message?: unknown; code?: unknown };
    if (typeof row.message === "string" && row.message.trim()) return row.message.trim();
    if (typeof row.code === "string" && row.code.trim()) return row.code.trim();
    return fallback;
  }

  return fallback;
}

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
    throw new ApiError(extractBackendErrorMessage(payload, response.status), response.status, payload);
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
    if (error.details !== undefined) {
      const extracted = extractBackendErrorMessage(error.details, error.status);
      if (extracted && !extracted.includes("[object Object]")) {
        return userSafeMessage(extracted);
      }
    }
    const message = typeof error.message === "string" ? error.message : "Ошибка запроса";
    return userSafeMessage(message.includes("[object Object]") ? `Ошибка запроса (${error.status || "?"})` : message);
  }
  return userSafeMessage(error instanceof Error ? error.message : "Unexpected error");
}
