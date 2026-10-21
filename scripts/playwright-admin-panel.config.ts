import { defineConfig } from '@playwright/test';
import communications from './playwright-communications.config';

export default defineConfig({
  ...communications,
  testMatch: ['admin-panel.spec.ts', 'admin-communications.spec.ts', 'admin-console.spec.ts'],
  outputDir: '../test-results/admin-panel',
  use: { ...communications.use, serviceWorkers: 'block' },
});
