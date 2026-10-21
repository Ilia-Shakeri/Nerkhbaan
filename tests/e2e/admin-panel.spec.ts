import { expect, test, type Page } from '@playwright/test';
import { adminTestUrl } from './admin-fixture-url';

const sections = [
  ['dashboard', 'Operations', 'admin.health.read', '/dashboard'],
  ['users', 'Users', 'admin.users.read', '/users'],
  ['roles', 'Access', 'admin.roles.read', '/roles'],
  ['support', 'Support', 'admin.support.read', '/support/tickets'],
  ['telegram', 'Telegram', 'admin.telegram.read', '/telegram/sources'],
  ['dlq', 'Dead-letter queue', 'admin.dlq.read', '/jobs/dlq'],
  ['providers', 'Providers', 'admin.providers.read', '/providers'],
  ['pricing', 'Pricing', 'admin.pricing.read', '/pricing/instruments'],
  ['jobs', 'Jobs & DLQ', 'admin.jobs.read', '/jobs'],
  ['settings', 'Settings', 'admin.settings.read', '/settings'],
  ['alerts', 'Alerts', 'admin.alerts.read', '/alerts'],
  ['communications', 'مرکز ارتباطات', 'admin.settings.read', '/communications'],
  ['backups', 'Backup evidence', 'admin.health.read', '/backups/status'],
  ['security', 'My security', '', '/auth/mfa'],
  ['audit', 'Audit', 'admin.audit.read', '/audit'],
] as const;
type RecordValue = Record<string, unknown>;
const user = { id: 2, username: 'owned_fixture', full_name: 'Owned fixture', email: 'owned@example.invalid', is_active: true, must_change_password: false };
const role = { id: 2, name: 'fixture_role', description: 'Owned fixture role', is_active: true, is_system: false, permissions: ['admin.roles.read'] };
const channels = { version: 1, encryption_ready: false,
  channels: Object.fromEntries(['sms', 'voip'].map(channel => [channel, { version: 0, enabled: false, provider_id: 'none', ready: false, config: {}, credentials: { configured: false, masked: null } }])),
  call_policy: { version: 0, enabled: false, critical_only: true, persist_seconds: 60, max_attempts: 1, cooldown_seconds: 900, max_calls_per_day: 3,
    quiet_hours: { enabled: true, start: '22:00', end: '08:00', timezone: 'Asia/Tehran', critical_bypass: false } }, provider_catalog: [], test_recipients: [] };

async function panel(page: Page, permissions: string[], profile: RecordValue = {}) {
  const reads: string[] = [], unexpected: string[] = [];
  const writes: Array<{ path: string; body: RecordValue }> = [];
  const errors: string[] = [];
  let failure = '', failStatus = 0, delayedWrite: Promise<void> | null = null;
  let mfaError = false;
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => ['127.0.0.1', 'localhost'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.abort());
  await page.route('**/api/admin/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) return route.abort();
    const path = url.pathname.replace('/api/admin', '');
    if (request.method() !== 'GET') {
      const body = request.postDataJSON() ?? {};
      writes.push({ path, body });
      if (path === '/auth/reauthenticate') return route.fulfill({ json: { reauthenticated: true } });
      if (delayedWrite) await delayedWrite;
      if (failure === path) return route.fulfill({ status: failStatus, json: { detail: 'Owned fixture response' } });
      if (/^\/users\/2\/state$/.test(path)) return route.fulfill({ json: { ...user, is_active: body.is_active } });
      if (/^\/administrators\/2\/roles$/.test(path)) return route.fulfill({ json: { id: 2, roles: body.roles } });
      unexpected.push(path);
      return route.fulfill({ status: 403, json: { detail: 'Mutation outside fixture' } });
    }
    reads.push(path);
    if (path === '/auth/me') return route.fulfill({ json: { admin: { id: 1, username: 'test_operator', full_name: 'Test operator', email: 'test@example.invalid', roles: ['fixture'], permissions,
      must_change_password: false, mfa_required: false, mfa_enabled: false, session_expires_at: '2099-01-01T00:00:00Z', ...profile } } });
    if (path === '/auth/csrf') return route.fulfill({ json: { csrf_token: 'test-only-csrf' } });
    if (path === '/auth/mfa') return mfaError ? route.fulfill({ status: 503, json: { detail: 'Security state unavailable' } })
      : route.fulfill({ json: { enabled: false, pending: false, backup_codes_remaining: 0 } });
    if (path === '/users') return route.fulfill({ json: { items: [user], total: 1 } });
    if (path === '/roles') return route.fulfill({ json: { items: [role] } });
    if (path === '/administrators') return route.fulfill({ json: { items: [{ ...user, roles: ['fixture_role'] }] } });
    if (path === '/permissions') return route.fulfill({ json: { items: [{ key: 'admin.roles.read', description: 'Read roles' }] } });
    if (path === '/settings') return route.fulfill({ json: { operational_settings: [], feature_flags: [], allowed_keys: [], instrument_scopes: [], provider_scopes: [], telegram_scopes: [], environment: {} } });
    if (path === '/communications') return route.fulfill({ json: channels });
    if (path === '/jobs') return route.fulfill({ json: { admin_jobs: [], backfill_jobs: [], delivery_jobs: [], totals: {} } });
    if (path === '/dashboard' || path === '/backups/status') return route.fulfill({ json: { status: 'owned_fixture' } });
    if (['/support/tickets', '/support/assignees', '/telegram/sources', '/jobs/dlq', '/providers', '/providers/drafts', '/pricing/instruments', '/pricing/anomalies', '/settings/effective', '/alerts', '/audit', '/communications/deliveries'].includes(path)) {
      return route.fulfill({ json: { items: [], total: 0, recent_rejections: [], instrument_ids: [] } });
    }
    unexpected.push(path);
    return route.fulfill({ status: 404, json: { detail: 'Unknown fixture route' } });
  });
  return { reads, writes, unexpected, errors, fail: (path: string, status: number) => { failure = path; failStatus = status; },
    delay: (value: Promise<void> | null) => { delayedWrite = value; }, failMfa: (value: boolean) => { mfaError = value; } };
}

for (const [section, title, permission, resource] of sections) {
  test(`limited profile renders ${section} with current data and no operational write`, async ({ page }) => {
    const state = await panel(page, permission ? [permission] : []);
    await page.goto(adminTestUrl(`/#/${section}`));
    await expect(page.locator('.workspace-header h1')).toHaveText(title);
    await expect(page.getByText('Loading current data…', { exact: true })).toHaveCount(0);
    await expect.poll(() => state.reads.includes(resource)).toBe(true);
    await expect(page.locator('.error-banner')).toHaveCount(0);
    expect(state.writes).toEqual([]);
    expect(state.unexpected).toEqual([]);
    expect(state.errors).toEqual([]);
    if (section === 'roles') expect(state.reads).not.toContain('/users');
    if (section === 'jobs') expect(state.reads).not.toContain('/jobs/dlq');
    if (section === 'users') {
      await expect(page.getByRole('button', { name: 'Disable', exact: true })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Force password change', exact: true })).toHaveCount(0);
    }
    if (section === 'communications') await expect(page.getByRole('button', { name: 'ذخیرهٔ اتصال' })).toHaveCount(0);
  });
}

test('unpermitted direct route uses an allowed page without a forbidden read', async ({ page }) => {
  const state = await panel(page, ['admin.settings.read']);
  await page.goto(adminTestUrl('/#/users'));
  await expect(page.locator('.workspace-header h1')).toHaveText('Settings');
  await expect(page.getByRole('button', { name: 'Users', exact: true })).toHaveCount(0);
  expect(state.reads).not.toContain('/users');
  expect(state.writes).toEqual([]);
});

test('required MFA keeps all operational routes locked', async ({ page }) => {
  const state = await panel(page, sections.map(item => item[2]).filter(Boolean), { mfa_required: true });
  await page.goto(adminTestUrl('/#/users'));
  await expect(page.locator('.workspace-header h1')).toHaveText('My security');
  await expect(page.locator('.sidebar nav button')).toHaveCount(1);
  expect(state.reads.filter(path => !path.startsWith('/auth/'))).toEqual([]);
  expect(state.writes).toEqual([]);
});

test('security read failure blocks enrollment until a successful refresh', async ({ page }) => {
  const state = await panel(page, []);
  state.failMfa(true);
  await page.goto(adminTestUrl('/#/security'));
  await expect(page.getByRole('alert')).toContainText('Security state unavailable');
  await page.getByLabel('Current password for sensitive changes', { exact: true }).fill('fixture-only-password');
  await expect(page.getByRole('button', { name: 'Start MFA enrollment', exact: true })).toBeDisabled();
  state.failMfa(false);
  await page.getByRole('button', { name: 'Reload current data', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Start MFA enrollment', exact: true })).toBeEnabled();
  expect(state.writes).toEqual([]);
});

async function openDisable(page: Page) {
  await page.goto(adminTestUrl('/#/users'));
  await page.getByLabel('Change reason', { exact: true }).fill('Owned fixture check');
  await page.getByRole('button', { name: 'Disable', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Current administrator password', { exact: true }).fill('fixture-only-password');
  await dialog.getByLabel('Type DISABLE USER 2', { exact: true }).fill('DISABLE USER 2');
  return dialog;
}

test('dangerous action submits once even when two native submit events race', async ({ page }) => {
  const state = await panel(page, ['admin.users.read', 'admin.users.manage']);
  let release = () => {};
  const pending = new Promise<void>(resolve => { release = resolve; });
  state.delay(pending);
  const dialog = await openDisable(page);
  await dialog.evaluate(form => { (form as HTMLFormElement).requestSubmit(); (form as HTMLFormElement).requestSubmit(); });
  await expect.poll(() => state.writes.filter(item => item.path === '/users/2/state').length).toBe(1);
  expect(state.writes.filter(item => item.path === '/auth/reauthenticate')).toHaveLength(1);
  await expect(dialog.locator('button[type="submit"]')).toBeDisabled();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeVisible();
  release();
  await expect(dialog).toHaveCount(0);
  expect(state.writes.find(item => item.path === '/users/2/state')?.body).toMatchObject({ is_active: false, confirmation: 'DISABLE USER 2', reason: 'Owned fixture check' });
  expect(state.unexpected).toEqual([]);
});

for (const status of [409, 503]) {
  test(`dangerous ${status} stops a repeated write until close and refresh`, async ({ page }) => {
    const state = await panel(page, ['admin.users.read', 'admin.users.manage']);
    state.fail('/users/2/state', status);
    const dialog = await openDisable(page);
    await dialog.getByRole('button', { name: 'Confirm action', exact: true }).click();
    await expect(dialog.getByText('Owned fixture response', { exact: true })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Confirm action', exact: true })).toBeDisabled();
    const before = state.reads.filter(path => path === '/users').length;
    await dialog.getByRole('button', { name: 'Close and reload', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect.poll(() => state.reads.filter(path => path === '/users').length).toBeGreaterThan(before);
    expect(state.writes.filter(item => item.path === '/users/2/state')).toHaveLength(1);
  });
}

test('role manager without directory read can select an existing administrator', async ({ page }) => {
  const state = await panel(page, ['admin.roles.read', 'admin.roles.manage']);
  await page.goto(adminTestUrl('/#/roles'));
  await expect(page.getByRole('button', { name: 'Edit roles', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Edit roles', exact: true }).click();
  await expect(page.getByRole('combobox', { name: 'User', exact: true })).toHaveValue('2');
  await expect(page.getByLabel('Find user', { exact: true })).toHaveCount(0);
  expect(state.reads).not.toContain('/users');
  expect(state.writes).toEqual([]);
});
