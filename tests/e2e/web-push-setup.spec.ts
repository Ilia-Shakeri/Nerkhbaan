import { expect, test, type Page } from '@playwright/test';

async function setup(page: Page, mode: 'unconfigured' | 'denied' | 'ios') {
  const errors: string[] = [], writes: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(mode => {
    localStorage.setItem('language', 'fa');
    sessionStorage.setItem('splash-shown', 'true');
    if (mode === 'denied') Object.defineProperty(Notification, 'permission', { configurable: true, get: () => 'denied' });
    if (mode === 'ios') Object.defineProperty(navigator, 'userAgent', { configurable: true, get: () => 'iPhone' });
  }, mode);
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
  await page.routeWebSocket('**/api/ws/prices', () => {});
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== 'GET') {
      writes.push(path); return route.fulfill({ status: 403, json: { detail: 'Fixture forbids sending' } });
    }
    if (path === '/api/auth/me') return route.fulfill({ json: { id: 1, username: 'web_push_fixture', must_change_password: false } });
    if (path === '/api/notifications/preferences') return route.fulfill({ json: { push_app: true, push_available: true, silent_mode: false, aggressive_alerts: false } });
    if (path === '/api/prices') return route.fulfill({ json: { assets: [], rights_revision: 'fixture', source: {} } });
    return route.fulfill({ json: [] });
  });
  await page.goto('/settings');
  return { errors, writes };
}

test('missing service setup explains disabled web push without sending', async ({ page }) => {
  const state = await setup(page, 'unconfigured');
  await expect(page.getByText('اعلان وب در خدمت آماده نیست؛ با مدیر تماس بگیرید.', { exact: true })).toBeVisible();
  await expect(page.getByRole('switch', { name: 'اعلان وب حساب', exact: true })).toBeDisabled();
  expect(state.errors).toEqual([]); expect(state.writes).toEqual([]);
});

test('blocked permission explains recovery in browser settings', async ({ page }) => {
  const state = await setup(page, 'denied');
  await expect(page.getByText(/اعلان این سایت بسته است/)).toBeVisible();
  expect(state.errors).toEqual([]); expect(state.writes).toEqual([]);
});

test('phone layout shows home screen install help without clipping', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const state = await setup(page, 'ios');
  await expect(page.getByText(/افزودن به صفحه اصلی/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(state.errors).toEqual([]); expect(state.writes).toEqual([]);
});
