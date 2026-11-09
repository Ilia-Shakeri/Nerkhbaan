import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const sections = [
  ['dashboard', 'Operations', '/dashboard'], ['users', 'Users', '/users'],
  ['roles', 'Access', '/roles'], ['support', 'Support', '/support/tickets'],
  ['telegram', 'Telegram', '/telegram/sources'], ['dlq', 'Dead-letter queue', '/jobs/dlq'],
  ['providers', 'Providers', '/providers'], ['pricing', 'Pricing', '/pricing/instruments'],
  ['jobs', 'Jobs & DLQ', '/jobs'], ['settings', 'Settings', '/settings'],
  ['alerts', 'Alerts', '/alerts'], ['communications', 'مرکز ارتباطات', '/communications'],
  ['backups', 'Backup evidence', '/backups/status'], ['security', 'My security', '/auth/mfa'],
  ['audit', 'Audit', '/audit'],
];

for (const width of [1280, 390]) {
  test(`all local administrator sections load real data at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const credentials = JSON.parse(readFileSync(path.resolve('.local-preview/admin-login.private.json'), 'utf8'));
    const response = await page.request.post('http://127.0.0.1:43187/api/admin/auth/signin', {
      headers: { Origin: 'http://127.0.0.1:43189' },
      data: { identifier: credentials.username, password: credentials.password },
    });
    expect(response.status()).toBe(200);
    const failures: string[] = [];
    page.on('pageerror', error => failures.push(error.message));
    page.on('response', response => {
      if (response.url().includes('/api/admin/') && response.status() >= 500) failures.push(new URL(response.url()).pathname);
    });
    for (const [section, name, endpoint] of sections) {
      const [loaded] = await Promise.all([
        page.waitForResponse(response => new URL(response.url()).pathname === `/api/admin${endpoint}` && response.status() === 200),
        page.goto(`http://127.0.0.1:43189/#/${section}`),
      ]);
      expect(loaded.status(), section).toBe(200);
      await expect(page.getByRole('heading', { name, exact: true }).first()).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), section).toBe(true);
      await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeInViewport();
    }
    expect(failures).toEqual([]);
    await page.setViewportSize({ width: width === 390 ? 1280 : 390, height: 844 });
    await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Enter control plane', exact: true })).toBeVisible();
  });
}
