import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '../tests/local-preview',
  workers: 1,
  retries: 0,
  timeout: 90_000,
  outputDir: '../.local-preview/test-results',
  use: {
    baseURL: 'http://127.0.0.1:43188',
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
  },
});
