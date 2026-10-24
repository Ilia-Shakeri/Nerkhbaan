import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { _electron } from '@playwright/test';

const root = path.resolve(import.meta.dirname, '..');
const temporaryRoot = path.resolve(os.tmpdir());
const executable = path.resolve(process.env.NERKHBAAN_DESKTOP_EXECUTABLE || path.join(root, 'apps/desktop/release/win-unpacked/Nerkhbaan.exe'));
const receiptPath = process.env.NERKHBAAN_DESKTOP_SMOKE_RECEIPT;
const expectedVersion = (await readFile(path.join(root, 'VERSION'), 'utf8')).trim();
// Reserve evidence before launching so a repeated run cannot replace an earlier result.
if (receiptPath) {
  await mkdir(path.dirname(path.resolve(receiptPath)), { recursive: true });
  await writeFile(receiptPath, JSON.stringify({ schema: 1, passed: false, state: 'started', expected_version: expectedVersion }), { flag: 'wx' });
}
const profile = await mkdtemp(path.join(temporaryRoot, 'nerkhbaan-desktop-smoke-'));
const receipt = { schema: 1, checked_at_utc: new Date().toISOString(), executable, scope: 'Actual packaged Windows runtime with synthetic intercepted authentication and initial network blocked by a loopback discard proxy; no production account or server login', passed: false };
let application;
try {
  const legalNotices = {};
  for (const [source, bundled] of [['LICENSE', 'LICENSE-Nerkhbaan.txt'], ['NOTICE', 'NOTICE-Nerkhbaan.txt'], ['docs/license-scope.md', 'LICENSE-SCOPE.md']]) {
    const expected = await readFile(path.join(root, source));
    const actual = await readFile(path.join(path.dirname(executable), bundled));
    assert.deepEqual(actual, expected, `Packaged legal notice must preserve ${source}`);
    legalNotices[bundled] = createHash('sha256').update(actual).digest('hex');
  }
  receipt.legal_notices_sha256 = legalNotices;
  const archive = path.join(path.dirname(executable), 'resources', 'app.asar');
  const archiveHash = createHash('sha256').update(await readFile(archive)).digest('hex');
  application = await _electron.launch({
    executablePath: executable,
    args: [`--user-data-dir=${profile}`, '--proxy-server=http://127.0.0.1:9', '--proxy-bypass-list=<-loopback>'],
    timeout: 60_000,
  });
  const page = await application.firstWindow();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  receipt.page_errors = pageErrors;
  await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().forEach(window => window.hide()));
  const credentials = { access_token: 'smoke-access-token-never-valid', refresh_token: 'smoke-refresh-token-never-valid-000' };
  const user = { id: -1, username: 'desktop_smoke', full_name: 'Desktop Smoke', email: 'desktop-smoke@example.invalid', is_active: true, must_change_password: false, created_at: '2026-10-11T00:00:00Z' };
  let signedIn = false;
  let signoutCalls = 0;
  let desktopSigninHeader = false;
  const endpointCounts = {};
  receipt.endpoint_counts = endpointCounts;
  await application.context().route(/^https?:\/\//, async route => {
    const url = new URL(route.request().url());
    const endpoint = `${route.request().method()} ${url.pathname}`;
    endpointCounts[endpoint] = (endpointCounts[endpoint] || 0) + 1;
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: { 'access-control-allow-origin': 'nerkhbaan://app', 'access-control-allow-methods': 'GET,POST,DELETE,PATCH,OPTIONS', 'access-control-allow-headers': 'authorization,content-type,x-client-type' } });
      return;
    }
    if (url.pathname.endsWith('/auth/signin')) {
      signedIn = true;
      desktopSigninHeader = route.request().headers()['x-client-type'] === 'desktop';
      await route.fulfill({ headers: { 'access-control-allow-origin': 'nerkhbaan://app' }, json: { ...credentials, token_type: 'bearer', user } });
    } else if (url.pathname.endsWith('/auth/me')) {
      await route.fulfill(signedIn ? { headers: { 'access-control-allow-origin': 'nerkhbaan://app' }, json: user } : { status: 401, headers: { 'access-control-allow-origin': 'nerkhbaan://app' }, json: { detail: 'Smoke profile has no account' } });
    } else if (url.pathname.endsWith('/auth/signout')) {
      signedIn = false;
      signoutCalls++;
      await route.fulfill({ headers: { 'access-control-allow-origin': 'nerkhbaan://app' }, json: { message: 'Synthetic session revoked' } });
    } else {
      await route.fulfill({ headers: { 'access-control-allow-origin': 'nerkhbaan://app' }, json: [] });
    }
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /ورود به حساب|Sign In/ }).waitFor({ timeout: 40_000 });
  const runtime = await application.evaluate(({ app }) => ({ packaged: app.isPackaged, profile: app.getPath('userData'), version: app.getVersion() }));
  assert.equal(runtime.packaged, true);
  assert.equal(runtime.version, expectedVersion, 'Packaged runtime must match the source release');
  assert.equal(path.resolve(runtime.profile), path.resolve(profile));
  assert.match(page.url(), /^nerkhbaan:\/\/app\/index\.html#/);
  assert.equal(await page.evaluate(() => window.isSecureContext), true);
  assert.equal(await page.evaluate(() => Boolean(window.electronAPI?.auth)), true);
  const nativeBridge = await page.evaluate(async () => {
    const bridge = window.electronAPI?.notifications;
    if (!bridge) return null;
    const initial = await bridge.status();
    const stop = bridge.onOpenInbox(() => {});
    stop(); stop();
    return {
      methods: Object.keys(bridge).sort(), frozen: Object.isFrozen(bridge), initial,
      malformedEnable: await bridge.enableSession({ version: 0 }),
      malformedShow: await bridge.showPending({ version: 0 }),
      malformedLease: await bridge.refreshLease({ version: 0 }),
    };
  });
  assert.ok(nativeBridge);
  assert.deepEqual(nativeBridge.methods, ['disableSession', 'enableSession', 'onOpenInbox', 'refreshLease', 'showPending', 'status']);
  assert.equal(nativeBridge.frozen, true);
  assert.equal(typeof nativeBridge.initial.supported, 'boolean');
  assert.equal(nativeBridge.initial.optedIn, false);
  assert.equal(nativeBridge.initial.leaseActive, false);
  assert.equal(nativeBridge.malformedEnable, false);
  assert.equal(nativeBridge.malformedShow, false);
  assert.equal(nativeBridge.malformedLease, false);
  const assetStatus = await page.evaluate(async () => (await fetch('nerkhbaan://app/icons/logo.png')).status);
  assert.equal(assetStatus, 200);
  const blocked = await application.evaluate(async ({ net }) => {
    const responses = await Promise.all(['nerkhbaan://evil/index.html', 'nerkhbaan://app/%2e%2e/package.json'].map(async url => (await net.fetch(url)).status));
    return responses;
  });
  assert.ok(blocked.every(status => status >= 400));
  const roundtrip = await page.evaluate(async value => {
    await window.electronAPI.auth.setCredentials(value);
    const stored = await window.electronAPI.auth.getCredentials();
    await window.electronAPI.auth.clearCredentials();
    return { stored, cleared: await window.electronAPI.auth.getCredentials() };
  }, credentials);
  assert.deepEqual(roundtrip.stored, credentials);
  assert.equal(roundtrip.cleared, null);
  await page.locator('input[name="username"]').fill('desktop_smoke');
  await page.locator('#auth-password').fill('smoke-password-never-valid-000');
  await page.getByRole('button', { name: /ورود به حساب|Sign In/ }).click();
  await page.getByRole('button', { name: /منوی کاربر|User menu/ }).waitFor({ timeout: 40_000 });
  assert.equal(desktopSigninHeader, true);
  assert.deepEqual(await page.evaluate(() => window.electronAPI.auth.getCredentials()), credentials);
  const encrypted = await readFile(path.join(profile, 'session-credentials.bin'));
  assert.ok(encrypted.length > 0);
  assert.equal(encrypted.includes(Buffer.from(credentials.access_token)), false);
  assert.equal(encrypted.includes(Buffer.from(credentials.refresh_token)), false);
  const signoutBefore = signoutCalls;
  await page.getByRole('button', { name: /منوی کاربر|User menu/ }).click();
  await page.getByRole('menuitem', { name: /خروج از حساب|Logout/ }).click();
  await page.getByRole('button', { name: /ورود به حساب|Sign In/ }).waitFor({ timeout: 15_000 });
  await page.waitForFunction(async () => await window.electronAPI.auth.getCredentials() === null, null, { timeout: 15_000 });
  assert.ok(signoutCalls > signoutBefore);
  await assert.rejects(readFile(path.join(profile, 'session-credentials.bin')), { code: 'ENOENT' });
  const nativeAfterLogout = await page.evaluate(() => window.electronAPI.notifications.status());
  assert.equal(nativeAfterLogout.optedIn, false);
  assert.equal(nativeAfterLogout.leaseActive, false);
  assert.ok(nativeAfterLogout.sessionGeneration > nativeBridge.initial.sessionGeneration);
  assert.equal(createHash('sha256').update(await readFile(archive)).digest('hex'), archiveHash, 'Packaged code must remain unchanged during acceptance');
  const appUrl = new URL(page.url());
  Object.assign(receipt, { packaged: runtime.packaged, version: runtime.version, secure_context: true, local_origin: `${appUrl.protocol}//${appUrl.host}`, asset_http_status: assetStatus, blocked_paths: blocked, synthetic_ui_signin: true, synthetic_ui_signout: true, encrypted_at_rest: true, session_file_removed_on_logout: true, passed: true });
  Object.assign(receipt, { native_bridge_methods: nativeBridge.methods, native_bridge_default_off: true,
    native_bridge_malformed_requests_denied: true, native_session_revoked_on_logout: true, native_os_send_executed: false,
    expected_version: expectedVersion, packaged_archive_sha256: archiveHash });
  console.log('DESKTOP_SMOKE_OK: packaged protocol, secure context, assets, path guards, isolated encrypted credentials, synthetic sign-in and UI logout');
} finally {
  await application?.close();
  const relative = path.relative(temporaryRoot, profile);
  if (!relative.startsWith('..') && !path.isAbsolute(relative) && path.basename(profile).startsWith('nerkhbaan-desktop-smoke-')) {
    await rm(profile, { recursive: true, force: true });
    receipt.isolated_profile_removed = true;
  }
  if (receiptPath) {
    await mkdir(path.dirname(path.resolve(receiptPath)), { recursive: true });
    await writeFile(receiptPath, JSON.stringify(receipt, null, 2));
  }
}
