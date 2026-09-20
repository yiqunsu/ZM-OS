import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/agent-fullstack",
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  use: {
    baseURL: "http://127.0.0.1:3131",
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "../backend/venv/bin/python ../backend/tests/support/run_fullstack.py",
    url: "http://127.0.0.1:3131/login",
    timeout: 120_000,
    reuseExistingServer: false,
    gracefulShutdown: { signal: "SIGTERM", timeout: 45_000 },
  },
});
