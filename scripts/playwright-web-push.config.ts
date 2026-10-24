import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '../tests/e2e', testMatch: 'web-push-setup.spec.ts',
  workers: 1, retries: 0, timeout: 35_000,
  outputDir: '../test-results/web-push-setup',
  use: { baseURL: 'http://127.0.0.1:4193', serviceWorkers: 'block', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) } }],
  webServer: {
    command: 'npm run dev --workspace=nerkhbaan-web -- --host 127.0.0.1 --port 4193 --strictPort',
    url: 'http://127.0.0.1:4193/auth', reuseExistingServer: false,
    env: { VITE_API_URL: '/api', VITE_VAPID_PUBLIC_KEY: '' },
  },
});
