import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

function load(file, globals) {
  const source = readFileSync(new URL('../' + file, import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const context = { exports: {}, URL, require: () => ({ precacheAndRoute() {}, cleanupOutdatedCaches() {}, registerRoute() {}, createHandlerBoundToURL() {}, NavigationRoute: class {} }), ...globals };
  vm.runInNewContext(code, context);
  return context.exports;
}

function worker(clients = []) {
  const handlers = {}, shown = [], opened = [];
  load('apps/web/src/pwa/sw.ts', { self: {
    location: { origin: 'https://app.example' },
    addEventListener: (type, callback) => { handlers[type] = callback; },
    registration: { showNotification: async (title, options) => { shown.push({ title, options }); } },
    clients: { matchAll: async () => clients, openWindow: async url => { opened.push(url); } },
  } });
  return { shown, opened,
    push: async (data, broken = false) => {
      let pending;
      handlers.push({ data: { json: () => { if (broken) throw new Error('invalid JSON'); return data; }, text: () => String(data) }, waitUntil: value => { pending = value; } });
      await pending;
    },
    click: async url => {
      let pending, closed = false;
      handlers.notificationclick({ notification: { data: { url }, close: () => { closed = true; } }, waitUntil: value => { pending = value; } });
      await pending; assert.equal(closed, true);
    },
  };
}

test('push shows a safe default for null, arrays and wrong field types', async () => {
  for (const data of [null, [], 5, 'text', { title: {}, body: [], silent: 'false', asset: 3 }]) {
    const h = worker(); await h.push(data);
    assert.equal(h.shown.length, 1);
    assert.equal(h.shown[0].title, 'Nerkhbaan');
    assert.equal(h.shown[0].options.body, '');
    assert.equal(h.shown[0].options.silent, false);
  }
});

test('push keeps title, body, quiet flag and asset grouping; text fallback works', async () => {
  const h = worker();
  await h.push({ title: 'Price alert', body: 'Target met', asset: 'BTC_USD', silent: true, url: '/alerts' });
  assert.equal(h.shown[0].title, 'Price alert');
  assert.equal(h.shown[0].options.body, 'Target met');
  assert.equal(h.shown[0].options.silent, true);
  assert.equal(h.shown[0].options.tag, 'nerkhbaan-BTC_USD');
  assert.equal(h.shown[0].options.data.url, 'https://app.example/alerts');
  await h.push('plain text', true);
  assert.equal(h.shown[1].options.body, 'plain text');
});

test('click rejects foreign, executable, credentialed, malformed and private paths', async () => {
  for (const url of ['https://foreign.example/', '//foreign.example/', 'javascript:alert(1)', 'https://user:pass@app.example/alerts', '/admin/users', '/%61dmin', '/api/private', '/%ZZ', {}]) {
    const h = worker(); await h.click(url);
    assert.deepEqual(h.opened, ['https://app.example/']);
  }
});

test('click preserves admin tab and focuses an existing public app after navigation', async () => {
  const calls = [];
  const h = worker([
    { url: 'https://app.example/admin/', navigate() { throw new Error('Admin must stay'); } },
    { url: 'https://app.example/', navigate: async url => { calls.push(url); return { focus: async () => calls.push('focus') }; } },
  ]);
  await h.click('/alerts?from=push');
  assert.deepEqual(calls, ['https://app.example/alerts?from=push', 'focus']);
  assert.equal(h.opened.length, 0);
});

test('click opens a new app window if existing navigation fails or returns null', async () => {
  for (const navigate of [async () => null, async () => { throw new Error('closed tab'); }]) {
    const h = worker([{ url: 'https://app.example/', navigate }]);
    await h.click('/alerts'); assert.deepEqual(h.opened, ['https://app.example/alerts']);
  }
});

function readiness(overrides = {}) {
  return load('apps/web/src/pwa/push-readiness.ts', {
    window: { isSecureContext: true, matchMedia: () => ({ matches: false }), ...overrides.window },
    navigator: { userAgent: 'Desktop browser', platform: 'Win32', maxTouchPoints: 0, ...overrides.navigator },
    Notification: { permission: overrides.permission ?? 'default' },
  });
}

test('readiness distinguishes insecure, unsupported, denied, missing setup and ready', () => {
  assert.equal(readiness({ window: { isSecureContext: false } }).pushReadiness(true, true), 'insecure');
  assert.equal(readiness().pushReadiness(true, false), 'unsupported');
  assert.equal(readiness({ permission: 'denied' }).pushReadiness(true, true), 'denied');
  assert.equal(readiness().pushReadiness(false, true), 'unconfigured');
  assert.equal(readiness().pushReadiness(true, true), 'ready');
});

test('iPhone and desktop-mode iPad show install help; installed app still needs capabilities', () => {
  for (const navigator of [{ userAgent: 'iPhone' }, { platform: 'MacIntel', maxTouchPoints: 5 }]) {
    assert.equal(readiness({ navigator }).pushReadiness(true, false), 'install');
    assert.equal(readiness({ navigator: { ...navigator, standalone: true } }).pushReadiness(true, false), 'unsupported');
    assert.equal(readiness({ navigator, window: { matchMedia: () => ({ matches: true }) } }).pushReadiness(true, true), 'ready');
  }
});

test('registration message never claims actual notification delivery', () => {
  const h = readiness();
  assert.match(h.pushReadinessText('ready', true, 'en'), /not a delivery receipt/);
  assert.match(h.pushReadinessText('denied', false, 'fa'), /تنظیمات سایت/);
  assert.match(h.pushReadinessText('install', false, 'fa'), /صفحه اصلی/);
});
