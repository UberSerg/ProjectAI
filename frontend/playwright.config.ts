import { defineConfig } from "@playwright/test";

/**
 * Local reproducible E2E against a running Docker/dev stack.
 * Not part of GitHub Actions CI for this remediation (documented limitation).
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:5173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
});
