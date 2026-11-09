import { expect, test, type BrowserContext } from '@playwright/test';
import { randomBytes } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const api = 'http://127.0.0.1:43187/api';
const web = 'http://127.0.0.1:43188';
const admin = 'http://127.0.0.1:43189';
const consent = { support_data_consent: true, policy_version: '2026-09-19.2' };

async function customer(context: BrowserContext, suffix: string) {
  const id = `joint_${suffix}_${randomBytes(4).toString('hex')}`;
  const response = await context.request.post(`${api}/auth/signup`, {
    headers: { Origin: web }, data: { username: id, email: `${id}@example.com`,
      full_name: 'Joint local review', password: 'LocalReview42!Password',
      accepted_terms: true, account_data_consent: true, policy_version: consent.policy_version },
  });
  expect(response.status()).toBe(201);
  return (await response.json()).user;
}

test('customer and administrator share support state and enforce account boundaries', async ({ page, browser }) => {
  const owner = await customer(page.context(), 'owner');
  const other = await browser.newContext({ serviceWorkers: 'block' });
  const adminContext = await browser.newContext({ serviceWorkers: 'block' });
  try {
    await customer(other, 'other');
    await page.addInitScript(() => { localStorage.setItem('language', 'en'); sessionStorage.setItem('splash-shown', 'true'); });
    await page.goto(`${web}/support`);
    const subject = `Joint support ${randomBytes(4).toString('hex')}`;
    await page.getByRole('button', { name: 'New Ticket', exact: true }).click();
    await page.getByLabel('Subject', { exact: true }).fill(subject);
    await page.getByLabel('Message', { exact: true }).fill('Local customer needs help.');
    await page.getByRole('checkbox').first().check();
    const [created] = await Promise.all([
      page.waitForResponse(response => new URL(response.url()).pathname === '/api/support/ticket'),
      page.getByRole('button', { name: 'Create Ticket', exact: true }).click(),
    ]);
    expect(created.status()).toBe(201);
    const ticket = await created.json();
    expect((await other.request.get(`${api}/support/ticket/${ticket.id}/messages`)).status()).toBe(404);
    expect((await page.request.get(`${api}/admin/users`)).status()).toBe(401);

    const credentials = JSON.parse(readFileSync(path.resolve('.local-preview/admin-login.private.json'), 'utf8'));
    const panel = await adminContext.newPage();
    await panel.goto(admin);
    await panel.getByLabel('Username or email', { exact: true }).fill(credentials.username);
    await panel.getByLabel('Password', { exact: true }).fill(credentials.password);
    const [login] = await Promise.all([
      panel.waitForResponse(response => response.url().endsWith('/api/admin/auth/signin')),
      panel.getByRole('button', { name: 'Enter control plane', exact: true }).click(),
    ]);
    expect(login.status()).toBe(200);
    const signedIn = await login.json();
    const headers = { Origin: admin, 'X-CSRF-Token': signedIn.csrf_token };
    await panel.getByRole('button', { name: /Support$/ }).click();
    const row = panel.getByRole('row').filter({ hasText: subject });
    await row.getByRole('button', { name: 'Open ticket', exact: true }).click();
    const reply = `Administrator answer ${ticket.id}`;
    await panel.getByLabel('Reply', { exact: true }).fill(reply);
    const [answered] = await Promise.all([
      panel.waitForResponse(response => response.url().endsWith(`/tickets/${ticket.id}/reply`)),
      panel.getByRole('button', { name: 'Send reply', exact: true }).click(),
    ]);
    expect(answered.status()).toBe(201);
    const internal = `Internal only ${ticket.id}`;
    const note = await panel.request.post(`${api}/admin/support/tickets/${ticket.id}/internal-notes`, { headers, data: { content: internal } });
    expect(note.status()).toBe(201);
    await page.getByRole('button', { name: 'Refresh support', exact: true }).click();
    await expect(page.getByText(reply, { exact: true }).first()).toBeVisible();
    const messages = await page.request.get(`${api}/support/ticket/${ticket.id}/messages`);
    expect(await messages.text()).not.toContain(internal);
    const response = await page.request.post(`${api}/support/ticket/${ticket.id}/message`, {
      headers: { Origin: web }, data: { content: 'Thank you, one more question.', ...consent },
    });
    expect(response.status()).toBe(201);
    const detail = await panel.request.get(`${api}/admin/support/tickets/${ticket.id}`);
    expect((await detail.json()).ticket.status).toBe('open');

    const noCsrf = await panel.request.patch(`${api}/admin/support/tickets/${ticket.id}`, {
      headers: { Origin: admin }, data: { priority: 'high' },
    });
    expect(noCsrf.status()).toBe(403);
    const reauth = await panel.request.post(`${api}/admin/auth/reauthenticate`, { headers, data: { password: credentials.password } });
    expect(reauth.status()).toBe(200);
    const selfDisable = await panel.request.patch(`${api}/admin/users/${signedIn.admin.id}/state`, {
      headers, data: { is_active: false, reason: 'Local protection test', confirmation: `DISABLE USER ${signedIn.admin.id}` },
    });
    expect(selfDisable.status()).toBe(409);
    const disable = await panel.request.patch(`${api}/admin/users/${owner.id}/state`, {
      headers, data: { is_active: false, reason: 'Local joint review', confirmation: `DISABLE USER ${owner.id}` },
    });
    expect(disable.status()).toBe(200);
    expect((await page.request.get(`${api}/auth/me`)).status()).toBe(401);
    const enable = await panel.request.patch(`${api}/admin/users/${owner.id}/state`, {
      headers, data: { is_active: true, reason: 'Local review complete', confirmation: `ENABLE USER ${owner.id}` },
    });
    expect(enable.status()).toBe(200);
    expect((await page.request.get(`${api}/auth/me`)).status()).toBe(401);
    await panel.getByRole('button', { name: 'Sign out', exact: true }).click();
    await expect(panel.getByRole('button', { name: 'Enter control plane', exact: true })).toBeVisible();
  } finally {
    await other.close();
    await adminContext.close();
  }
});
