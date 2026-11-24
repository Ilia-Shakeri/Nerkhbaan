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
  const move = page.locator('[data-market-card="silver"]');
  await move.focus(); await page.keyboard.press('Alt+ArrowUp');
  await expect(page.getByRole('button', { name: 'Move Silver to first' })).toHaveCount(0);
  await expect(page.locator('[data-market-card]').first()).toHaveAttribute('data-market-card', 'silver');
  await expect(page.locator('[data-market-card="silver"]')).toBeFocused();
  await expect(page.getByRole('status').filter({ hasText: 'Card order changed' })).toHaveText('Card order changed');
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


test('pickers match light and dark themes and back returns within the website', async ({ page }) => {
  await customer(page); await page.setViewportSize({ width: 390, height: 844 });
  for (const [theme, color] of [['dark', 'rgb(21, 18, 13)'], ['light', 'rgb(255, 250, 240)']]) {
    await page.goto(web); await page.evaluate(theme => localStorage.setItem('theme', theme), theme);
    await page.goto(web + '/alerts');
    await page.getByRole('button', { name: 'New Alert', exact: true }).click();
    const select = page.getByRole('dialog').getByLabel('Asset', { exact: true });
    await expect(select).toHaveCSS('background-color', color);
    await expect(select.locator('option').last()).toHaveCSS('background-color', color);
    await select.click();
    expect(await select.evaluate(e => getComputedStyle(e, '::picker(select)').backgroundColor)).toBe(color);
    await page.screenshot({ path: test.info().outputPath(`picker-${theme}.png`) });
    await page.keyboard.press('Escape'); await select.selectOption('silver');
    await expect(select).toHaveValue('silver'); await page.keyboard.press('Escape');
  }
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await expect(page).toHaveURL(web + '/');
});

test('all four card marks load without logo frames or the two removed controls', async ({ page }) => {
  await customer(page); await page.goto(web);
  await expect(page.locator('[data-market-card]')).toHaveCount(4);
  await expect(page.getByRole('button', { name: /^Move .+ to first$/ })).toHaveCount(0);
  for (const card of await page.locator('[data-market-card]').all()) {
    const icon = card.locator('.asset-icon'); await expect(icon).toBeVisible();
    expect(await icon.evaluate((e: HTMLImageElement) => e.complete && e.naturalWidth > 0)).toBe(true);
  }
  for (const logo of await page.locator('img.brand-logo').all()) await expect(logo).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await page.goto(web + '/support');
  await expect(page.getByRole('button', { name: 'Refresh support', exact: true })).toHaveCount(0);
});

test('alerts update from the server without a refresh and preserve the open draft', async ({ page }) => {
  await page.clock.install(); await customer(page); await page.goto(web + '/alerts');
  await expect(page.getByText('No alerts yet', { exact: true })).toBeVisible();
  const reply = await page.request.post(api + '/api/alerts', { headers: { Origin: web }, data: {
    asset: 'gold', target_price: 2501, currency_mode: 'usd', condition: 'above', price_source_mode: 'ordinary', notify_app: true, notify_email: false,
  } });
  expect(reply.status()).toBe(201); const alert = await reply.json();
  await page.clock.fastForward(15_050);
  await expect(page.getByRole('button', { name: 'Edit Alert', exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'New Alert', exact: true }).click();
  const target = page.getByRole('dialog').getByLabel('Target', { exact: true });
  await target.fill('7777'); await target.blur(); await page.clock.fastForward(31_000);
  await expect(target).toHaveValue('7777');
  await page.keyboard.press('Escape');
  expect((await page.request.delete(api + '/api/alerts/' + alert.id, { headers: { Origin: web } })).ok()).toBe(true);
});

test('administrator reads refresh quietly, pause during editing and back follows panel history', async ({ page }) => {
  await page.clock.install(); await administrator(page); let reads = 0;
  page.on('request', r => { if (new URL(r.url()).pathname === '/api/admin/users' && r.method() === 'GET') reads++; });
  await page.goto(admin + '/#/users'); await expect(page.getByRole('heading', { name: 'Users', exact: true }).first()).toBeVisible();
  await expect.poll(() => reads).toBeGreaterThan(0); const first = reads;
  await page.clock.fastForward(30_050); await expect.poll(() => reads).toBeGreaterThan(first);
  for (const mark of await page.locator('.brand-seal').all()) await expect(mark).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  const value = page.getByRole('checkbox', { name: 'Enabled', exact: true }); await expect(value).toBeVisible();
  const changed = !(await value.isChecked()); await value.setChecked(changed); await value.blur(); await page.clock.fastForward(61_000); await expect(value).toBeChecked({ checked: changed });
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await expect(page).toHaveURL(/#\/users$/);
});


test('back stays in the header without covering content at narrow widths or large text', async ({ page }) => {
  await customer(page);
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(web + '/assistant');
    await page.evaluate(() => document.documentElement.style.fontSize = '200%');
    const back = page.getByRole('button', { name: 'Back', exact: true });
    await expect(back).toBeVisible();
    const b = (await back.boundingBox())!;
    expect(b.width).toBe(44); expect(b.height).toBe(44);
    expect(await back.evaluate(e => !!e.closest('header'))).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await administrator(page); await page.goto(admin + '/#/communications');
  await page.evaluate(() => document.documentElement.style.fontSize = '200%');
  const back = page.getByRole('button', { name: 'Back', exact: true });
  expect(await back.evaluate(e => !!e.closest('header'))).toBe(true);
  expect((await back.boundingBox())!.width).toBe(44);
});
