import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '../tests/e2e',
  testMatch: 'alert-communications.spec.ts',
  timeout: 35_000,
  workers: 1,
  retries: 0,
  reporter: 'list',
  outputDir: '../test-results/alert-communications',
  use: {
    baseURL: 'http://127.0.0.1:4185',
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1100 } } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } },
  ],
  webServer: {
    command: 'npm run dev --workspace=nerkhbaan-web -- --host 127.0.0.1 --port 4185 --strictPort',
    url: 'http://127.0.0.1:4185/auth',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: { VITE_API_URL: '/api' },
  },
});
