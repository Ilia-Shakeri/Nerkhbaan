import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import path from 'node:path';

test('local administrator can sign in, inspect pages and sign out', async ({ page, request }) => {
  const credentials = JSON.parse(readFileSync(path.resolve('.local-preview/admin-login.private.json'), 'utf8'));
  const anonymous = await request.get('http://127.0.0.1:43187/api/admin/auth/me');
  expect(anonymous.status()).toBe(401);
  const foreign = await request.post('http://127.0.0.1:43187/api/admin/auth/signin', {
    headers: { Origin: 'http://127.0.0.1:43188' }, data: {},
  });
  expect(foreign.status()).toBe(403);
  const sending = await request.post('http://127.0.0.1:43187/api/admin/communications/test-events', {
    headers: { Origin: 'http://127.0.0.1:43189' }, data: {},
  });
  expect(sending.status()).toBe(503);
  for (const folder of ['.local-preview', '.LOCAL-PREVIEW']) {
    const file = path.resolve(folder, 'admin-login.private.json').replaceAll('\\', '/');
    const response = await request.get(`http://127.0.0.1:43189/@fs/${file}`);
    expect(response.status()).toBe(403);
    expect(await response.text()).not.toContain(credentials.password);
  }
  const errors: string[] = [];
  const failed: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    if (response.url().includes('/api/admin/') && response.status() >= 500) failed.push(new URL(response.url()).pathname);
  });
  await page.goto('http://127.0.0.1:43189');
  await expect(page.getByRole('complementary', { name: 'پنل محلی' })).toBeVisible();
  await page.getByLabel('Username or email', { exact: true }).fill(credentials.username);
  await page.getByLabel('Password', { exact: true }).fill(credentials.password);
  const [signedIn] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith('/api/admin/auth/signin')),
    page.getByRole('button', { name: 'Enter control plane', exact: true }).click(),
  ]);
  expect(signedIn.status()).toBe(200);
  await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeVisible();
  for (const name of ['Users', 'Access', 'مرکز ارتباطات', 'Audit']) {
    await page.getByRole('button', { name: new RegExp(`${name}$`) }).click();
    await expect(page.getByRole('heading', { name, exact: true }).first()).toBeVisible();
  }
  await page.getByRole('button', { name: /مرکز ارتباطات$/ }).click();
  await expect(page.getByRole('heading', { name: 'سرویس پیامک', exact: true })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'ارائه‌دهنده', exact: true })).toBeVisible();
  await page.screenshot({ path: '.local-preview/review-admin.png', fullPage: true });
  await page.reload();
  await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Enter control plane', exact: true })).toBeVisible();
  expect(errors).toEqual([]);
  expect(failed).toEqual([]);
});
