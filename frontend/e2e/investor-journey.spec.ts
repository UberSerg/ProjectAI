/**
 * Deterministic Playwright investor journey (DEMO / local stack).
 *
 * Prerequisites:
 *   - Docker stack healthy from this worktree
 *   - DEMO book bootstrapped with durable source (or empty UI create path)
 *
 * Run (local-only; not wired into GitHub CI yet):
 *   cd frontend
 *   npm run test:e2e:install
 *   E2E_BASE_URL=http://127.0.0.1:5173 E2E_API_URL=http://backend:8000 npm run test:e2e
 *
 * When the browser runs inside the frontend container, set E2E_API_URL to the
 * docker DNS name (http://backend:8000) so page.route can rewrite localhost:8000.
 *
 * Fixtures are DEMO/TEST labeled. Never seeds invented market candles.
 */
import { expect, test, type APIRequestContext } from "@playwright/test";

const BASE = process.env.E2E_BASE_URL || "http://localhost:5173";
const API = process.env.E2E_API_URL || "http://localhost:8000";

async function apiJson(request: APIRequestContext, path: string, init?: { method?: string; data?: unknown }) {
  const res = await request.fetch(`${API}${path}`, {
    method: init?.method || "GET",
    data: init?.data as object | undefined,
    headers: { "Content-Type": "application/json" },
  });
  const body = await res.json().catch(() => null);
  return { status: res.status(), body };
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

test.describe("MVP investor journey", () => {
  test("decision→memory survives refresh; hypothetical cash is read-only", async ({ page, request }) => {
    test.setTimeout(180_000);

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

    let portfolioId: number | null = null;
    const list = await apiJson(request, "/api/v1/personal-portfolios");
    if (list.status === 200 && Array.isArray(list.body?.items)) {
      const demo = list.body.items.find(
        (p: { name?: string; source?: string }) =>
          p.source === "DEMO_INVESTOR_JOURNEY_V1" ||
          (typeof p.name === "string" && p.name.includes("DEMO")),
      );
      if (demo?.id != null) portfolioId = Number(demo.id);
      else if (list.body.items[0]?.id != null) portfolioId = Number(list.body.items[0].id);
    }
    expect(portfolioId, "Need a portfolio id for journey").not.toBeNull();
    const pid = portfolioId!;

    const before = await snapshotJournal(request, pid);

    await page.goto(`${BASE}/portfolio/${pid}?tab=decision`);
    await expect(page.getByTestId("daily-decision-panel")).toBeVisible({ timeout: 60_000 });

    // Intelligence deep-link when holdings expose it (best-effort, non-blocking).
    await page.goto(`${BASE}/portfolio/${pid}?tab=holdings`);
    const analyze = page.getByRole("link", { name: /Проанализировать компанию/i }).first();
    if (await analyze.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await analyze.click();
      await expect(page).toHaveURL(/\/intelligence/, { timeout: 30_000 });
      const back = page.getByRole("link", { name: /Вернуться к портфелю|Назад к портфелю/i }).first();
      if (await back.isVisible().catch(() => false)) {
        await back.click();
      }
    }

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
