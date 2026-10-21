import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "../tests/e2e",
  testMatch: "admin-communications.spec.ts",
  timeout: 30_000,
  workers: 1,
  retries: 0,
  reporter: "list",
  outputDir: "../test-results/communications",
  use: { baseURL: "http://127.0.0.1:4184", trace: "retain-on-failure", screenshot: "only-on-failure", ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1100 } } },
    { name: "mobile", use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" } },
  ],
  webServer: {
    command: "npm run dev --workspace=nerkhbaan-admin-web -- --host 127.0.0.1 --port 4184 --strictPort",
    url: "http://127.0.0.1:4184/communications-preview.html",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: { VITE_ADMIN_BASE_PATH: "/" },
  },
});
