import { createRequire } from 'node:module';
import { randomBytes, createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

if (!process.argv.includes('--allow-production-signup')) throw new Error('Explicit production signup opt-in required; no network or account created');
const require = createRequire(import.meta.url);
const { chromium, expect } = require('@playwright/test');
const origin = 'https://nerkhbaan.ir';
const id = randomBytes(8).toString('hex');
const username = `delivery_${id}`;
const email = `${username}@example.com`;
const password = `Aa9!${randomBytes(24).toString('base64url')}`;
const receipt = { started_at: new Date().toISOString(), base_url: origin,
  account_reference_sha256: createHash('sha256').update(username).digest('hex'),
  account_kind: 'single owned disposable smoke-test account; no mail sent',
  production_configuration_changed: false, checks: [], page_errors: [] };
const receiptDir = path.resolve(import.meta.dirname, '../../delivery/web-auth-smoke');
mkdirSync(receiptDir, { recursive: true, mode: 0o700 });
const output = path.join(receiptDir, `live-auth-${Date.now()}-${id}.json`);
writeFileSync(output, JSON.stringify({ ...receipt, passed: false, incomplete: true }, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
let browser;
const contexts = [];
let phase = 'launch';
function checked(name, details = {}) { receipt.checks.push({ name, passed: true, at: new Date().toISOString(), ...details }); }
const clean = value => String(value).replaceAll(password, '[redacted]').replaceAll(username, '[test account]').replaceAll(email, '[test address]');
async function context(viewport) {
  const item = await browser.newContext({ viewport, serviceWorkers: 'block', permissions: [] });
  contexts.push(item);
  await item.addInitScript(() => { localStorage.setItem('language', 'fa'); sessionStorage.setItem('splash-shown', 'true'); });
  const page = await item.newPage();
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => receipt.page_errors.push(clean(error.message)));
  return { item, page };
}
async function profile(item) {
  const response = await item.request.get(`${origin}/api/auth/me`, { timeout: 15000 });
  if (response.status() !== 200) throw new Error(`Profile status ${response.status()}`);
  const user = await response.json();
  if (user.username !== username) throw new Error('Profile identity mismatch');
}
async function signout(item, page, label) {
  phase = label + '-signout';
  await page.getByRole('button', { name: 'منوی کاربر', exact: true }).click();
  const [response] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === '/api/auth/signout' && response.request().method() === 'POST'),
    page.getByRole('menuitem', { name: 'خروج از حساب', exact: true }).click(),
  ]);
  if (response.status() !== 204) throw new Error(`Signout status ${response.status()}`);
  await expect(page.getByRole('button', { name: 'ورود به حساب', exact: true })).toBeVisible();
  const me = await item.request.get(`${origin}/api/auth/me`);
  if (me.status() !== 401) throw new Error(`Signed-out profile status ${me.status()}`);
  checked(label + '-logout-invalidates-session');
}
async function signin(item, page, identifier, label) {
  phase = label + '-signin';
  await page.goto(`${origin}/auth`, { waitUntil: 'domcontentloaded' });
  await page.locator('input[name="username"]').fill(identifier);
  await page.locator('#auth-password').fill(password);
  const [response] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === '/api/auth/signin' && response.request().method() === 'POST'),
    page.getByRole('button', { name: 'ورود به حساب', exact: true }).click(),
  ]);
  if (response.status() !== 200) throw new Error(`Signin status ${response.status()}`);
  await expect(page.getByRole('button', { name: 'منوی کاربر', exact: true })).toBeVisible();
  await profile(item); checked(label + '-signin-and-profile');
}
try {
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const { item, page } = await context({ width: 1440, height: 1000 });
  phase = 'public-readiness';
  for (const resource of ['/', '/auth', '/manifest.webmanifest', '/sw.js', '/api/health/ready']) {
    const response = await item.request.get(origin + resource, { timeout: 15000 });
    if (response.status() !== 200) throw new Error(`Public resource ${resource} status ${response.status()}`);
    if (resource.endsWith('ready') && !(await response.json()).ready) throw new Error('API not ready');
    checked('public-resource', { path: resource, status: response.status() });
  }
  phase = 'signup-form';
  await page.goto(`${origin}/auth`, { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'ثبت نام', exact: true }).click();
  await page.locator('input[name="name"]').fill('Delivery smoke test');
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="email"]').fill(email);
  await page.locator('#auth-password').fill(password);
  const agreements = page.getByRole('checkbox');
  if (await agreements.count() !== 2) throw new Error('Unexpected agreement controls');
  await agreements.nth(0).check(); await agreements.nth(1).check();
  phase = 'signup-submit-once';
  const [response] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === '/api/auth/signup' && response.request().method() === 'POST'),
    page.getByRole('button', { name: 'ایجاد حساب کاربری', exact: true }).click(),
  ]);
  receipt.signup_http_status = response.status();
  if (response.status() !== 201) throw new Error(`Signup status ${response.status()}`);
  checked('signup-through-live-form');
  await expect(page.getByRole('button', { name: 'منوی کاربر', exact: true })).toBeVisible();
  await profile(item); checked('signup-authenticated-profile');
  phase = 'cookie-flag-check';
  const authCookies = (await item.cookies()).filter(cookie => ['nerkhbaan_session', 'nerkhbaan_refresh'].includes(cookie.name));
  if (authCookies.length < 2 || authCookies.some(cookie => !cookie.httpOnly || !cookie.secure)) throw new Error('Authentication cookies lack required flags');
  checked('secure-httponly-authentication-cookies', { cookie_count: authCookies.length });
  phase = 'reload-session';
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('button', { name: 'منوی کاربر', exact: true })).toBeVisible();
  await profile(item); checked('reload-preserves-session');
  await signout(item, page, 'desktop-first');
  phase = 'wrong-password';
  await page.locator('input[name="username"]').fill(username);
  await page.locator('#auth-password').fill('WrongTestPassword9!');
  const [rejected] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === '/api/auth/signin' && response.request().method() === 'POST'),
    page.getByRole('button', { name: 'ورود به حساب', exact: true }).click(),
  ]);
  if (rejected.status() !== 401) throw new Error('Wrong password did not return 401');
  await expect(page.getByRole('alert').filter({ hasText: 'نام کاربری یا رمز عبور اشتباه است' })).toBeVisible();
  checked('wrong-password-rejected-with-visible-error');
  await signin(item, page, username.toUpperCase(), 'desktop-username');
  await signout(item, page, 'desktop-username');
  const mobile = await context({ width: 390, height: 844 });
  await signin(mobile.item, mobile.page, email, 'narrow-viewport-email');
  if (!(await mobile.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))) throw new Error('Horizontal overflow in narrow viewport');
  checked('narrow-viewport-no-horizontal-overflow', { actual_mobile_os_test: false });
  await signout(mobile.item, mobile.page, 'narrow-viewport');
  receipt.passed = receipt.page_errors.length === 0;
} catch (error) {
  receipt.passed = false; receipt.failed_phase = phase; receipt.error = clean(error.message); receipt.automatic_signup_retry = false;
} finally {
  // Revoke only sessions belonging to this owned test context if a UI assertion stopped early.
  for (const item of contexts) {
    try {
      const response = await item.request.post(`${origin}/api/auth/signout`, { headers: { Origin: origin }, timeout: 10000 });
      receipt.checks.push({ name: 'owned-context-session-teardown', status: response.status(), passed: response.status() === 204 });
    } catch (error) { receipt.checks.push({ name: 'owned-context-session-teardown', passed: false, error_type: error.name }); }
    try { await item.close(); }
    catch (error) { receipt.checks.push({ name: 'owned-browser-context-close', passed: false, error_type: error.name }); }
  }
  if (browser) {
    try { await browser.close(); }
    catch (error) { receipt.checks.push({ name: 'owned-browser-close', passed: false, error_type: error.name }); }
  }
  receipt.passed = Boolean(receipt.passed) && receipt.checks.every(check => check.passed) && receipt.page_errors.length === 0;
  receipt.finished_at = new Date().toISOString();
  receipt.incomplete = false;
  writeFileSync(output, JSON.stringify(receipt, null, 2) + '\n', { flag: 'w', mode: 0o600 });
  console.log(JSON.stringify({ receipt: output, ...receipt }));
}
process.exitCode = receipt.passed ? 0 : 1;
