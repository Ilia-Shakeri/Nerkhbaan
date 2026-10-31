import { expect, test } from '@playwright/test';
import { randomBytes } from 'node:crypto';
import { writeFileSync, unlinkSync } from 'node:fs';
import path from 'node:path';

test('local accounts, alerts and in-app notices work without external delivery', async ({ page, request }) => {
  const health = await request.get('http://127.0.0.1:43187/__preview__/health');
  expect(health.status()).toBe(200);
  expect(await health.json()).toMatchObject({ mode: 'local-preview', external_delivery: false, prices: 'synthetic' });
  const sentinel = path.resolve('.local-preview/access-check.txt');
  writeFileSync(sentinel, 'PRIVATE_PREVIEW_SENTINEL');
  try {
    for (const file of [sentinel, sentinel.replace('.local-preview', '.LOCAL-PREVIEW')]) {
      const hidden = await request.get(`http://127.0.0.1:43188/@fs/${file.replaceAll('\\', '/')}`);
      expect(hidden.status()).toBe(403);
      expect(await hidden.text()).not.toContain('PRIVATE_PREVIEW_SENTINEL');
    }
  } finally { unlinkSync(sentinel); }
  const external = await request.post('http://127.0.0.1:43187/api/local-preview/notice', { headers: { Origin: 'https://foreign.invalid' } });
  expect(external.status()).toBe(403);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => { localStorage.setItem('language', 'en'); sessionStorage.setItem('splash-shown', 'true'); });
  const id = randomBytes(6).toString('hex');
  const email = `local_${id}@example.com`;
  const password = 'LocalPreviewTest42!';
  await page.goto('/auth');
  await expect(page.getByRole('complementary', { name: 'Local preview' })).toContainText('synthetic');
  await page.getByRole('button', { name: 'Sign up', exact: true }).click();
  await page.locator('input[name="name"]').fill('Local review test');
  await page.locator('input[name="username"]').fill('not a valid username');
  expect(await page.locator('input[name="username"]').evaluate((input: HTMLInputElement) => input.validity.patternMismatch)).toBe(true);
  await page.locator('input[name="username"]').fill(`local_${id}`);
  await page.locator('input[name="email"]').fill(email);
  await page.locator('#auth-password').fill(password);
  const terms = page.getByRole('checkbox');
  await terms.nth(0).check(); await terms.nth(1).check();
  const [created] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === '/api/auth/signup', { timeout: 25000 }),
    page.getByRole('button', { name: 'Create Account', exact: true }).click(),
  ]);
  expect(created.status()).toBe(201);
  await expect(page.getByRole('button', { name: 'User menu', exact: true })).toBeVisible();
  const sample = await page.request.get('http://127.0.0.1:43187/api/prices');
  expect((await sample.json()).rights_revision).toBe('local-preview-synthetic-v1');
  await expect(page.getByRole('heading', { name: /^Gold / }).first()).toBeVisible();
  await expect(page.getByText('USD Local sample', { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: '.local-preview/review-desktop.png', fullPage: true });
  await page.goto('/alerts');
  await page.getByRole('button', { name: 'New Alert', exact: true }).click();
  await page.getByLabel('Target', { exact: true }).fill('1800');
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Edit Alert', exact: true })).toHaveCount(1);
  await page.reload();
  await expect(page.getByRole('button', { name: 'Edit Alert', exact: true })).toHaveCount(1);
  await page.getByRole('button', { name: 'Add sample in-app notification', exact: true }).click();
  await page.getByRole('button', { name: 'Notifications', exact: true }).click();
  await expect(page.getByText('اعلان نمونهٔ محلی', { exact: true }).first()).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/settings');
  await expect(page.getByRole('switch', { name: 'Account web notifications', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '.local-preview/review-phone.png', fullPage: true });
  await page.getByRole('button', { name: 'User menu', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Logout', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sign In', exact: true })).toBeVisible();
  await page.locator('input[name="username"]').fill(email);
  await page.locator('#auth-password').fill(password);
  await page.getByRole('button', { name: 'Sign In', exact: true }).click();
  await expect(page.getByRole('button', { name: 'User menu', exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
