import { expect, test } from '@playwright/test';
import { randomBytes } from 'node:crypto';

export function registerDeliveryTests(api: string, web: string) {
  test('password change ends both sessions and returns to sign-in with the new password', async ({ page, browser }) => {
    const id = `handoff_${randomBytes(6).toString('hex')}`;
    const password = 'InitialDelivery42!';
    const next = 'ChangedDelivery73!';
    const other = await browser.newContext({ serviceWorkers: 'block' });
    try {
      const signup = await page.request.post(`${api}/auth/signup`, { headers: { Origin: web }, data: {
        username: id, email: `${id}@example.com`, password, full_name: 'Delivery review',
        accepted_terms: true, account_data_consent: true, policy_version: '2026-09-19.2',
      } });
      expect(signup.status()).toBe(201);
      expect((await other.request.post(`${api}/auth/signin`, { headers: { Origin: web },
        data: { username_or_email: id, password } })).status()).toBe(200);
      await page.addInitScript(() => { localStorage.setItem('language', 'en'); sessionStorage.setItem('splash-shown', 'true'); });
      await page.goto('/settings');
      await page.getByRole('button', { name: 'User menu', exact: true }).click();
      await page.getByRole('menuitem', { name: 'Change Password', exact: true }).click();
      const dialog = page.getByRole('dialog');
      await dialog.getByLabel('Current Password', { exact: true }).fill('WrongDelivery42!');
      await dialog.getByLabel('New Password', { exact: true }).fill(next);
      await dialog.getByLabel('Confirm New Password', { exact: true }).fill(next);
      const [rejected] = await Promise.all([
        page.waitForResponse(r => r.url().endsWith('/api/auth/change-password')),
        dialog.getByRole('button', { name: 'Change Password', exact: true }).click(),
      ]);
      expect(rejected.status()).toBe(400);
      await expect(dialog).toBeVisible();
      expect((await other.request.get(`${api}/auth/me`)).status()).toBe(200);
      await dialog.getByLabel('Current Password', { exact: true }).fill(password);
      let submitted = 0;
      page.on('request', request => { if (request.url().endsWith('/api/auth/change-password')) submitted++; });
      const [changed] = await Promise.all([
        page.waitForResponse(r => r.url().endsWith('/api/auth/change-password')),
        dialog.locator('form').evaluate((form: HTMLFormElement) => { form.requestSubmit(); form.requestSubmit(); }),
      ]);
      expect(changed.status()).toBe(200);
      await expect(page.getByRole('button', { name: 'Sign In', exact: true })).toBeVisible();
      expect(submitted).toBe(1);
      expect((await other.request.get(`${api}/auth/me`)).status()).toBe(401);
      expect((await other.request.post(`${api}/auth/refresh`, { headers: { Origin: web }, data: {} })).status()).toBe(401);
      expect((await other.request.post(`${api}/auth/signin`, { headers: { Origin: web },
        data: { username_or_email: id, password } })).status()).toBe(401);
      await page.locator('input[name="username"]').fill(id);
      await page.locator('#auth-password').fill(next);
      await page.getByRole('button', { name: 'Sign In', exact: true }).click();
      await expect(page.getByRole('button', { name: 'User menu', exact: true })).toBeVisible();
      await page.reload();
      await expect(page.getByRole('button', { name: 'User menu', exact: true })).toBeVisible();
    } finally { await other.close(); }
  });

  test('phone alert edits persist, another account cannot change them, deletion stops the alert', async ({ page, browser }) => {
    const other = await browser.newContext({ serviceWorkers: 'block' });
    const createAccount = async (client: typeof page.request) => {
      const id = `alert_delivery_${randomBytes(5).toString('hex')}`;
      expect((await client.post(`${api}/auth/signup`, { headers: { Origin: web }, data: {
        username: id, email: `${id}@example.com`, password: 'DeliveryAccount42!',
        accepted_terms: true, account_data_consent: true, policy_version: '2026-09-19.2',
      } })).status()).toBe(201);
    };
    try {
      await createAccount(page.request);
      await createAccount(other.request);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.addInitScript(() => { localStorage.setItem('language', 'en'); sessionStorage.setItem('splash-shown', 'true'); });
      await page.goto('/alerts');
      await page.getByRole('button', { name: 'New Alert', exact: true }).click();
      await page.getByLabel('Target', { exact: true }).fill('1800');
      const [created] = await Promise.all([
        page.waitForResponse(r => r.url().endsWith('/api/alerts') && r.request().method() === 'POST'),
        page.getByRole('button', { name: 'Create', exact: true }).click(),
      ]);
      expect(created.status()).toBe(201);
      const alert = await created.json();
      expect(await (await other.request.get(`${api}/alerts`)).json()).toEqual([]);
      expect((await other.request.patch(`${api}/alerts/${alert.id}`, { headers: { Origin: web }, data: { target_price: 1 } })).status()).toBe(404);
      expect((await other.request.delete(`${api}/alerts/${alert.id}`, { headers: { Origin: web } })).status()).toBe(404);
      await page.getByRole('button', { name: 'Edit Alert', exact: true }).click();
      await page.getByLabel('Target', { exact: true }).fill('1900');
      const [updated] = await Promise.all([
        page.waitForResponse(r => r.url().endsWith(`/api/alerts/${alert.id}`) && r.request().method() === 'PATCH'),
        page.getByRole('button', { name: 'Save', exact: true }).click(),
      ]);
      expect(updated.status()).toBe(200);
      await page.reload();
      await page.getByRole('button', { name: 'Edit Alert', exact: true }).click();
      await expect(page.getByLabel('Target', { exact: true })).toHaveValue('1900');
      await page.getByRole('button', { name: 'Cancel', exact: true }).click();
      page.once('dialog', dialog => dialog.dismiss());
      await page.getByRole('button', { name: 'Delete alert', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Edit Alert', exact: true })).toHaveCount(1);
      page.once('dialog', dialog => dialog.accept());
      const [deleted] = await Promise.all([
        page.waitForResponse(r => r.url().endsWith(`/api/alerts/${alert.id}`) && r.request().method() === 'DELETE'),
        page.getByRole('button', { name: 'Delete alert', exact: true }).click(),
      ]);
      expect(deleted.status()).toBe(204);
      await page.reload();
      await expect(page.getByRole('button', { name: 'Edit Alert', exact: true })).toHaveCount(0);
      expect(await (await page.request.get(`${api}/alerts`)).json()).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    } finally { await other.close(); }
  });
}
