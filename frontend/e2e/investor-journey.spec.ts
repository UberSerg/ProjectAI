/**
 * Deterministic Playwright investor-journey slice (isolated E2E fixture only).
 *
 * Fail closed unless an explicit fixture id is provided and verified:
 *   E2E_PORTFOLIO_ID=<id>
 *   Portfolio must have source=DEMO_INVESTOR_JOURNEY_V1 (durable DEMO provenance).
 *
 * Never falls back to "first portfolio" or name substring "DEMO".
 *
 * Run (local-only; not wired into GitHub CI):
 *   cd frontend
 *   npm run test:e2e:install
 *   E2E_PORTFOLIO_ID=6798 E2E_BASE_URL=http://127.0.0.1:5173 E2E_API_URL=http://127.0.0.1:8000 npm run test:e2e
 *
 * Inside the frontend container, set E2E_API_URL=http://backend:8000 so page.route
 * can rewrite browser localhost:8000 calls.
 *
 * Scope of this test (intentionally narrowed): decision → capture → refresh.
 * Full empty→create→Intelligence journey is not claimed here.
 */
import { expect, test, type APIRequestContext } from "@playwright/test";

const BASE = process.env.E2E_BASE_URL || "http://localhost:5173";
const API = process.env.E2E_API_URL || "http://localhost:8000";
const FIXTURE_ID_RAW = (process.env.E2E_PORTFOLIO_ID || "").trim();
const REQUIRED_SOURCE = "DEMO_INVESTOR_JOURNEY_V1";

async function apiJson(request: APIRequestContext, path: string, init?: { method?: string; data?: unknown }) {
  const res = await request.fetch(`${API}${path}`, {
    method: init?.method || "GET",
    data: init?.data as object | undefined,
    headers: { "Content-Type": "application/json" },
  });
  const body = await res.json().catch(() => null);
  return { status: res.status(), body };
}

async function resolveFixturePortfolio(request: APIRequestContext): Promise<number> {
  if (!/^\d+$/.test(FIXTURE_ID_RAW)) {
    throw new Error(
      "E2E_PORTFOLIO_ID is required (numeric). Refusing to pick a portfolio by DEMO name or list order.",
    );
  }
  const pid = Number(FIXTURE_ID_RAW);
  const { status, body } = await apiJson(request, `/api/v1/personal-portfolios/${pid}`);
  if (status !== 200 || body == null) {
    throw new Error(`E2E fixture portfolio ${pid} not found (HTTP ${status}).`);
  }
  const source = String(body?.portfolio?.source ?? body?.source ?? "");
  if (source !== REQUIRED_SOURCE) {
    throw new Error(
      `E2E fixture portfolio ${pid} source=${JSON.stringify(source)} — expected ${REQUIRED_SOURCE}. Fail closed.`,
    );
  }
  return pid;
}

async function snapshotJournal(request: APIRequestContext, portfolioId: number) {
  const { status, body } = await apiJson(request, `/api/v1/personal-portfolios/${portfolioId}`);
  expect(status).toBe(200);
  const ops = Array.isArray(body?.operations) ? body.operations : [];
  return {
    cash: String(body?.summary?.cash_rub ?? body?.portfolio?.cash_rub ?? ""),
    opTypes: ops.map((o: { operation_type?: string }) => o.operation_type),
    opCount: ops.length,
    opIds: ops.map((o: { id?: number }) => o.id),
  };
}

test.describe("MVP investor journey (fixture-bound)", () => {
  test("decision→memory survives refresh; hypothetical cash is read-only", async ({ page, request }) => {
    test.setTimeout(180_000);

    const pid = await resolveFixturePortfolio(request);

    await page.route("**/api/v1/**", async (route) => {
      try {
        const original = new URL(route.request().url());
        const target = `${API}${original.pathname}${original.search}`;
        const response = await request.fetch(target, {
          method: route.request().method(),
          headers: {
            ...route.request().headers(),
            host: new URL(API).host,
          },
          data: route.request().postData() || undefined,
        });
        const body = await response.body();
        await route.fulfill({
          status: response.status(),
          headers: response.headers(),
          body,
        });
      } catch {
        await route.abort();
      }
    });

    const before = await snapshotJournal(request, pid);

    await page.goto(`${BASE}/portfolio/${pid}?tab=decision`);
    await expect(page.getByTestId("daily-decision-panel")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("daily-decision-preset-100k").click();
    await expect(page.getByTestId("daily-decision-scenarios")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("decision-scenario-DO_NOTHING")).toBeVisible();
    await expect(page.getByTestId("decision-scenario-HOLD_CASH")).toBeVisible();
    await expect(page.getByTestId("decision-scenario-KRAKEN_ALLOCATION")).toBeVisible();

    await expect(page.getByTestId("memory-capture")).toBeEnabled({ timeout: 15_000 });
    await page.getByTestId("memory-capture").click();
    await expect(page.getByTestId("memory-notice")).toContainText(/зафиксир|уже было сохранено/i);

    const mid = await snapshotJournal(request, pid);
    expect(mid.cash).toBe(before.cash);
    expect(mid.opCount).toBe(before.opCount);
    expect(mid.opIds).toEqual(before.opIds);
    expect(mid.opTypes.filter((t: string) => t === "DEPOSIT" || t === "BUY")).toEqual([]);

    await page.reload();
    await page.goto(`${BASE}/portfolio/${pid}?tab=decision`);
    await expect(page.getByTestId("decision-memory-panel")).toBeVisible({ timeout: 60_000 });
    await expect(page.locator("[data-testid^='memory-item-']").first()).toBeVisible({ timeout: 30_000 });

    const after = await snapshotJournal(request, pid);
    expect(after.cash).toBe(before.cash);
    expect(after.opCount).toBe(before.opCount);
    expect(after.opTypes.some((t: string) => t === "DEPOSIT" || t === "BUY")).toBeFalsy();
  });
});
