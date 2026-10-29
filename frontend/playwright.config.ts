import { defineConfig, devices } from "@playwright/test";

/**
 * E2E against a running stack (docker compose up, or API + worker + `next start` locally).
 * E2E_BASE_URL defaults to http://localhost:3000. Credentials: E2E_EMAIL / E2E_PASSWORD.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
