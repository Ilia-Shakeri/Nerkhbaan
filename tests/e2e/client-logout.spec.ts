import { expect, test, type Page } from '@playwright/test';
import { emptyMarketPrices, mockMarketStream } from './market-fixture';

const profile = { id: 1, username: 'logout_test', full_name: 'Logout Test', email: 'logout@example.test', is_active: true, must_change_password: false, created_at: '2026-10-13T00:00:00Z' };

type SessionState = { signedOut: boolean; fail: boolean; offline: boolean; profiles: number; signouts: number; detached: number; crash: boolean; calls: string[]; signinGate?: Promise<void>; signoutCookie?: string; pushFails?: boolean };
async function session(page: Page, shared?: SessionState) {
  await mockMarketStream(page);
  await page.addInitScript(() => {
    localStorage.setItem('language', 'en');
    sessionStorage.setItem('splash-shown', 'true');
    let subscribed = sessionStorage.getItem('test-push-unsubscribed') !== 'true';
    const worker = { pushManager: { getSubscription: async () => subscribed ? {
      endpoint: 'https://push.example.test/logout-test',
      unsubscribe: async () => { if (sessionStorage.getItem('test-push-stuck')) return false; subscribed = false; sessionStorage.setItem('test-push-unsubscribed', 'true'); return true; },
    } : null } };
    Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: { getRegistration: async () => worker, ready: Promise.resolve(worker) } });
  });
  const state: SessionState = shared ?? { signedOut: false, fail: false, offline: false, profiles: 0, signouts: 0, detached: 0, crash: false, calls: [] };
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/me') {
      state.profiles++;
      await route.fulfill(state.signedOut ? { status: 401, json: { detail: 'No session' } } : { json: profile });
    } else if (path === '/api/auth/signin') {
      state.calls.push('signin-start');
      await state.signinGate;
      state.signedOut = false;
      state.calls.push('signin-response');
      await route.fulfill({ json: { user: profile, token_type: 'bearer' }, headers: { 'set-cookie': 'test_session=new-session; Path=/; HttpOnly; SameSite=Lax' } });
    } else if (path === '/api/auth/signout') {
      state.signouts++;
      state.calls.push('signout');
      if (state.offline) await route.abort('internetdisconnected');
      else if (state.fail) await route.fulfill({ status: 503, json: { detail: 'Temporary signout failure' } });
      else { state.signedOut = true; state.signoutCookie = route.request().headers().cookie; await route.fulfill({ status: 204, headers: { 'set-cookie': 'test_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax' } }); }
    } else if (path === '/api/push/unsubscribe') {
      expect(route.request().postDataJSON().endpoint).toBe('https://push.example.test/logout-test');
      state.detached++;
      state.calls.push('detach');
      await route.fulfill(state.pushFails ? { status: 503, json: { detail: 'Temporary detach failure' } } : { status: 204 });
    } else if (path === '/api/prices') await route.fulfill({ json: emptyMarketPrices() });
    else if (path.endsWith('/history')) await route.fulfill({ json: { points: [] } });
    else if (path === '/api/alerts') await route.fulfill({ json: state.crash ? null : [] });
    else await route.fulfill({ json: [] });
  });
  return state;
}

async function leave(page: Page) {
  await page.getByRole('button', { name: 'User menu', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Logout', exact: true }).click();
}

test('failed logout stays visible across reload and explicit retry closes the server session', async ({ page }) => {
  const state = await session(page);
  state.fail = true;
  await page.goto('/');
  await leave(page);
  await expect(page.getByRole('alert', { name: 'Sign-out incomplete' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry sign-out' })).toBeEnabled();
  const beforeReload = state.profiles;
  await page.reload();
  await expect(page.getByRole('button', { name: 'Sign In', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sign In', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Sign up', exact: true })).toBeDisabled();
  await expect(page.getByRole('alert', { name: 'Sign-out incomplete' })).toBeVisible();
  expect(state.profiles).toBe(beforeReload);
  state.fail = false;
  await page.getByRole('button', { name: 'Retry sign-out' }).click();
  await expect(page.getByRole('alert', { name: 'Sign-out incomplete' })).toHaveCount(0);
  expect(state.signedOut).toBe(true);
  await expect(page.getByRole('button', { name: 'Sign In', exact: true })).toBeEnabled();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Sign In', exact: true })).toBeVisible();
});

test('offline logout stays locked after the connection returns and reloads', async ({ page }) => {
  const state = await session(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'User menu', exact: true }).click();
  state.offline = true;
  await page.context().setOffline(true);
  await page.getByRole('menuitem', { name: 'Logout', exact: true }).click();
  await expect(page.getByRole('alert', { name: 'Sign-out incomplete' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry sign-out' })).toBeEnabled({ timeout: 25_000 });
  await page.context().setOffline(false);
  state.offline = false;
  const beforeReload = state.profiles;
  await page.reload();
  await expect(page.getByRole('button', { name: 'Sign In', exact: true })).toBeVisible();
  expect(state.profiles).toBe(beforeReload);
  await page.getByRole('button', { name: 'Retry sign-out' }).click();
  await expect(page.getByRole('alert', { name: 'Sign-out incomplete' })).toHaveCount(0);
});

test('crash recovery detaches browser push before closing the session', async ({ page }) => {
  const state = await session(page);
  state.crash = true;
  await page.goto('/alerts');
  await expect(page.getByRole('heading', { name: 'Page failed to load' })).toBeVisible();
  await page.getByRole('button', { name: 'Sign in again', exact: true }).click();
  await expect.poll(() => state.detached).toBe(1);
  expect(state.calls[0]).toBe('detach');
  await expect(page.getByRole('button', { name: 'Sign In', exact: true })).toBeVisible();
});

test('crash recovery keeps failed signout visible on the next page', async ({ page }) => {
  const state = await session(page);
  state.crash = true;
  state.fail = true;
  await page.goto('/alerts');
  await page.getByRole('button', { name: 'Sign in again', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sign In', exact: true })).toBeVisible();
  await expect(page.getByRole('alert', { name: 'Sign-out incomplete' })).toBeVisible();
  expect(state.signedOut).toBe(false);
  expect(state.detached).toBe(1);
});

test('cookie fallback preserves failed logout when local storage writes are denied', async ({ page }) => {
  const state = await session(page);
  state.fail = true;
  await page.addInitScript(() => {
    const write = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === 'nerkhbaan-logout-pending') throw new DOMException('Storage denied', 'SecurityError');
      return write.call(this, key, value);
    };
  });
  await page.goto('/');
  await leave(page);
  await expect(page.getByRole('button', { name: 'Retry sign-out' })).toBeEnabled();
  const profiles = state.profiles;
  await page.reload();
  await expect(page.getByRole('alert', { name: 'Sign-out incomplete' })).toBeVisible();
  expect(state.profiles).toBe(profiles);
  expect(await page.evaluate(() => document.cookie)).toContain('nerkhbaan-logout-pending=1');
});

test('logout waits for another tab sign-in response and revokes its newly set cookie', async ({ page }) => {
  const state = await session(page);
  await page.goto('/');
  const second = await page.context().newPage();
  await session(second, state);
  let releaseSignin!: () => void;
  state.signinGate = new Promise(resolve => { releaseSignin = resolve; });
  await second.goto('/auth');
  await second.getByLabel('Username or Email').fill('logout_test');
  await second.getByLabel('Password', { exact: true }).fill('TestPassword123!');
  await second.getByRole('button', { name: 'Sign In', exact: true }).click();
  await expect.poll(() => state.calls.includes('signin-start')).toBe(true);
  await leave(page);
  await expect(page.getByRole('alert', { name: 'Sign-out incomplete' })).toBeVisible();
  await expect(second.getByRole('alert', { name: 'Sign-out incomplete' })).toBeVisible();
  expect(state.signouts).toBe(0);
  releaseSignin();
  await expect.poll(() => state.signedOut).toBe(true);
  expect(state.signoutCookie).toContain('test_session=new-session');
  expect(state.calls.indexOf('signin-response')).toBeLessThan(state.calls.indexOf('signout'));
  await expect(second.getByRole('button', { name: 'User menu', exact: true })).toHaveCount(0);
  await second.reload();
  await expect(second.getByRole('button', { name: 'Sign In', exact: true })).toBeVisible();
  expect((await page.context().cookies()).some(cookie => cookie.name === 'test_session')).toBe(false);
});

test('URL fallback preserves failed logout when storage and marker cookies are denied', async ({ page }) => {
  const state = await session(page);
  state.fail = true;
  await page.addInitScript(() => {
    const write = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === 'nerkhbaan-logout-pending') throw new DOMException('Storage denied', 'SecurityError');
      return write.call(this, key, value);
    };
    const cookie = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie')!;
    Object.defineProperty(Document.prototype, 'cookie', { get() { return cookie.get!.call(this); }, set(value) { if (String(value).startsWith('nerkhbaan-logout-pending=')) throw new DOMException('Cookie denied', 'SecurityError'); cookie.set!.call(this, value); } });
  });
  await page.goto('/');
  await leave(page);
  await expect(page.getByRole('button', { name: 'Retry sign-out' })).toBeEnabled();
  const profiles = state.profiles;
  await page.reload();
  await expect(page.getByRole('alert', { name: 'Sign-out incomplete' })).toBeVisible();
  expect(state.profiles).toBe(profiles);
  expect(page.url()).toContain('signout=pending');
  state.fail = false;
  await page.getByRole('button', { name: 'Retry sign-out' }).click();
  await expect(page.getByRole('alert', { name: 'Sign-out incomplete' })).toHaveCount(0);
  expect(page.url()).not.toContain('signout=pending');
});

test('a still-live push endpoint keeps logout incomplete after unsuccessful detach', async ({ page }) => {
  const state = await session(page);
  state.pushFails = true;
  await page.addInitScript(() => sessionStorage.setItem('test-push-stuck', 'true'));
  await page.goto('/');
  await leave(page);
  await expect(page.getByRole('button', { name: 'Retry sign-out' })).toBeEnabled();
  expect(state.signedOut).toBe(true);
  await expect(page.getByRole('alert', { name: 'Sign-out incomplete' })).toBeVisible();
  await page.evaluate(() => sessionStorage.removeItem('test-push-stuck'));
  state.pushFails = false;
  await page.getByRole('button', { name: 'Retry sign-out' }).click();
  await expect(page.getByRole('alert', { name: 'Sign-out incomplete' })).toHaveCount(0);
});

test('failed logout exposes a Persian retry notice with right-to-left text', async ({ page }) => {
  const state = await session(page);
  state.fail = true;
  await page.addInitScript(() => localStorage.setItem('language', 'fa'));
  await page.goto('/');
  await page.getByRole('button', { name: 'منوی کاربر', exact: true }).click();
  await page.getByRole('menuitem', { name: 'خروج از حساب', exact: true }).click();
  const notice = page.getByRole('alert', { name: 'خروج کامل نشده' });
  await expect(notice).toBeVisible();
  await expect(notice).toHaveAttribute('dir', 'rtl');
  await expect(page.getByRole('button', { name: 'تلاش دوباره برای خروج' })).toBeEnabled();
});
