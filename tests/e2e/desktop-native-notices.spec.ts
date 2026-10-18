import { expect, test, type Page, type WebSocketRoute } from '@playwright/test';

async function fixture(page: Page) {
  const state = { revision: 'native-rights-1', items: [] as Record<string, unknown>[], push: true, signedOut: false, sockets: [] as WebSocketRoute[] };
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.abort());
  await page.routeWebSocket('**/api/ws/prices', socket => { state.sockets.push(socket); socket.send(JSON.stringify({ event_type: 'snapshot', rights_revision: state.revision, prices: [] })); });
  await page.addInitScript(() => {
    localStorage.setItem('language', 'en'); sessionStorage.setItem('splash-shown', 'true');
    const data = { generation: 0, scope: null as null | { nonce: string; sessionGeneration: number; rightsEpoch: number }, enables: 0, revokes: 0, leases: 0, accept: true, shows: [] as unknown[], listeners: new Set<(value: unknown) => void>() };
    const bridge = {
      status: async () => ({ supported: true, optedIn: Boolean(data.scope), sessionGeneration: data.generation, rightsEpoch: data.scope?.rightsEpoch ?? 0, leaseActive: Boolean(data.scope), lastEvent: 'idle' }),
      enableSession: async (value: { sessionGeneration: number; rightsEpoch: number }) => {
        data.enables++; if (!data.accept) { data.generation++; return false; }
        data.scope = { nonce: 'a'.repeat(64), sessionGeneration: value.sessionGeneration, rightsEpoch: value.rightsEpoch }; return { ...data.scope };
      },
      refreshLease: async () => { data.leases++; return true; },
      showPending: async (value: unknown) => { data.shows.push(value); return true; },
      disableSession: async (value: { sessionGeneration: number }) => { data.revokes++; if (value.sessionGeneration === data.generation) { data.generation++; data.scope = null; } return true; },
      onOpenInbox: (listener: (value: unknown) => void) => { data.listeners.add(listener); return () => data.listeners.delete(listener); },
    };
    Object.defineProperty(window, 'electronAPI', { value: { notifications: bridge }, configurable: true });
    Object.assign(window, { __native: data });
  });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/me') await route.fulfill({ json: { id: 1, username: 'notice_test', full_name: 'Notice Test', email: 'notice@example.test', must_change_password: false, is_active: true, created_at: '2026-10-18T00:00:00Z' } });
    else if (path === '/api/auth/signout') { state.signedOut = true; await route.fulfill({ status: 204 }); }
    else if (path === '/api/notifications/preferences') await route.fulfill({ json: { push_app: state.push, silent_mode: true, aggressive_alerts: false, push_available: false, sms_available: false, email_available: false, telegram_available: false, sms_enabled: false, email_enabled: false, telegram_enabled: false, sms_verified: false, email_verified: false, telegram_verified: false, telegram_deeplink_available: false } });
    else if (path === '/api/notifications/preferences/push_app') { state.push = route.request().postDataJSON().enabled; await route.fulfill({ json: { push_app: state.push, silent_mode: true } }); }
    else if (path === '/api/notifications') await route.fulfill({ json: state.items });
    else if (path === '/api/prices') await route.fulfill({ json: { rights_revision: state.revision, assets: [], source: {}, refreshed_at: new Date().toISOString() } });
    else await route.fulfill({ json: [] });
  });
  return state;
}
const toggle = (page: Page) => page.getByRole('switch', { name: 'Windows notices for this session', exact: true });
const read = (page: Page) => page.evaluate(() => {
  const value = (window as unknown as { __native: { enables: number; revokes: number; shows: unknown[] } }).__native;
  return { enables: value.enables, revokes: value.revokes, shows: value.shows };
});
async function enable(page: Page) {
  await toggle(page).click(); await expect(toggle(page)).toBeChecked();
  await expect.poll(async () => (await read(page)).enables).toBe(1);
  await page.waitForFunction(() => Boolean((window as unknown as { __native: { scope: unknown; leases: number } }).__native.scope) && (window as unknown as { __native: { leases: number } }).__native.leases > 0);
}
test('native setting starts off, grants explicitly, and resets after reload', async ({ page }) => {
  await fixture(page); await page.goto('/#/settings'); await expect(toggle(page)).toBeEnabled(); await expect(toggle(page)).not.toBeChecked();
  expect((await read(page)).enables).toBe(0); await enable(page); await page.reload();
  await expect(toggle(page)).not.toBeChecked(); expect((await read(page)).enables).toBe(0);
});
test('canceled consent leaves switch off; browser push remains independent', async ({ page }) => {
  await fixture(page); await page.goto('/#/settings');
  await page.evaluate(() => { (window as unknown as { __native: { accept: boolean } }).__native.accept = false; });
  await toggle(page).click(); await expect.poll(async () => (await read(page)).enables).toBe(1); await expect(toggle(page)).not.toBeChecked();
  expect((await read(page)).shows).toEqual([]);
  await expect(page.getByRole('switch', { name: 'In-App Notifications', exact: true })).toBeChecked();
});
test('new trigger gives generic bridge payload and current click opens inbox; global off revokes', async ({ page }) => {
  const state = await fixture(page); await page.clock.install(); await page.goto('/#/settings'); await enable(page);
  await page.waitForTimeout(100);
  const created = await page.evaluate(() => new Date(Date.now() + 1_000).toISOString());
  state.items = [{ id: 2, resource_type: 'alert_trigger', resource_id: '9223372036854775807', read_at: null, created_at: created, title: 'private value 999', message: 'private token <xml> https://private.invalid' }];
  await page.clock.fastForward(15_000); await expect.poll(async () => (await read(page)).shows.length).toBe(1);
  expect(JSON.stringify((await read(page)).shows)).not.toMatch(/private|999|xml|https/);
  await page.evaluate(() => { const data = (window as unknown as { __native: { scope: unknown; listeners: Set<(scope: unknown) => void> } }).__native; data.listeners.forEach(listener => listener(data.scope)); });
  await expect(page.getByRole('region', { name: 'Notification list', exact: true })).toBeVisible();
  await page.getByRole('switch', { name: 'In-App Notifications', exact: true }).uncheck();
  await expect(toggle(page)).not.toBeChecked(); await expect.poll(async () => (await read(page)).revokes).toBeGreaterThan(0);
});
test('rights hint on settings route revokes; old click and old trigger cannot restore session', async ({ page }) => {
  const state = await fixture(page); await page.goto('/#/settings'); await enable(page);
  expect(state.sockets.length).toBe(1); state.revision = 'native-rights-2'; state.sockets[0].send(JSON.stringify({ event_type: 'heartbeat', rights_revision: state.revision }));
  await expect(toggle(page)).not.toBeChecked(); await expect.poll(async () => (await read(page)).revokes).toBeGreaterThan(0);
  expect((await read(page)).shows).toEqual([]); expect((await read(page)).enables).toBe(1);
});
test('logout and auth expiry revoke before any later native work', async ({ page }) => {
  const state = await fixture(page); await page.goto('/#/settings'); await enable(page);
  await page.evaluate(() => window.dispatchEvent(new Event('auth-expired')));
  await expect.poll(async () => (await read(page)).revokes).toBeGreaterThan(0);
  await expect.poll(() => state.signedOut).toBe(true); expect((await read(page)).shows).toEqual([]);
});
