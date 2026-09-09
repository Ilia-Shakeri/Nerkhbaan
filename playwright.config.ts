import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'npm run dev:web -- --host 127.0.0.1 --port 4173',
      url: 'http://127.0.0.1:4173/auth',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { VITE_API_URL: 'http://127.0.0.1:8000' },
    },
    {
      command: 'python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000',
      url: 'http://127.0.0.1:8000/api/health/ready',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { BACKGROUND_TASKS_ENABLED: 'false' },
    },
  ],
});
