import { defineConfig, devices } from "@playwright/test";

/**
 * E2E smoke flows against the REAL backend (disposable SQLite + demo seed)
 * and the Vite dev server. Run:  npm run test:e2e
 *
 * E2E_PYTHON lets you point at a virtualenv interpreter
 * (e.g. ../backend/.venv/Scripts/python.exe on Windows).
 */
const PYTHON = process.env.E2E_PYTHON ?? "python";

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    locale: "it-IT",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `"${PYTHON}" scripts/e2e_server.py`,
      cwd: "../backend",
      url: "http://127.0.0.1:8000/health",
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
