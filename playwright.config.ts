import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  testIgnore: ['**/admin-communications.spec.ts', '**/alert-communications.spec.ts'],
  timeout: 90_000,
  workers: 1,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    navigationTimeout: 60_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) } }],
  webServer: [
    {
      command: 'npm run dev --workspace=nerkhbaan-admin-web -- --host 127.0.0.1 --port 4174',
      url: 'http://127.0.0.1:4174',
      reuseExistingServer: false,
      timeout: 120_000,
      env: { VITE_ADMIN_API_URL: 'http://127.0.0.1:8000/api/admin' },
    },
    {
      command: 'npm run dev --workspace=nerkhbaan-web -- --host 127.0.0.1 --port 4173',
      url: 'http://127.0.0.1:4173/auth',
      reuseExistingServer: false,
      timeout: 120_000,
      env: { VITE_API_URL: 'http://127.0.0.1:8000' },
    },
    {
      command: process.env.NERKHBAAN_BROWSER_SCHEMA
        ? 'python -m uvicorn browser_test_server:app --app-dir apps/api/scripts --host 127.0.0.1 --port 8000'
        : 'python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000',
      url: process.env.NERKHBAAN_BROWSER_SCHEMA ? 'http://127.0.0.1:8000/__fixture__/health' : 'http://127.0.0.1:8000/api/health/ready',
      reuseExistingServer: false,
      timeout: 120_000,
      env: { BACKGROUND_TASKS_ENABLED: 'false' },
    },
  ],
});
