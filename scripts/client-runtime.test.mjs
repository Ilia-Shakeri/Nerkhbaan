import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const root = path.resolve(import.meta.dirname, '..');
function moduleAt(file, globals, imports) {
  const source = readFileSync(path.join(root, file), 'utf8').replaceAll('import.meta.env', '__env');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  const context = { exports: {}, require: name => imports[name] ?? (name.endsWith('logout-state') ? { logoutIsPending: () => false, logoutGeneration: () => 0 } : undefined), URL, Event, CustomEvent, setTimeout, clearTimeout, console, ...globals };
  vm.runInNewContext(compiled, context, { filename: file });
  return context.exports;
}

function clientHarness(shared, locks) {
  const interceptors = {};
  const instance = {
    interceptors: { request: { use: callback => { interceptors.request = callback; } }, response: { use: (_success, error) => { interceptors.error = error; } } },
    request: async config => { config.headers = {}; await interceptors.request(config); return { status: 200, config }; },
    post: async (url, payload) => {
      shared.calls.push({ url, payload });
      if (url === 'auth/signout') {
        await shared.signoutGate;
        if (shared.signoutFails) throw new Error('test signout outage');
        return { status: 204 };
      }
      await shared.signinGate;
      return { data: { access_token: 'signed-in-access', refresh_token: 'signed-in-refresh', user: { id: 2 } } };
    },
  };
  const axios = {
    create: config => { shared.baseURLs.push(config.baseURL); return instance; },
    isAxiosError: error => Boolean(error.response),
    get: async (_url, config) => {
      if (config.headers.Authorization !== 'Bearer current-access') throw { response: { status: 401 } };
      return { data: { id: 1 } };
    },
    post: async (_url, payload) => {
      shared.rotations += 1;
      assert.equal(payload.refresh_token, 'original-refresh');
      await new Promise(resolve => setTimeout(resolve, 10));
      return { data: { access_token: 'current-access', refresh_token: 'current-refresh' } };
    },
  };
  const window = { dispatchEvent() {}, electronAPI: { auth: {
    async getCredentials() { shared.reads += 1; const stored = shared.credentials; await shared.readGate; await new Promise(resolve => setTimeout(resolve, 5)); return stored; },
    async setCredentials(value) { shared.credentials = value; }, async clearCredentials() { shared.credentials = null; },
  } } };
  const exported = moduleAt('apps/web/src/app/services/api.ts', { __env: { VITE_API_URL: '/api' }, navigator: { locks }, window, document: { documentElement: { lang: 'en' } } }, { axios, './logout-state': { logoutIsPending: () => Boolean(shared.pending), logoutGeneration: () => shared.generation || 0, beginLogout: () => { shared.pending = true; shared.generation = (shared.generation || 0) + 1; }, finishLogout: success => { if (success) shared.pending = false; } } });
  return { exported, fail: url => interceptors.error({ config: { url }, response: { status: 401 } }) };
}

function sharedSession() { return { credentials: { access_token: 'original-access', refresh_token: 'original-refresh' }, rotations: 0, reads: 0, baseURLs: [], calls: [] }; }

test('parallel renderer failures share one rotation before credential I/O', async () => {
  const shared = sharedSession();
  const client = clientHarness(shared);
  const result = await Promise.all([client.fail('prices'), client.fail('alerts')]);
  assert.equal(shared.rotations, 1);
  assert.equal(result.length, 2);
  assert.ok(result.every(item => item.config.headers.Authorization === 'Bearer current-access'));
  assert.equal(shared.baseURLs[0], 'https://nerkhbaan.ir/api/');
});

test('two renderers share a lock and re-read secure credentials before rotation', async () => {
  const shared = sharedSession();
  let tail = Promise.resolve();
  const locks = { request(_name, task) { const result = tail.then(task); tail = result.catch(() => undefined); return result; } };
  const first = clientHarness(shared, locks);
  const second = clientHarness(shared, locks);
  await Promise.all([first.fail('prices'), second.fail('alerts')]);
  assert.equal(shared.rotations, 1);
  assert.equal(shared.reads, 2);
});

test('push teardown returns when no service worker is registered', async () => {
  let requests = 0;
  const exported = moduleAt('apps/web/src/pwa/push.ts', {
    __env: {}, window: { Notification: {}, PushManager: {} },
    navigator: { serviceWorker: { getRegistration: async () => undefined, ready: new Promise(() => {}) } },
  }, { '@/app/services/api': { apiInstance: { post: () => { requests += 1; } } } });
  await exported.disablePushNotifications();
  assert.equal(requests, 0);
});

test('desktop never waits for a web push worker', async () => {
  const exported = moduleAt('apps/web/src/pwa/push.ts', {
    __env: {}, window: { electronAPI: {}, Notification: {}, PushManager: {} },
    navigator: { serviceWorker: { getRegistration: () => { throw new Error('Must not inspect worker'); } } },
  }, { '@/app/services/api': { apiInstance: {} } });
  assert.equal(exported.pushIsSupported(), false);
  await exported.disablePushNotifications();
});

test('an empty or partial snapshot clears removed quote legs before merging', () => {
  const { clearSnapshotPrices } = moduleAt('apps/web/src/app/services/price-stream.ts', {}, {});
  const current = { refreshed_at: '2026-10-11T00:00:00Z', source: {}, assets: [{ asset: 'gold', price_usd: 4000, price_toman: 10000000, usd_status: 'fresh', toman_status: 'fresh', candidate_price_usd: 4500, change_percent_usd: 12 }] };
  const cleared = clearSnapshotPrices(current);
  assert.equal(cleared.assets[0].price_usd, null);
  assert.equal(cleared.assets[0].price_toman, null);
  assert.equal(cleared.assets[0].candidate_price_usd, null);
  assert.equal(cleared.assets[0].usd_status, 'unavailable');
  assert.equal(cleared.assets[0].change_percent_usd, null);
  assert.equal(current.assets[0].price_usd, 4000);
  assert.equal(clearSnapshotPrices(undefined), undefined);
});

test('stream quotes preserve distinct instrument units and daily changes without HTTP metadata', () => {
  const { canonicalLegDetails } = moduleAt('apps/web/src/app/services/price-stream.ts', {}, {});
  const usd = canonicalLegDetails({ instrument_id: 'XAU_USD_OZ', currency: 'USD', unit: 'troy_ounce', purity: 0.9999, change_24h: 1.5, market: 'global', display_decimals: 2 }, false);
  const toman = canonicalLegDetails({ instrument_id: 'GOLD_18K_TOMAN_GRAM', currency: 'TOMAN', unit: 'gram', purity: 0.75, change_24h: -2, market: 'iran', display_decimals: 0 }, true);
  assert.equal(usd.unit_usd.weight_unit, 'troy_ounce');
  assert.equal(usd.unit_usd.purity, 0.9999);
  assert.equal(usd.change_percent_usd, 1.5);
  assert.equal(toman.unit_toman.weight_unit, 'gram');
  assert.equal(toman.unit_toman.purity, 0.75);
  assert.equal(toman.change_percent_toman, -2);
  assert.equal(usd.unit_toman, undefined);
  assert.equal(canonicalLegDetails({ instrument_id: 'XAU_USD_OZ', change_24h: NaN }, false).change_percent_usd, null);
});

test('snapshot removal clears historical prices and source credits too', () => {
  const { clearSnapshotPrices } = moduleAt('apps/web/src/app/services/price-stream.ts', {}, {});
  const current = { assets: [{ asset: 'gold', history: [{ value_usd: 2080 }],
    usd_attributions: [{ label: 'Old source', url: 'https://old.fixture.invalid/' }],
    toman_attributions: [{ label: 'Old local source', url: 'https://local.fixture.invalid/' }] }] };
  const cleared = clearSnapshotPrices(current);
  assert.equal(cleared.assets[0].history.length, 0);
  assert.equal(cleared.assets[0].usd_attributions.length, 0);
  assert.equal(cleared.assets[0].toman_attributions.length, 0);
  assert.equal(current.assets[0].history.length, 1);
});

test('source credits accept safe HTTPS links only and keep distinct contributors', () => {
  const { safeAttributions } = moduleAt('apps/web/src/app/services/price-stream.ts', {}, {});
  const valid = { label: 'Gold API', url: 'https://gold-api.com/' };
  const credits = safeAttributions([valid, valid,
    { label: 'Script', url: 'javascript:alert(1)' },
    { label: 'Plain', url: 'http://source.fixture.invalid/' },
    { label: 'Secret', url: 'https://name:secret@source.fixture.invalid/' },
    { label: '', url: 'https://source.fixture.invalid/' },
    { label: 'Local market', url: 'https://local.fixture.invalid/' }]);
  assert.deepEqual(JSON.parse(JSON.stringify(credits)), [valid, { label: 'Local market', url: 'https://local.fixture.invalid/' }]);
});

test('stream source credits remain bound to the correct currency leg', () => {
  const { canonicalLegDetails } = moduleAt('apps/web/src/app/services/price-stream.ts', {}, {});
  const credit = { label: 'Gold API', url: 'https://gold-api.com/' };
  const result = canonicalLegDetails({ instrument_id: 'XAU_USD_OZ', attribution: [credit] }, false);
  assert.deepEqual(JSON.parse(JSON.stringify(result.usd_attributions)), [credit]);
  assert.equal(result.toman_attributions, undefined);
});

test('source-rights revision retires old socket frames and old HTTP requests', () => {
  const target = new EventTarget(); const events = [];
  target.addEventListener('pricing-rights-changed', event => events.push(event.detail.revision));
  const stream = moduleAt('apps/web/src/app/services/price-stream.ts', { window: target }, {});
  assert.equal(stream.acceptRightsRevision('first', 'http', 0), true);
  const oldEpoch = stream.currentRightsEpoch();
  assert.equal(stream.acceptRightsRevision('second', 'socket'), false);
  assert.equal(stream.currentRightsRevision(), 'first');
  assert.equal(stream.rightsArePending(), true);
  assert.equal(stream.acceptRightsRevision('second', 'http', stream.currentRightsEpoch()), true);
  assert.equal(stream.acceptRightsRevision('first', 'socket'), false);
  assert.equal(stream.acceptRightsRevision('first', 'http', oldEpoch), false);
  assert.equal(stream.currentRightsRevision(), 'second');
  assert.equal(stream.acceptRightsRevision(undefined, 'socket'), false);
  assert.deepEqual(events, ['first', 'first', 'second']);
  // A fresh authoritative read can confirm an intentional permission rollback.
  assert.equal(stream.acceptRightsRevision('first', 'http', stream.currentRightsEpoch()), true);
});

function pricingHarness() {
  const window = new EventTarget();
  const stream = moduleAt('apps/web/src/app/services/price-stream.ts', { window }, {});
  const calls = [];
  const instance = { interceptors: { request: { use() {} }, response: { use() {} } },
    get: (url, config) => new Promise(resolve => calls.push({ url, config, resolve })) };
  const exported = moduleAt('apps/web/src/app/services/api.ts', {
    __env: {}, navigator: {}, window, document: { documentElement: { lang: 'en' } },
  }, { axios: { create: () => instance }, './price-stream': stream });
  return { stream, calls, exported };
}

test('late pricing response cannot restore a retired source-rights revision', async () => {
  const { stream, calls, exported } = pricingHarness();
  const pending = exported.getPrices();
  stream.acceptRightsRevision('new-rights', 'socket');
  stream.acceptRightsRevision('new-rights', 'http', stream.currentRightsEpoch());
  calls[0].resolve({ data: { rights_revision: 'old-rights', assets: [{ price_usd: 2080 }] } });
  await assert.rejects(pending, /permission|rights|source/i);
  assert.equal(stream.currentRightsRevision(), 'new-rights');
});

test('an unseen older socket revision stays hidden until a fresh HTTP read confirms current rights', () => {
  const stream = moduleAt('apps/web/src/app/services/price-stream.ts', { window: new EventTarget() }, {});
  stream.acceptRightsRevision('current', 'http', 0);
  const oldEpoch = stream.currentRightsEpoch();
  assert.equal(stream.acceptRightsRevision('unseen-older-frame', 'socket'), false);
  assert.equal(stream.currentRightsRevision(), 'current');
  assert.equal(stream.rightsArePending(), true);
  assert.equal(stream.acceptRightsRevision('current', 'socket'), false);
  assert.equal(stream.acceptRightsRevision('current', 'http', oldEpoch), false);
  assert.equal(stream.acceptRightsRevision('current', 'http', stream.currentRightsEpoch()), true);
  assert.equal(stream.rightsArePending(), false);
});

test('history request carries current rights revision and rejects an older in-flight result', async () => {
  const { stream, calls, exported } = pricingHarness();
  stream.acceptRightsRevision('first', 'http', 0);
  const pending = exported.getPriceHistory('gold', '30d');
  assert.equal(calls[0].config.params.rights_revision, 'first');
  stream.acceptRightsRevision('second', 'socket');
  calls[0].resolve({ data: { asset: 'gold', points: [{ value_usd: 2080 }] } });
  await assert.rejects(pending, /permission|rights|source/i);
});

test('sign-in waits for push teardown and remote signout before storing new credentials', async () => {
  const shared = sharedSession();
  const client = clientHarness(shared);
  let releasePush, releaseSignout;
  const push = new Promise(resolve => { releasePush = resolve; });
  shared.signoutGate = new Promise(resolve => { releaseSignout = resolve; });
  const signout = client.exported.api.auth.signout(() => push);
  assert.equal(signout, client.exported.api.auth.signout());
  const signin = client.exported.api.auth.signin({ username_or_email: 'test-user', password: 'test-only-password' });
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(shared.calls.length, 0);
  releasePush();
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual(shared.calls.map(call => call.url), ['auth/signout']);
  assert.equal(shared.calls[0].payload.refresh_token, 'original-refresh');
  releaseSignout();
  await Promise.all([signout, signin]);
  assert.deepEqual(shared.calls.map(call => call.url), ['auth/signout', 'auth/signin']);
  assert.equal(shared.credentials.access_token, 'signed-in-access');
});

test('sign-up can proceed after failed signout and push teardown cannot prevent revocation', async () => {
  const shared = sharedSession();
  shared.signoutFails = true;
  const client = clientHarness(shared);
  const signout = client.exported.api.auth.signout(async () => { throw new Error('test push outage'); });
  const signup = client.exported.api.auth.signup({ username: 'new-user' });
  await assert.rejects(signout, /test signout outage/);
  await signup;
  assert.deepEqual(shared.calls.map(call => call.url), ['auth/signout', 'auth/signup']);
  assert.equal(shared.credentials.refresh_token, 'signed-in-refresh');
});

test('signout waits for an existing refresh and revokes its newest refresh token', async () => {
  const shared = sharedSession();
  const client = clientHarness(shared);
  const rotation = client.fail('prices');
  const signout = client.exported.api.auth.signout();
  await Promise.all([rotation, signout]);
  assert.equal(shared.rotations, 1);
  assert.equal(shared.calls[0].url, 'auth/signout');
  assert.equal(shared.calls[0].payload.refresh_token, 'current-refresh');
  assert.equal(shared.credentials, null);
});

test('a pending secure credential read cannot restore cached credentials after logout', async () => {
  const shared = sharedSession();
  let releaseRead;
  shared.readGate = new Promise(resolve => { releaseRead = resolve; });
  const client = clientHarness(shared);
  const pendingRequest = client.exported.apiInstance.request({ url: 'prices' });
  const signout = client.exported.api.auth.signout();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(shared.reads, 1);
  assert.equal(shared.calls.length, 0);
  releaseRead();
  await Promise.all([pendingRequest, signout]);
  const after = await client.exported.apiInstance.request({ url: 'prices' });
  assert.equal(after.config.headers.Authorization, undefined);
  assert.equal(shared.credentials, null);
});

test('an older secure credential read cannot replace a newer successful sign-in', async () => {
  const shared = sharedSession();
  let releaseRead;
  shared.readGate = new Promise(resolve => { releaseRead = resolve; });
  const client = clientHarness(shared);
  const oldRequest = client.exported.apiInstance.request({ url: 'prices' });
  await client.exported.api.auth.signin({ username_or_email: 'new-user', password: 'test-only-password' });
  releaseRead();
  await oldRequest;
  const latest = await client.exported.apiInstance.request({ url: 'prices' });
  assert.equal(latest.config.headers.Authorization, 'Bearer signed-in-access');
});

test('pending logout blocks sign-in, registration and automatic refresh without replacing credentials', async () => {
  const shared = sharedSession();
  shared.pending = true;
  const client = clientHarness(shared);
  await assert.rejects(client.exported.api.auth.signin({}), /sign-out is incomplete/);
  await assert.rejects(client.exported.api.auth.signup({}), /sign-out is incomplete/);
  await assert.rejects(client.fail('alerts'));
  assert.equal(shared.calls.length, 0);
  assert.equal(shared.rotations, 0);
  assert.equal(shared.credentials.refresh_token, 'original-refresh');
});

test('logout waits for sign-in already sent and revokes the credential it creates', async () => {
  const shared = sharedSession();
  let finishSignin;
  shared.signinGate = new Promise(resolve => { finishSignin = resolve; });
  const client = clientHarness(shared);
  const signin = client.exported.api.auth.signin({});
  const rejected = assert.rejects(signin, /sign-out is incomplete/);
  await new Promise(resolve => setTimeout(resolve, 10));
  shared.pending = true;
  const logout = client.exported.api.auth.signout();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual(shared.calls.map(call => call.url), ['auth/signin']);
  finishSignin();
  await Promise.all([logout, rejected]);
  assert.equal(shared.calls[1].payload.refresh_token, 'signed-in-refresh');
  assert.equal(shared.credentials, null);
});

test('a late sign-in in another renderer restores the logout lock when shared locks are unavailable', async () => {
  const shared = sharedSession();
  let finishSignin;
  shared.signinGate = new Promise(resolve => { finishSignin = resolve; });
  const late = clientHarness(shared);
  const other = clientHarness(shared);
  const signin = late.exported.api.auth.signin({});
  const rejected = assert.rejects(signin, /sign-out is incomplete/);
  await new Promise(resolve => setTimeout(resolve, 10));
  shared.pending = true; shared.generation = 1;
  await other.exported.api.auth.signout();
  shared.pending = false; shared.generation = 2;
  finishSignin();
  await rejected;
  assert.equal(shared.pending, true);
  assert.equal(shared.credentials.refresh_token, 'signed-in-refresh');
  await late.exported.api.auth.signout();
  assert.equal(shared.calls.at(-1).payload.refresh_token, 'signed-in-refresh');
  assert.equal(shared.credentials, null);
});

test('failed desktop logout retains secure revocation credentials across reload until retry succeeds', async () => {
  const shared = sharedSession();
  shared.pending = true;
  shared.signoutFails = true;
  const first = clientHarness(shared);
  const state = { beginLogout: () => { shared.pending = true; }, finishLogout: success => { if (success) shared.pending = false; } };
  const flow = client => moduleAt('apps/web/src/app/services/logout.ts', {}, { '@/pwa/push': { disablePushNotifications: async () => {} }, './api': { api: client.exported.api }, './logout-state': state });
  await assert.rejects(flow(first).requestLogout(), /test signout outage/);
  assert.equal(shared.pending, true);
  assert.equal(shared.credentials.refresh_token, 'original-refresh');
  await assert.rejects(first.exported.apiInstance.request({ url: 'prices' }), /sign-out is incomplete/);
  const reloaded = clientHarness(shared);
  shared.signoutFails = false;
  await flow(reloaded).requestLogout();
  assert.deepEqual(shared.calls.filter(call => call.url === 'auth/signout').map(call => call.payload.refresh_token), ['original-refresh', 'original-refresh']);
  assert.equal(shared.credentials, null);
  assert.equal(shared.pending, false);
});

test('late startup subscription read cannot bind an endpoint after logout begins', async () => {
  let releaseRead, pending = false, generation = 0, writes = 0;
  const read = new Promise(resolve => { releaseRead = resolve; });
  const worker = { pushManager: { getSubscription: () => read } };
  const push = moduleAt('apps/web/src/pwa/push.ts', {
    __env: { VITE_VAPID_PUBLIC_KEY: 'test-key' }, window: { Notification: {}, PushManager: {} },
    navigator: { serviceWorker: { getRegistration: async () => worker, ready: Promise.resolve(worker) } },
  }, { '@/app/services/api': { apiInstance: { post: async () => { writes++; } } }, '@/app/services/logout-state': { logoutIsPending: () => pending, logoutGeneration: () => generation } });
  const sync = push.syncPushSubscription();
  await new Promise(resolve => setTimeout(resolve, 10));
  pending = true; generation++;
  releaseRead({ toJSON: () => ({ endpoint: 'old-endpoint' }) });
  await sync;
  assert.equal(writes, 0);
});

test('push cleanup waits for an already sent subscription write before detaching it', async () => {
  let releaseWrite, pending = false;
  const write = new Promise(resolve => { releaseWrite = resolve; });
  const calls = [];
  const subscription = { endpoint: 'test-endpoint', toJSON: () => ({}), unsubscribe: async () => { calls.push('browser-detach'); } };
  const worker = { pushManager: { getSubscription: async () => subscription } };
  const push = moduleAt('apps/web/src/pwa/push.ts', {
    __env: { VITE_VAPID_PUBLIC_KEY: 'test-key' }, window: { Notification: {}, PushManager: {} },
    navigator: { serviceWorker: { getRegistration: async () => worker, ready: Promise.resolve(worker) } },
  }, { '@/app/services/api': { apiInstance: { post: async url => { calls.push(url); if (url === 'push/subscribe') await write; } } }, '@/app/services/logout-state': { logoutIsPending: () => pending, logoutGeneration: () => 0 } });
  const sync = push.syncPushSubscription();
  await new Promise(resolve => setTimeout(resolve, 10));
  pending = true;
  const cleanup = push.disablePushNotifications();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual(calls, ['push/subscribe']);
  releaseWrite();
  await Promise.all([sync, cleanup]);
  assert.deepEqual(calls, ['push/subscribe', 'browser-detach', 'push/unsubscribe']);
});

test('bounded push cleanup still sends server signout and keeps the logout lock for retry', async () => {
  const finished = [], timeouts = [];
  let signouts = 0;
  const logout = moduleAt('apps/web/src/app/services/logout.ts', {
    setTimeout: (callback, delay) => { timeouts.push(delay); return setTimeout(callback, 5); },
  }, { '@/pwa/push': { disablePushNotifications: () => new Promise(() => {}) }, './api': { api: { auth: { signout: async before => { await before(); signouts++; } } } }, './logout-state': { beginLogout() {}, finishLogout: success => finished.push(success) } });
  const first = logout.requestLogout();
  assert.equal(first, logout.requestLogout());
  await assert.rejects(first, /Notification cleanup/);
  assert.deepEqual(timeouts, [4000]);
  assert.equal(signouts, 1);
  assert.deepEqual(finished, [false]);
});
