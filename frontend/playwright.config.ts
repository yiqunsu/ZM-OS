import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/agent",
  fullyParallel: true,
  use: {
    baseURL: "http://127.0.0.1:3101",
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev -- --hostname 127.0.0.1 --port 3101",
    url: "http://127.0.0.1:3101/login",
    reuseExistingServer: false,
    env: {
      AGENT_V2_ENABLED: "true",
      BACKEND_INTERNAL_URL: "http://127.0.0.1:8102",
      AUTH_PROVIDER: "local",
      AUTH_SECRET: "filmos-e2e-secret-local-tests-only",
      AUTH_TRUST_HOST: "true",
      AUTH_URL: "http://127.0.0.1:3101",
    },
  },
});
