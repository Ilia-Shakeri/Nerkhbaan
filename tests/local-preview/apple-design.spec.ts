import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { randomBytes } from 'node:crypto';

const web = 'http://127.0.0.1:43188';
const api = 'http://127.0.0.1:43187';
const admin = 'http://127.0.0.1:43189';
const id = `apple_${randomBytes(5).toString('hex')}`;
const password = 'LocalAppleReview42!';

test.beforeAll(async ({ request }) => {
  const reply = await request.post(`${api}/api/auth/signup`, { headers: { Origin: web }, data: {
    username: id, email: `${id}@example.com`, password, full_name: 'Interaction review',
    accepted_terms: true, account_data_consent: true, policy_version: '2026-09-19.2',
  } });
  expect(reply.status()).toBe(201);
});

async function customer(page: Page) {
  expect((await page.request.post(`${api}/api/auth/signin`, { headers: { Origin: web },
    data: { username_or_email: id, password } })).status()).toBe(200);
  await page.addInitScript(() => { localStorage.setItem('language', 'en'); sessionStorage.setItem('splash-shown', 'true'); });
}

async function administrator(page: Page) {
  const credentials = JSON.parse(readFileSync(path.resolve('.local-preview/admin-login.private.json'), 'utf8'));
  expect((await page.request.post(`${api}/api/admin/auth/signin`, { headers: { Origin: admin },
    data: { identifier: credentials.username, password: credentials.password } })).status()).toBe(200);
}

test('anonymous recovery and legal pages survive a rejected startup session', async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem('language', 'en'); sessionStorage.setItem('splash-shown', 'true'); });
  for (const [route, heading] of [['/forgot-password', 'Forgot Password'], ['/privacy', 'Privacy policy'], ['/terms', 'Terms and conditions']]) {
    await page.goto(web + route);
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
    await expect.poll(() => new URL(page.url()).pathname).toBe(route);
  }
  await page.goto(web + '/alerts');
  await expect(page).toHaveURL(/\/auth/);
});

test('authentication responds immediately and mobile fields stay readable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => { localStorage.setItem('language', 'en'); sessionStorage.setItem('splash-shown', 'true'); });
  await page.goto(web + '/auth');
  const signup = page.getByRole('button', { name: 'Sign up', exact: true });
  await expect(signup).toBeEnabled();
  expect((await signup.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await signup.click();
  await expect(page.getByRole('textbox', { name: 'Username', exact: true })).toBeEditable();
  const sizes = await page.locator('input:not([type="checkbox"])').evaluateAll(elements => elements.map(e => parseFloat(getComputedStyle(e).fontSize)));
  expect(sizes.every(size => size >= 16)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('card ordering works with a keyboard and is saved after reload', async ({ page }) => {
  await customer(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(web);
  const move = page.getByRole('button', { name: 'Move Silver to first', exact: true });
  await move.focus(); await page.keyboard.press('Enter');
  await expect(page.locator('[data-market-card]').first()).toHaveAttribute('data-market-card', 'silver');
  await expect(page.locator('[data-market-card="silver"]')).toBeFocused();
  await expect(page.getByRole('status').filter({ hasText: 'Silver moved to first' })).toHaveText('Silver moved to first');
  await page.reload();
  await expect(page.locator('[data-market-card]').first()).toHaveAttribute('data-market-card', 'silver');
});

test('price period and currency controls keep a full touch target', async ({ page }) => {
  await customer(page); await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(web);
  for (const name of ['USD', 'TMN', '1h', '24h', '7d', '30d', '1y', 'Compare sources']) {
    const control = page.getByRole('button', { name, exact: true }).first();
    await expect(control).toBeVisible();
    const rect = (await control.boundingBox())!;
    expect(rect.height, name).toBeGreaterThanOrEqual(44);
    if (name !== 'Compare sources') expect(rect.width, name).toBeGreaterThanOrEqual(44);
  }
});

test('touch users can see the desktop sidebar collapse control without hover', async ({ browser }) => {
  const context = await browser.newContext({ hasTouch: true, viewport: { width: 1365, height: 900 }, serviceWorkers: 'block' });
  try {
    const page = await context.newPage(); await customer(page); await page.goto(web);
    const collapse = page.getByRole('button', { name: 'Collapse sidebar', exact: true });
    await expect(collapse).toBeVisible();
    expect(await page.evaluate(() => matchMedia('(pointer: coarse)').matches)).toBe(true);
    expect(await collapse.evaluate(e => getComputedStyle(e).opacity)).toBe('1');
  } finally { await context.close(); }
});

test('user information can retry a failed read in the same dialog', async ({ page }) => {
  await customer(page); await page.goto(web);
  await expect(page.getByRole('button', { name: 'User menu', exact: true })).toBeVisible();
  let attempts = 0;
  await page.route('**/api/auth/me', async route => {
    if (++attempts === 1) return route.fulfill({ status: 503, json: { detail: 'Temporary test outage' } });
    await route.continue();
  });
  await page.getByRole('button', { name: 'User menu', exact: true }).click();
  await page.getByRole('menuitem', { name: 'User Info', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Retry user information', exact: true }).click();
  await expect(dialog.getByText(id, { exact: true })).toBeVisible();
  expect(attempts).toBe(2);
});

test('a failed chat list stays distinct from an empty list and can be retried', async ({ page }) => {
  await customer(page);
  let unavailable = true;
  await page.route('**/api/insights/chat/sessions', route => unavailable
    ? route.fulfill({ status: 503, json: { detail: 'Temporary test outage' } })
    : route.fulfill({ json: [] }));
  await page.goto(web + '/assistant');
  await expect(page.getByText('Saved chats may still exist.', { exact: false })).toBeVisible();
  await expect(page.getByText('No saved chats', { exact: true })).toHaveCount(0);
  unavailable = false;
  await page.getByRole('button', { name: 'Retry chat list', exact: true }).click();
  await expect(page.getByText('No saved chats', { exact: true })).toBeVisible();
});

test('administrator navigation is named and data tables scroll from a keyboard', async ({ page }) => {
  await administrator(page); await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(admin + '/#/users');
  const navigation = page.getByRole('navigation', { name: 'Administrator navigation' });
  await expect(navigation.getByText('Pricing', { exact: true })).toBeVisible();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#admin-main')).toBeFocused();
  await expect(page).toHaveURL(/#\/users$/);
  const table = page.getByRole('region', { name: /^Data table:/ }).first();
  await table.focus();
  expect(await table.evaluate(e => e.scrollWidth > e.clientWidth)).toBe(true);
  await page.keyboard.press('ArrowRight');
  await expect.poll(() => table.evaluate(e => e.scrollLeft)).toBeGreaterThan(0);
  expect(await page.getByLabel('Search', { exact: true }).evaluate(e => parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(16);
  expect(await page.title()).toContain('Users');
});

test('reduced transparency removes the administrator dialog blur', async ({ page }) => {
  await administrator(page);
  const media = await page.context().newCDPSession(page);
  await media.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-transparency', value: 'reduce' }] });
  await page.goto(admin + '/#/users');
  await page.getByLabel('Change reason', { exact: true }).fill('Local accessibility check; no write submitted');
  await page.getByRole('button', { name: 'Disable', exact: true }).first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  const style = await page.locator('.modal-backdrop').evaluate(e => ({ blur: getComputedStyle(e).backdropFilter, background: getComputedStyle(e).backgroundColor }));
  expect(style.blur).toBe('none');
  expect(style.background).toBe('rgb(8, 7, 4)');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
});


test('analysis keeps flat and missing changes neutral and respects the numeric direction', async ({ page }) => {
  await customer(page);
  await page.route('**/api/prices', async route => {
    const reply = await route.fetch();
    const body = await reply.json();
    const changes = [0, 1, -1, null];
    body.assets = body.assets.slice(0, 4).map((asset: object, index: number) => ({ ...asset, change_percent: changes[index], trend: 'neutral' }));
    await route.fulfill({ response: reply, json: body });
  });
  await page.goto(web + '/analysis');
  for (const [name, color] of [['Gold 0%', 'text-gray-400'], ['Silver +1%', 'text-emerald-500'], ['Tether -1%', 'text-red-500'], ['Bitcoin —', 'text-gray-400']]) {
    const value = page.getByRole('button', { name, exact: true }).locator('div').last();
    await expect(value).toHaveClass(new RegExp(color));
  }
});
