import { expect, test, type Page, type Route } from '@playwright/test';

type RecordValue = Record<string, unknown>;
type FixtureOptions = {
  language?: 'fa' | 'en';
  preferences?: RecordValue;
  alerts?: RecordValue[];
  preferencesHandler?: (route: Route, index: number) => Promise<void>;
  saveHandler?: (route: Route) => Promise<void>;
};
const readyPreferences: RecordValue = {
  push_app: true, sms_enabled: true, sms_verified: true, sms_phone: '+989120000000',
  sms_available: true, voip_available: true, voip_critical_only: true,
  email_enabled: true, email_verified: true, email_address: 'owned@example.invalid',
  email_available: true, push_available: false, telegram_available: false,
  telegram_enabled: false, telegram_id: null, telegram_verified: false,
  telegram_deeplink_available: false, silent_mode: false, aggressive_alerts: false,
};
const savedAlert: RecordValue = {
  id: 7, asset: 'gold', condition: 'above', target_price: 1250, currency_mode: 'toman',
  price_source_mode: 'reference', notify_app: true, notify_email: true,
  notify_sms: true, notify_voip: true, priority: 'critical',
  notify_webhook: false, webhook_url: null, enable_dlq: false, notify_telegram: false,
  alert_type: 'price', formula: null, is_active: true, instrument_id: null,
  mode: 'recurring', cooldown_seconds: 900, max_notifications_per_day: 3,
};

async function fixture(page: Page, options: FixtureOptions = {}) {
  const language = options.language ?? 'en';
  const mutations: Array<{ method: string; body: RecordValue }> = [];
  const forbidden: string[] = [];
  let alerts = options.alerts ?? [];
  let preferences = { ...readyPreferences, ...options.preferences };
  let preferenceReads = 0;
  await page.addInitScript(({ language }) => {
    localStorage.setItem('language', language);
    localStorage.setItem('currencyMode', 'toman');
    sessionStorage.setItem('splash-shown', 'true');
  }, { language });
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname)
    ? route.continue() : route.abort());
  await page.routeWebSocket('**/api/ws/prices', () => {});
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    if (!['localhost', '127.0.0.1'].includes(url.hostname)) return route.abort();
    const path = url.pathname;
    const method = route.request().method();
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { id: 1, username: 'owned_alert_fixture', must_change_password: false } });
    if (path.endsWith('/notifications/preferences')) {
      const index = ++preferenceReads;
      if (options.preferencesHandler) return options.preferencesHandler(route, index);
      return route.fulfill({ json: preferences });
    }
    if (/\/alerts(?:\/\d+)?$/.test(path)) {
      if (method === 'GET') return route.fulfill({ json: alerts });
      if (method !== 'POST' && method !== 'PATCH') { forbidden.push(path); return route.fulfill({ status: 403, json: { detail: 'Unexpected fixture mutation' } }); }
      const body = route.request().postDataJSON() as RecordValue;
      mutations.push({ method, body });
      if (options.saveHandler) return options.saveHandler(route);
      const id = Number(path.split('/').at(-1)) || mutations.length;
      const saved = { ...savedAlert, notify_sms: false, notify_voip: false, priority: 'normal',
        ...alerts.find(alert => alert.id === id), id, ...body };
      alerts = [...alerts.filter(alert => alert.id !== id), saved];
      return route.fulfill({ json: saved });
    }
    if (method !== 'GET') {
      forbidden.push(path);
      return route.fulfill({ status: 403, json: { detail: 'Real delivery is forbidden in this fixture' } });
    }
    if (path.endsWith('/prices')) return route.fulfill({ json: { rights_revision: 'alert-communications-fixture-v1', assets: [], source: {} } });
    if (path.endsWith('/history')) return route.fulfill({ json: { asset: 'gold', rights_revision: 'alert-communications-fixture-v1', points: [] } });
    return route.fulfill({ json: [] });
  });
  return { mutations, forbidden, setPreferences: (patch: RecordValue) => { preferences = { ...preferences, ...patch }; } };
}

const sms = (page: Page) => page.getByRole('switch', { name: 'SMS', exact: true });
const voip = (page: Page) => page.getByRole('switch', { name: 'Phone call', exact: true });
async function openCreate(page: Page) {
  await page.goto('/alerts');
  await page.getByRole('button', { name: 'New Alert', exact: true }).click();
  await expect(sms(page)).toBeEnabled();
  await page.getByLabel('Target', { exact: true }).fill('1350');
}

test('new alert keeps optional delivery off and resets after a configured save', async ({ page }) => {
  const state = await fixture(page);
  await openCreate(page);
  await expect(sms(page)).not.toBeChecked();
  await expect(voip(page)).not.toBeChecked();
  await expect(page.getByLabel('Alert severity')).toHaveValue('normal');
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await expect.poll(() => state.mutations.length).toBe(1);
  expect(state.mutations[0]).toMatchObject({ method: 'POST', body: {
    notify_sms: false, notify_voip: false, priority: 'normal', notify_app: true, notify_email: false,
  } });
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'New Alert', exact: true }).click();
  await expect(sms(page)).toBeEnabled();
  await sms(page).click();
  await page.getByLabel('Alert severity').selectOption('critical');
  await expect(voip(page)).toBeEnabled();
  await voip(page).click();
  await page.getByRole('switch', { name: 'Email', exact: true }).click();
  await page.getByLabel('Target', { exact: true }).fill('1450');
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await expect.poll(() => state.mutations.length).toBe(2);
  expect(state.mutations[1].body).toMatchObject({ notify_sms: true, notify_voip: true, priority: 'critical', notify_email: true });
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'New Alert', exact: true }).click();
  await expect(sms(page)).not.toBeChecked();
  await expect(voip(page)).not.toBeChecked();
  await expect(page.getByLabel('Alert severity')).toHaveValue('normal');
  expect(state.forbidden).toEqual([]);
});

test('verified active number and critical policy gate optional calls', async ({ page }) => {
  const state = await fixture(page);
  await openCreate(page);
  await expect(voip(page)).toBeDisabled();
  await expect(page.getByText('The current policy allows calls for critical alerts only.', { exact: true })).toBeVisible();
  await page.getByLabel('Alert severity').selectOption('critical');
  await voip(page).click();
  await page.getByLabel('Alert severity').selectOption('normal');
  await expect(voip(page)).toBeChecked();
  await expect(voip(page)).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Create', exact: true })).toBeDisabled();
  await voip(page).click();
  await expect(page.getByRole('button', { name: 'Create', exact: true })).toBeEnabled();
  expect(state.mutations).toHaveLength(0);
  expect(state.forbidden).toEqual([]);
});

for (const changed of [{ sms_verified: false }, { sms_enabled: false }, { sms_phone: null }]) {
  test(`phone prerequisite ${Object.keys(changed)[0]} cannot enable SMS or calls`, async ({ page }) => {
    const state = await fixture(page, { preferences: changed });
    await page.goto('/alerts');
    await page.getByRole('button', { name: 'New Alert', exact: true }).click();
    await expect(page.getByText('Verify and enable your alert number in Settings.', { exact: true })).toHaveCount(2);
    await expect(sms(page)).toBeDisabled();
    await page.getByLabel('Alert severity').selectOption('critical');
    await expect(voip(page)).toBeDisabled();
    await page.getByRole('link', { name: 'Verify and enable your number in Settings' }).click();
    await expect(page).toHaveURL(/\/settings$/);
    expect(state.mutations).toHaveLength(0);
    expect(state.forbidden).toEqual([]);
  });
}

test('service readiness blocks only the unavailable channel', async ({ page }) => {
  const state = await fixture(page, { preferences: { sms_available: false, voip_available: true, voip_critical_only: false } });
  await page.goto('/alerts');
  await page.getByRole('button', { name: 'New Alert', exact: true }).click();
  await expect(page.getByText('SMS service is currently unavailable.', { exact: true })).toBeVisible();
  await expect(sms(page)).toBeDisabled();
  await expect(voip(page)).toBeEnabled();
  await voip(page).click();
  await page.getByLabel('Target', { exact: true }).fill('1350');
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await expect.poll(() => state.mutations.length).toBe(1);
  expect(state.mutations[0].body).toMatchObject({ notify_sms: false, notify_voip: true, priority: 'normal' });
  expect(state.forbidden).toEqual([]);
});

test('editing preserves delivery choices and email without changing the saved price policy', async ({ page }) => {
  const state = await fixture(page, { alerts: [savedAlert] });
  await page.goto('/alerts');
  await page.getByRole('button', { name: 'Edit Alert', exact: true }).click();
  await expect(sms(page)).toBeChecked();
  await expect(voip(page)).toBeChecked();
  await expect(page.getByRole('switch', { name: 'Email', exact: true })).toBeChecked();
  await expect(page.getByLabel('Alert severity')).toHaveValue('critical');
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeEnabled();
  await page.getByLabel('Target', { exact: true }).fill('1500');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect.poll(() => state.mutations.length).toBe(1);
  expect(state.mutations[0]).toEqual({ method: 'PATCH', body: { asset: 'gold', target_price: 1500,
    currency_mode: 'toman', price_source_mode: 'reference', condition: 'above', notify_app: true,
    notify_email: true, notify_sms: true, notify_voip: true, priority: 'critical' } });
  expect(state.forbidden).toEqual([]);
});

test('unavailable saved channels remain selected and can always be turned off', async ({ page }) => {
  const state = await fixture(page, { alerts: [savedAlert], preferences: { sms_available: false, voip_available: false } });
  await page.goto('/alerts');
  await page.getByRole('button', { name: 'Edit Alert', exact: true }).click();
  await expect(page.getByText('SMS service is currently unavailable.', { exact: true })).toBeVisible();
  await expect(sms(page)).toBeChecked();
  await expect(voip(page)).toBeChecked();
  await expect(sms(page)).toBeEnabled();
  await expect(voip(page)).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeDisabled();
  await sms(page).click();
  await voip(page).click();
  await expect(sms(page)).toBeDisabled();
  await expect(voip(page)).toBeDisabled();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect.poll(() => state.mutations.length).toBe(1);
  expect(state.mutations[0].body).toMatchObject({ notify_sms: false, notify_voip: false, priority: 'critical', notify_email: true });
  expect(state.forbidden).toEqual([]);
});

test('failed readiness can be retried without resetting form choices', async ({ page }) => {
  const state = await fixture(page, { preferencesHandler: (route, index) => index === 1
    ? route.fulfill({ status: 503, json: { detail: 'Fixture not ready' } })
    : route.fulfill({ json: readyPreferences }) });
  await page.goto('/alerts');
  await page.getByRole('button', { name: 'New Alert', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Check service again' })).toBeVisible();
  await expect(sms(page)).toBeDisabled();
  await expect(voip(page)).toBeDisabled();
  await page.getByLabel('Target', { exact: true }).fill('1600');
  await page.getByRole('switch', { name: 'Email', exact: true }).click();
  await page.getByLabel('Alert severity').selectOption('critical');
  await page.getByRole('button', { name: 'Check service again' }).click();
  await expect(sms(page)).toBeEnabled();
  await expect(voip(page)).toBeEnabled();
  await expect(page.getByLabel('Target', { exact: true })).toHaveValue('1600');
  await expect(page.getByRole('switch', { name: 'Email', exact: true })).toBeChecked();
  await sms(page).click();
  await voip(page).click();
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await expect.poll(() => state.mutations.length).toBe(1);
  expect(state.mutations[0].body).toMatchObject({ target_price: 1600, notify_email: true, notify_sms: true, notify_voip: true, priority: 'critical' });
  expect(state.forbidden).toEqual([]);
});

test('one pending save cannot create duplicate alerts or change choices', async ({ page }) => {
  let release = () => {};
  const pending = new Promise<void>(resolve => { release = resolve; });
  const state = await fixture(page, { saveHandler: async route => { await pending; await route.fulfill({ json: { ...savedAlert,
    ...(route.request().postDataJSON() as RecordValue), id: 1 } }); } });
  await openCreate(page);
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await expect.poll(() => state.mutations.length).toBe(1);
  await expect(page.getByLabel('Target', { exact: true })).toBeDisabled();
  await expect(page.getByLabel('Alert severity')).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
  await page.getByLabel('Target', { exact: true }).press('Enter');
  expect(state.mutations).toHaveLength(1);
  release();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(state.forbidden).toEqual([]);
});

test('late closed readiness does not enable a newly opened form', async ({ page }) => {
  let release = () => {};
  const pending = new Promise<void>(resolve => { release = resolve; });
  let firstStarted = false;
  const state = await fixture(page, { preferencesHandler: async (route, index) => {
    if (index === 1) {
      firstStarted = true;
      await pending;
      await route.fulfill({ json: readyPreferences }).catch(() => undefined);
    } else await route.fulfill({ json: { ...readyPreferences, sms_available: false, voip_available: false } });
  } });
  await page.goto('/alerts');
  await page.getByRole('button', { name: 'New Alert', exact: true }).click();
  await expect.poll(() => firstStarted).toBe(true);
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'New Alert', exact: true }).click();
  await expect(page.getByText('SMS service is currently unavailable.', { exact: true })).toBeVisible();
  release();
  await expect(sms(page)).toBeDisabled();
  await page.getByLabel('Alert severity').selectOption('critical');
  await expect(voip(page)).toBeDisabled();
  expect(state.mutations).toHaveLength(0);
  expect(state.forbidden).toEqual([]);
});

test('Persian form stays readable at the viewport edge and keeps explicit consent choices', async ({ page }, testInfo) => {
  const state = await fixture(page, { language: 'fa' });
  await page.goto('/alerts');
  await page.getByRole('button', { name: 'هشدار جدید', exact: true }).click();
  await expect(page.getByRole('switch', { name: 'پیامک', exact: true })).toBeEnabled();
  await expect(page.getByRole('switch', { name: 'تماس تلفنی', exact: true })).toBeDisabled();
  await page.getByLabel('شدت هشدار').selectOption('critical');
  await expect(page.getByRole('switch', { name: 'تماس تلفنی', exact: true })).toBeEnabled();
  await expect(page.getByRole('switch', { name: 'تماس تلفنی', exact: true })).not.toBeChecked();
  const dialog = page.getByRole('dialog');
  const bounds = await dialog.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  await dialog.screenshot({ path: testInfo.outputPath('alert-communications-fa.png') });
  expect(state.mutations).toHaveLength(0);
  expect(state.forbidden).toEqual([]);
});
