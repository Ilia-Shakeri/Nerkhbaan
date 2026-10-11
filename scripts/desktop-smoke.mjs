import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { _electron } from '@playwright/test';

const root = path.resolve(import.meta.dirname, '..');
const temporaryRoot = path.resolve(os.tmpdir());
const profile = await mkdtemp(path.join(temporaryRoot, 'nerkhbaan-desktop-smoke-'));
let application;
try {
  application = await _electron.launch({
    executablePath: path.join(root, 'apps/desktop/release/win-unpacked/Nerkhbaan.exe'),
    args: [`--user-data-dir=${profile}`],
    timeout: 60_000,
  });
  const page = await application.firstWindow();
  await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().forEach(window => window.hide()));
  await application.context().route('https://**', route => route.fulfill({ status: 401, json: { detail: 'Smoke profile has no account' } }));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /ورود به حساب|Sign In/ }).waitFor({ timeout: 40_000 });
  const runtime = await application.evaluate(({ app }) => ({ packaged: app.isPackaged, profile: app.getPath('userData') }));
  assert.equal(runtime.packaged, true);
  assert.equal(path.resolve(runtime.profile), path.resolve(profile));
  assert.match(page.url(), /^nerkhbaan:\/\/app\/index\.html#/);
  assert.equal(await page.evaluate(() => window.isSecureContext), true);
  assert.equal(await page.evaluate(() => Boolean(window.electronAPI?.auth)), true);
  const assetStatus = await page.evaluate(async () => (await fetch('nerkhbaan://app/icons/logo.png')).status);
  assert.equal(assetStatus, 200);
  const blocked = await application.evaluate(async ({ net }) => {
    const responses = await Promise.all(['nerkhbaan://evil/index.html', 'nerkhbaan://app/%2e%2e/package.json'].map(async url => (await net.fetch(url)).status));
    return responses;
  });
  assert.ok(blocked.every(status => status >= 400));
  const credentials = { access_token: 'smoke-access-token-never-valid', refresh_token: 'smoke-refresh-token-never-valid-000' };
  const roundtrip = await page.evaluate(async value => {
    await window.electronAPI.auth.setCredentials(value);
    const stored = await window.electronAPI.auth.getCredentials();
    await window.electronAPI.auth.clearCredentials();
    return { stored, cleared: await window.electronAPI.auth.getCredentials() };
  }, credentials);
  assert.deepEqual(roundtrip.stored, credentials);
  assert.equal(roundtrip.cleared, null);
  console.log('DESKTOP_SMOKE_OK: packaged protocol, secure context, assets, path guards, isolated encrypted credentials');
} finally {
  await application?.close();
  const relative = path.relative(temporaryRoot, profile);
  if (!relative.startsWith('..') && !path.isAbsolute(relative) && path.basename(profile).startsWith('nerkhbaan-desktop-smoke-')) {
    await rm(profile, { recursive: true, force: true });
  }
}
