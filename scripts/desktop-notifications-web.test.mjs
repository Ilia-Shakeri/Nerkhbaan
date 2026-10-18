import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { EventEmitter } from 'node:events';
import { createRequire } from 'node:module';
import ts from 'typescript';

const root = path.resolve(import.meta.dirname, '..');
const require = createRequire(import.meta.url);
const flush = async () => { for (let i = 0; i < 35; i++) await Promise.resolve(); };
const defer = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
function load(file, imports = {}, globals = {}) {
  const source = readFileSync(path.join(root, file), 'utf8').replaceAll('import.meta.env', '__env');
  const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
  const context = { exports: {}, require: name => imports[name], Date, BigInt, AbortController, Event, setTimeout, clearTimeout, setInterval, clearInterval, __env: {}, ...globals };
  vm.runInNewContext(code, context, { filename: file }); return context.exports;
}
const exports = load('apps/web/src/app/services/desktop-notifications.ts', {
  './api': {}, './price-stream': {}, './desktop-notification-session': { subscribeDesktopNoticeSession() {} }, './prices-connection': {},
}, { window: {} });
function harness() {
  let now = Date.parse('2026-10-18T12:00:00Z'), nextTimer = 0;
  const timers = new Map(), calls = { show: [], lease: [], revoke: [], enable: [], list: [], opens: 0, disconnected: 0 };
  const session = { authenticated: true, generation: 1 }, rights = { epoch: 1, revision: 'r1', pending: false };
  let items = [], prefs = { push_app: true, silent_mode: true }, user = { must_change_password: false };
  let mainGeneration = 0, connectStatus, click;
  const scope = () => ({ nonce: 'a'.repeat(64), sessionGeneration: mainGeneration, rightsEpoch: rights.epoch });
  const bridge = {
    status: async () => ({ supported: true, optedIn: false, sessionGeneration: mainGeneration, rightsEpoch: 0, leaseActive: false, lastEvent: 'idle' }),
    enableSession: async value => { calls.enable.push(value); return scope(); },
    refreshLease: async value => { calls.lease.push(value); return true; },
    showPending: async value => { calls.show.push(value); return true; },
    disableSession: async value => { calls.revoke.push(value); if (value.sessionGeneration === mainGeneration) mainGeneration++; return true; },
    onOpenInbox: callback => { click = callback; return () => { click = undefined; }; },
  };
  const deps = {
    bridge: () => bridge, session: () => session, rights: () => rights,
    me: async () => user, preferences: async () => prefs, prices: async () => ({}),
    list: async signal => { calls.list.push(signal); return items; },
    connect: callback => { connectStatus = callback; callback('live'); return () => { calls.disconnected++; }; },
    openInbox: () => { calls.opens++; }, now: () => now,
    setTimeout: (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, at: now + delay }); return id; },
    clearTimeout: id => { timers.delete(id); },
  };
  const controller = exports.createDesktopNotifications(deps);
  const notice = (id, age = 0, fields = {}) => ({ id, resource_type: 'alert_trigger', resource_id: '9223372036854775807', created_at: new Date(now - age).toISOString(), read_at: null, title: 'private price 999 token', message: 'private account <xml> https://private.invalid', ...fields });
  const advance = async ms => {
    const end = now + ms;
    for (let guard = 0; guard < 100; guard++) {
      const due = [...timers].filter(([, value]) => value.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      now = due[1].at; timers.delete(due[0]); due[1].callback(); await flush();
    }
    now = end; await flush();
  };
  return { controller, calls, deps, bridge, session, rights, scope, notice, advance, timers,
    items: value => { items = value; }, prefs: value => { prefs = value; }, user: value => { user = value; },
    status: value => connectStatus?.(value), click: value => click?.(value), now: () => now };
}

test('native start stays off; explicit grant skips baseline then sends only scope and IDs', async () => {
  const h = harness(); const stop = h.controller.start(); await flush();
  assert.equal(h.controller.snapshot().optedIn, false); assert.equal(h.calls.enable.length, 0); assert.equal(h.calls.list.length, 0);
  h.items([h.notice(1)]); assert.equal(await h.controller.enable('fa'), true); assert.equal(h.calls.show.length, 0);
  await h.advance(1_000); h.items([h.notice(2), h.notice(1)]); await h.advance(14_000);
  assert.equal(h.calls.show.length, 1); assert.deepEqual([...h.calls.show[0].noticeIds], ['2']);
  assert.deepEqual(Object.keys(h.calls.show[0]).sort(), ['nonce', 'noticeIds', 'rightsEpoch', 'sessionGeneration', 'version']);
  assert.doesNotMatch(JSON.stringify(h.calls.show), /private|price|token|account|https|xml/);
  assert.equal(h.calls.lease[0].silent, true); stop();
});
test('positive trigger proof rejects unknown kinds, read state, invalid date and unsafe identifiers', () => {
  const h = harness(), now = h.now(), baseline = now - 1_000;
  assert.equal(exports.eligibleDesktopNotice(h.notice(2), baseline, now), '2');
  for (const fields of [{ resource_type: 'security' }, { resource_type: 'system' }, { resource_type: null }, { resource_id: '9223372036854775808' }, { resource_id: '0' }, { resource_id: 2 }, { read_at: undefined }, { read_at: '2026-10-18T11:00:00Z' }, { created_at: 'bad' }, { created_at: '2026-10-18' }, { id: Number.MAX_SAFE_INTEGER + 1 }, { id: '01' }, { id: '-2' }]) assert.equal(exports.eligibleDesktopNotice(h.notice(2, 0, fields), baseline, now), null);
  assert.equal(exports.eligibleDesktopNotice(h.notice(2, 61_000), now - 100_000, now), null);
  assert.equal(exports.eligibleDesktopNotice(h.notice(2, -31_000), baseline, now), null);
});
test('fresh authenticated profile, allowed preferences and verified rights needed before consent', async () => {
  for (const mode of ['signed-out', 'password', 'global-off', 'unknown-silent', 'unverified-rights']) {
    const h = harness();
    if (mode === 'signed-out') h.session.authenticated = false;
    if (mode === 'password') h.user({ must_change_password: true });
    if (mode === 'global-off') h.prefs({ push_app: false, silent_mode: true });
    if (mode === 'unknown-silent') h.prefs({ push_app: true });
    if (mode === 'unverified-rights') h.rights.revision = '';
    assert.equal(await h.controller.enable('en'), false, mode); assert.equal(h.calls.enable.length, 0, mode);
  }
});
test('canceled consent and late grant after revoke never enable a session', async () => {
  const canceled = harness(); canceled.bridge.enableSession = async () => false;
  assert.equal(await canceled.controller.enable('en'), false); assert.equal(canceled.calls.lease.length, 0);
  const h = harness(), gate = defer(); h.bridge.enableSession = () => gate.promise;
  const enabled = h.controller.enable('en'); await flush(); const old = h.scope(); h.controller.disable(); gate.resolve(old);
  assert.equal(await enabled, false); assert.equal(h.controller.snapshot().optedIn, false); assert.equal(h.calls.show.length, 0); assert.ok(h.calls.revoke.length >= 1);
});
test('logout during baseline aborts list and blocks late lease or show', async () => {
  const h = harness(), gate = defer(); h.deps.list = signal => { h.calls.list.push(signal); return gate.promise; };
  const enabled = h.controller.enable('en'); await flush();
  h.session.authenticated = false; h.session.generation++; h.controller.disable();
  assert.equal(h.calls.list[0].aborted, true); gate.resolve([h.notice(2)]); await enabled;
  assert.equal(h.calls.lease.length, 0); assert.equal(h.calls.show.length, 0);
});
test('rights pending during an inbox request revokes immediately and old response stays dead', async () => {
  const h = harness(); await h.controller.enable('en'); const gate = defer();
  h.deps.list = signal => { h.calls.list.push(signal); return gate.promise; };
  const polling = h.controller.poll(); await flush(); h.rights.pending = true; h.rights.epoch++; h.controller.rightsChanged();
  assert.equal(h.calls.list.at(-1).aborted, true); assert.equal(h.controller.snapshot().optedIn, false);
  gate.resolve([h.notice(2)]); await polling; assert.equal(h.calls.show.length, 0);
  h.rights.pending = false; h.controller.rightsChanged(); await h.advance(60_000); assert.equal(h.calls.show.length, 0);
});
test('rights change while consent open cancels without an automatic second dialog', async () => {
  const h = harness(), gate = defer(); h.bridge.enableSession = value => { h.calls.enable.push(value); return gate.promise; };
  const enabling = h.controller.enable('en'); await flush(); const old = h.scope(); h.rights.epoch++; h.rights.revision = 'r2'; h.controller.rightsChanged();
  gate.resolve(old); await enabling; assert.equal(h.controller.snapshot().optedIn, false); assert.equal(h.calls.enable.length, 1);
});
test('baseline date excludes old backlog even when its ID was not in first page', async () => {
  const h = harness(); h.items([h.notice(1, 10_000)]); await h.controller.enable('en');
  await h.advance(1_000); h.items([h.notice(2, 10_000), h.notice(3)]); await h.advance(14_000);
  assert.deepEqual([...h.calls.show[0].noticeIds], ['3']);
});
test('duplicate polls and explicit reenable cannot replay old unread batch', async () => {
  const h = harness(); await h.controller.enable('en'); await h.advance(1_000); h.items([h.notice(2)]); await h.advance(14_000); await h.advance(15_000);
  assert.equal(h.calls.show.length, 1); h.controller.disable(); assert.equal(await h.controller.enable('en'), true); await h.advance(15_000);
  assert.equal(h.calls.show.length, 1);
});
test('one inbox request stays in flight; timer cadence never polls faster than fifteen seconds', async () => {
  const h = harness(); await h.controller.enable('en'); assert.equal(h.calls.list.length, 1);
  await h.advance(14_999); assert.equal(h.calls.list.length, 1);
  const gate = defer(); h.deps.list = signal => { h.calls.list.push(signal); return gate.promise; };
  await h.advance(1); await h.controller.poll(); await h.controller.poll(); assert.equal(h.calls.list.length, 2);
  gate.resolve([]); await flush(); h.controller.disable();
});
test('failed or hung freshness reads close grant and need a fresh user click', async () => {
  const h = harness(); await h.controller.enable('en'); h.deps.preferences = () => new Promise(() => {});
  const polling = h.controller.poll(); await h.advance(18_000); await polling;
  assert.equal(h.controller.snapshot().optedIn, false); assert.equal(h.calls.revoke.length, 1); assert.equal(h.calls.list.at(-1).aborted, true);
  await h.advance(120_000); assert.equal(h.calls.enable.length, 1);
});
test('global off and native lease rejection stop before requesting an OS notice', async () => {
  for (const mode of ['global-off', 'lease-failed']) {
    const h = harness(); await h.controller.enable('en'); await h.advance(1_000); h.items([h.notice(2)]);
    if (mode === 'global-off') h.prefs({ push_app: false, silent_mode: false }); else h.bridge.refreshLease = async () => false;
    await h.advance(14_000); assert.equal(h.calls.show.length, 0); assert.equal(h.controller.snapshot().optedIn, false);
  }
});
test('fixed inbox click requires current scope, rights, authentication and active local lease', async () => {
  const h = harness(); const stop = h.controller.start(); await h.controller.enable('en'); const scope = h.scope();
  h.click(scope); assert.equal(h.calls.opens, 1); h.click({ ...scope, nonce: 'b'.repeat(64) }); assert.equal(h.calls.opens, 1);
  h.rights.epoch++; h.click(scope); assert.equal(h.calls.opens, 1); h.rights.epoch--;
  h.session.authenticated = false; h.click(scope); assert.equal(h.calls.opens, 1); h.session.authenticated = true;
  h.controller.disable(); h.click(scope); assert.equal(h.calls.opens, 1); stop();
});
test('disconnect closes grant; large feeds are bounded; batches carry at most sixteen IDs', async () => {
  const h = harness(); await h.controller.enable('en'); await h.advance(1_000); h.items(Array.from({ length: 40 }, (_, index) => h.notice(index + 2))); await h.advance(14_000);
  assert.equal(h.calls.show[0].noticeIds.length, 16); h.status('fallback'); assert.equal(h.controller.snapshot().optedIn, false);
  const large = harness(); large.items(Array.from({ length: 1_001 }, (_, index) => large.notice(index + 1))); assert.equal(await large.controller.enable('en'), false);
});
test('session module revokes synchronously and login never preserves an earlier grant', () => {
  const session = load('apps/web/src/app/services/desktop-notification-session.ts'); const calls = [];
  session.subscribeDesktopNoticeSession(() => calls.push(session.desktopNoticeSession()));
  session.startDesktopNoticeSession(); assert.equal(session.desktopNoticeSession().authenticated, true); assert.equal(calls[0].authenticated, false);
  session.revokeDesktopNoticeSession(); assert.equal(calls.at(-1).authenticated, false); assert.equal(calls.at(-1).generation, 2);
});

function connectionHarness() {
  const timers = new Map(), intervals = new Map(), sockets = [], accepted = [], target = new EventTarget();
  let next = 0, now = 0, fail = false;
  class FakeSocket {
    static OPEN = 1;
    readyState = 0;
    constructor() { if (fail) throw new Error('local socket fixture'); sockets.push(this); }
    open() { this.readyState = 1; this.onopen?.(); }
    frame(value) { this.onmessage?.({ data: JSON.stringify(value) }); }
    close() { this.readyState = 3; this.onclose?.(); }
  }
  class Clock extends Date { static now() { return now; } }
  const navigator = { onLine: true };
  const loaded = load('apps/web/src/app/services/prices-connection.ts', {
    './api': { getPricesWebSocketUrl: () => 'ws://owned.invalid/prices' },
    './price-stream': { acceptRightsRevision: value => { accepted.push(value); return value !== 'pending'; } },
  }, { Date: Clock, WebSocket: FakeSocket, window: target, navigator,
    setTimeout: (callback, delay) => { const id = ++next; timers.set(id, { callback, delay }); return id; }, clearTimeout: id => timers.delete(id),
    setInterval: callback => { const id = ++next; intervals.set(id, callback); return id; }, clearInterval: id => intervals.delete(id),
  });
  return { ...loaded, sockets, timers, intervals, accepted, target, navigator, fail: value => { fail = value; }, time: value => { now = value; },
    retry: () => { const [id, value] = timers.entries().next().value; timers.delete(id); value.callback(); } };
}
test('dashboard and cross-route notice watch share exactly one socket and retire final subscriber', () => {
  const h = connectionHarness(), frames = [], states = [];
  const dashboard = h.subscribePricesConnection({ message: value => frames.push(value) });
  const native = h.subscribePricesConnection({ status: value => states.push(value) });
  assert.equal(h.sockets.length, 1); h.sockets[0].open(); assert.equal(states.at(-1), 'live');
  h.sockets[0].frame({ type: 'heartbeat', rights_revision: 'current' }); assert.equal(frames.length, 1);
  dashboard(); assert.equal(h.sockets[0].readyState, 1);
  h.sockets[0].frame({ type: 'heartbeat', rights_revision: 'pending' }); assert.equal(h.accepted.at(-1), 'pending');
  native(); assert.equal(h.sockets[0].readyState, 3); assert.equal(h.timers.size, 0); assert.equal(h.intervals.size, 0);
});
test('socket reconnect uses bounded backoff; old socket and revoked revision cannot publish', () => {
  const h = connectionHarness(), frames = [], states = [];
  const stop = h.subscribePricesConnection({ message: value => frames.push(value), status: value => states.push(value) });
  const old = h.sockets[0]; old.open(); old.close(); assert.equal(states.at(-1), 'fallback');
  for (let index = 0; index < 8; index++) {
    assert.equal(h.timers.size, 1); const delay = [...h.timers.values()][0].delay; assert.ok(delay >= 800 && delay <= 36_000);
    h.retry(); h.sockets.at(-1).close();
  }
  old.frame({ rights_revision: 'current' }); assert.equal(frames.length, 0);
  h.retry(); h.sockets.at(-1).open(); h.sockets.at(-1).frame({ rights_revision: 'pending' }); assert.equal(frames.length, 0);
  stop(); assert.equal(h.timers.size, 0);
});
test('socket constructor fault and missing heartbeat recover without duplicate transport', () => {
  const h = connectionHarness(), states = []; h.fail(true);
  const stop = h.subscribePricesConnection({ status: value => states.push(value) });
  assert.equal(states.at(-1), 'fallback'); assert.equal(h.timers.size, 1);
  h.fail(false); h.retry(); assert.equal(h.sockets.length, 1); h.sockets[0].open();
  h.time(46_000); [...h.intervals.values()][0](); assert.equal(h.sockets[0].readyState, 3); assert.equal(h.timers.size, 1);
  stop(); assert.equal(h.timers.size, 0);
});
test('stalled connection is retired on deadline and its late open cannot become live', () => {
  const h = connectionHarness(), states = []; const stop = h.subscribePricesConnection({ status: value => states.push(value) });
  const stale = h.sockets[0]; h.time(46_000); [...h.intervals.values()][0]();
  assert.equal(states.at(-1), 'fallback'); assert.equal(h.timers.size, 1);
  stale.open(); assert.equal(states.at(-1), 'fallback'); h.retry(); assert.equal(h.sockets.length, 2); stop();
});
test('fast consent waits for live connection; stalled connect stops before consent', async () => {
  const h = harness(); let connected;
  h.deps.connect = callback => { connected = callback; callback('connecting'); return () => {}; };
  const enabling = h.controller.enable('en'); await flush(); assert.equal(h.calls.enable.length, 0);
  connected('live'); assert.equal(await enabling, true);
  const stalled = harness(); stalled.deps.connect = callback => { callback('connecting'); return () => {}; };
  const waiting = stalled.controller.enable('en'); await flush(); await stalled.advance(10_000);
  assert.equal(await waiting, false); assert.equal(stalled.calls.enable.length, 0); assert.equal(stalled.controller.snapshot().optedIn, false);
});
test('initial HTTP revision is confirmed before opening a first rights socket', async () => {
  const h = harness(); h.rights.revision = ''; h.rights.epoch = 0;
  h.deps.prices = async () => {
    if (h.rights.revision !== 'first-confirmed') { h.rights.revision = 'first-confirmed'; h.rights.epoch = 1; h.controller.rightsChanged(); }
  };
  h.deps.connect = callback => { assert.equal(h.rights.revision, 'first-confirmed'); callback('live'); return () => {}; };
  assert.equal(await h.controller.enable('en'), true);
});
test('web eligibility and current main controller accept a later committed lower ID once', async () => {
  const h = harness(), notices = [], event = { trusted: true };
  const { createNotificationController } = require('../apps/desktop/electron/native-notifications.cjs');
  const main = createNotificationController({
    platform: 'win32', packaged: true, identityReady: true, isSupported: () => true,
    isTrusted: value => value === event, isCurrentFrameTrusted: () => true,
    now: h.deps.now, setTimeout: h.deps.setTimeout, clearTimeout: h.deps.clearTimeout,
    nonce: () => 'a'.repeat(64), askConsent: async () => true,
    createNotification(options) {
      const native = new EventEmitter(); native.show = () => notices.push(options); native.close = () => {};
      return native;
    }, focusWindow() {}, openInbox() {},
  });
  h.deps.bridge = () => ({
    status: async () => main.status(event), enableSession: value => main.enableSession(event, structuredClone(value)),
    refreshLease: async value => main.refreshLease(event, structuredClone(value)), showPending: async value => main.showPending(event, structuredClone(value)),
    disableSession: async value => main.disableSession(event, structuredClone(value)), onOpenInbox: () => () => {},
  });
  assert.equal(await h.controller.enable('en'), true);
  await h.advance(1_000); h.items([h.notice(100)]); await h.advance(14_000); assert.equal(notices.length, 1);
  await h.advance(1_000); h.items([h.notice(99), h.notice(100, 15_000)]); await h.advance(14_000);
  assert.equal(notices.length, 2); assert.equal(h.controller.snapshot().optedIn, true);
  await h.advance(15_000); assert.equal(notices.length, 2);
  assert.doesNotMatch(JSON.stringify(notices), /999|private|token|xml|https/);
  h.controller.disable();
});
