import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '../tests/e2e',
  testMatch: 'client-interface.spec.ts',
  workers: 1,
  timeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:4175', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) } }],
  webServer: {
    command: 'npm run dev --workspace=nerkhbaan-web -- --host 127.0.0.1 --port 4175',
    url: 'http://127.0.0.1:4175/auth',
    reuseExistingServer: false,
    env: { VITE_API_URL: '/api' },
  },
});
