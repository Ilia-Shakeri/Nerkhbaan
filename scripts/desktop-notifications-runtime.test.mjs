import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { APP_ID, TOAST_CLSID, CHANNELS, COPY, createNotificationController,
  configureWindowsIdentity, registerNotificationIpc } = require('../apps/desktop/electron/native-notifications.cjs');
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const event = { trusted: true };
const request = (scope, extra = {}) => ({ version: 1, ...scope, ...extra });

function clock() {
  let stamp = 0;
  let serial = 0;
  const tasks = new Map();
  return {
    now: () => stamp,
    setTimeout: (fn, delay) => { const id = ++serial; tasks.set(id, { fn, due: stamp + delay }); return id; },
    clearTimeout: id => tasks.delete(id),
    tick(ms) {
      const end = stamp + ms;
      for (;;) {
        const next = [...tasks].filter(([, value]) => value.due <= end).sort((a, b) => a[1].due - b[1].due)[0];
        if (!next) break;
        tasks.delete(next[0]); stamp = next[1].due; next[1].fn();
      }
      stamp = end;
    },
  };
}

function fixture(changes = {}) {
  const time = clock();
  const notices = [];
  const dialogs = [];
  const inbox = [];
  const active = [];
  let trustedFrame = true;
  let focused = 0;
  let serial = 0;
  const adapter = {
    platform: 'win32', packaged: true, identityReady: true, isSupported: () => true,
    isTrusted: value => value?.trusted === true,
    isCurrentFrameTrusted: () => trustedFrame,
    now: time.now, setTimeout: time.setTimeout, clearTimeout: time.clearTimeout,
    nonce: () => (++serial).toString(16).padStart(64, '0'),
    askConsent: (copy, signal) => new Promise(resolve => dialogs.push({ copy, signal, resolve })),
    createNotification(options) {
      const native = new EventEmitter();
      Object.assign(native, { options, shows: 0, closes: 0,
        show() { this.shows++; }, close() { this.closes++; this.emit('close'); } });
      notices.push(native);
      return native;
    },
    focusWindow: () => { focused++; }, openInbox: value => inbox.push(value), setActive: value => active.push(value),
    ...changes,
  };
  const controller = createNotificationController(adapter);
  async function enable(rightsEpoch = 7, locale = 'en') {
    const pending = controller.enableSession(event, { version: 1,
      sessionGeneration: controller.status(event).sessionGeneration, rightsEpoch, locale });
    await flush();
    dialogs.at(-1).resolve(true);
    return pending;
  }
  const lease = (scope, silent = false) => controller.refreshLease(event, request(scope, { pushApp: true, silent }));
  const show = (scope, ids = ['1']) => controller.showPending(event, request(scope, { noticeIds: ids }));
  return { controller, adapter, time, notices, dialogs, inbox, active, enable, lease, show,
    get focused() { return focused; }, setFrame(value) { trustedFrame = value; } };
}

test('01 Windows identity stays pinned; unsupported and unpackaged runtimes never create or prompt', async () => {
  const calls = [];
  const app = { isPackaged: true, setToastActivatorCLSID: value => calls.push(['clsid', value]),
    setAppUserModelId: value => calls.push(['aumid', value]) };
  assert.equal(configureWindowsIdentity(app, 'win32'), true);
  assert.deepEqual(calls, [['clsid', TOAST_CLSID], ['aumid', APP_ID]]);
  assert.equal(APP_ID, JSON.parse(readFileSync(new URL('../apps/desktop/package.json', import.meta.url))).build.appId);
  assert.match(TOAST_CLSID, /^\{[A-F0-9]{8}(?:-[A-F0-9]{4}){3}-[A-F0-9]{12}\}$/);
  for (const changes of [{ packaged: false }, { platform: 'linux' }, { identityReady: false }, { isSupported: () => false }]) {
    const f = fixture(changes);
    assert.equal(f.controller.status(event).supported, false);
    assert.equal(await f.controller.enableSession(event, { version: 1, sessionGeneration: 0, rightsEpoch: 0, locale: 'en' }), false);
    assert.equal(f.dialogs.length, 0); assert.equal(f.notices.length, 0);
  }
  calls.length = 0; app.isPackaged = false;
  assert.equal(configureWindowsIdentity(app, 'win32'), false); assert.equal(calls.length, 0);
});

test('02 every main request rejects untrusted senders without changing a trusted session', async () => {
  const f = fixture(); const scope = await f.enable(); f.lease(scope);
  const bad = { trusted: false };
  assert.equal(f.controller.status(bad), false);
  assert.equal(await f.controller.enableSession(bad, { version: 1, sessionGeneration: 0, rightsEpoch: 7, locale: 'en' }), false);
  assert.equal(f.controller.refreshLease(bad, request(scope, { pushApp: true, silent: false })), false);
  assert.equal(f.controller.showPending(bad, request(scope, { noticeIds: ['1'] })), false);
  assert.equal(f.controller.disableSession(bad, { version: 1, sessionGeneration: 0 }), false);
  assert.equal(f.controller.status(event).optedIn, true); assert.equal(f.notices.length, 0);
});

test('03 explicit consent pins locale and epochs; fresh lease shows only fixed generic options and silent flag', async () => {
  const f = fixture(); const scope = await f.enable(17, 'fa');
  assert.deepEqual(scope, { nonce: '1'.padStart(64, '0'), sessionGeneration: 0, rightsEpoch: 17 });
  assert.equal(f.controller.status(event).leaseActive, false); assert.equal(f.show(scope), false);
  assert.equal(f.lease(scope, true), true); assert.equal(f.show(scope, ['12', '13']), true);
  assert.deepEqual(f.notices[0].options, { title: 'Nerkhbaan', body: COPY.fa.body, silent: true, timeoutType: 'default' });
  assert.equal(f.notices[0].shows, 1); assert.deepEqual(f.active, [true]);
  assert.equal(f.dialogs[0].copy, COPY.fa);
});

test('04 one consent dialog; cancel, deadline and every late completion stay off', async () => {
  const f = fixture();
  const payload = { version: 1, sessionGeneration: 0, rightsEpoch: 7, locale: 'en' };
  const first = f.controller.enableSession(event, payload); await flush();
  assert.equal(await f.controller.enableSession(event, payload), false); assert.equal(f.dialogs.length, 1);
  f.dialogs[0].resolve(false); assert.equal(await first, false);
  const generation = f.controller.status(event).sessionGeneration;
  const second = f.controller.enableSession(event, { ...payload, sessionGeneration: generation }); await flush();
  f.time.tick(20_000); assert.equal(await second, false); assert.equal(f.dialogs[1].signal.aborted, true);
  f.dialogs[1].resolve(true); await flush(); assert.equal(f.controller.status(event).optedIn, false);
});

test('05 malformed records, unsafe IDs, hidden keys and private text fail before native construction', async () => {
  const f = fixture(); const scope = await f.enable(); f.lease(scope);
  const base = request(scope, { noticeIds: ['1'] });
  const bad = [null, [], { ...base, version: true }, { ...base, version: 2 }, { ...base, message: 'account price token https://bad.test <xml>' },
    { ...base, nonce: 'x'.repeat(2048) }, { ...base, noticeIds: [] }, { ...base, noticeIds: ['1', '1'] },
    { ...base, noticeIds: ['01'] }, { ...base, noticeIds: ['0'] }, { ...base, noticeIds: ['-1'] },
    { ...base, noticeIds: ['9007199254740992'] }, { ...base, noticeIds: ['1\n'] },
    { ...base, noticeIds: [1] }, { ...base, noticeIds: Array.from({ length: 17 }, (_, index) => String(index + 1)) },
    Object.assign(Object.create({ inherited: true }), base), { ...base, [Symbol('private')]: true }];
  const accessor = { ...base }; Object.defineProperty(accessor, 'nonce', { get() { throw new Error('must not read'); }, enumerable: true }); bad.push(accessor);
  for (const value of bad) assert.equal(f.controller.showPending(event, value), false);
  assert.equal(f.notices.length, 0);
  assert.equal(f.show(scope, ['9007199254740991']), true);
});

test('06 wrong nonce, stale generation and changed rights never renew, show or revoke a newer grant', async () => {
  const f = fixture(); const old = await f.enable(); f.lease(old);
  f.controller.disableSession(event, { version: 1, sessionGeneration: old.sessionGeneration });
  const scope = await f.enable(8); f.lease(scope);
  for (const changed of [{ nonce: old.nonce }, { sessionGeneration: old.sessionGeneration }, { rightsEpoch: 7 }]) {
    assert.equal(f.lease({ ...scope, ...changed }), false); assert.equal(f.show({ ...scope, ...changed }), false);
  }
  assert.equal(f.controller.disableSession(event, { version: 1, sessionGeneration: old.sessionGeneration }), false);
  assert.equal(f.controller.status(event).optedIn, true); assert.equal(f.show(scope), true);
});

test('07 lease expiry blocks queued shows; a renewed lease defeats an older expiry and global off closes notices', async () => {
  const f = fixture(); const scope = await f.enable(); f.lease(scope); f.show(scope);
  f.time.tick(30_000); f.lease(scope); f.time.tick(15_000);
  assert.equal(f.controller.status(event).leaseActive, true);
  f.time.tick(30_000); assert.equal(f.controller.status(event).leaseActive, false);
  assert.equal(f.controller.status(event).lastEvent, 'expired'); assert.equal(f.show(scope, ['2']), false);
  f.lease(scope); f.show(scope, ['2']);
  assert.equal(f.controller.refreshLease(event, request(scope, { pushApp: false, silent: false })), false);
  assert.equal(f.controller.status(event).optedIn, false); assert.ok(f.notices.every(value => value.closes > 0));
  assert.equal(f.lease(scope), false);
});

test('08 revoke during pending consent or native construction cannot produce a late grant or show', async () => {
  const f = fixture(); const pending = f.controller.enableSession(event, { version: 1, sessionGeneration: 0, rightsEpoch: 0, locale: 'en' }); await flush();
  f.controller.disableSession(event, { version: 1, sessionGeneration: 0 });
  assert.equal(await pending, false); f.dialogs[0].resolve(true); await flush();
  assert.equal(f.controller.status(event).optedIn, false);
  const scope = await f.enable(); f.lease(scope);
  const create = f.adapter.createNotification;
  f.adapter.createNotification = options => { const value = create(options); f.controller.revoke(); return value; };
  assert.equal(f.show(scope), false); assert.equal(f.notices[0].shows, 0); assert.equal(f.notices[0].closes, 1);
});

test('09 timeout close retains the object for revoke and short expiry removal attempts', async () => {
  const f = fixture(); const scope = await f.enable(); f.lease(scope); f.show(scope);
  const native = f.notices[0]; native.emit('close', { reason: 'timedOut' });
  assert.equal(native.closes, 0); f.controller.revoke(); assert.equal(native.closes, 1);
  const next = await f.enable(); f.lease(next); f.show(next, ['2']);
  const second = f.notices[1]; second.emit('close', { reason: 'timedOut' }); f.time.tick(30_000);
  assert.equal(second.closes, 1); second.emit('click'); assert.equal(f.inbox.length, 0);
  f.controller.revoke(); assert.equal(second.closes, 2);
  const thirdScope = await f.enable(); f.lease(thirdScope); f.show(thirdScope, ['3']);
  const third = f.notices[2]; f.time.tick(45_000); assert.equal(third.closes, 2);
  f.controller.revoke(); assert.equal(third.closes, 3);
});

test('10 submitted, shown, failed, clicked and closed are distinct; revoked native callbacks stay inert', async () => {
  const f = fixture(); const scope = await f.enable(); f.lease(scope); f.show(scope);
  const native = f.notices[0]; assert.equal(f.controller.status(event).lastEvent, 'accepted');
  for (const [name, expected] of [['show', 'shown'], ['failed', 'failed'], ['close', 'closed'], ['click', 'clicked']]) {
    native.emit(name, {}, 'private error URL and token'); assert.equal(f.controller.status(event).lastEvent, expected);
  }
  assert.equal(f.focused, 1); assert.deepEqual(f.inbox, [scope]);
  f.controller.revoke(); native.emit('show'); native.emit('click');
  assert.equal(f.controller.status(event).lastEvent, 'revoked'); assert.equal(f.inbox.length, 1);
  assert.equal(Object.hasOwn(f.controller.status(event), 'delivered'), false);
});

test('11 polling replay and large sessions stay bounded by coalescing, rate cap and recent ID cache', async () => {
  const f = fixture(); const scope = await f.enable(); f.lease(scope);
  assert.equal(f.show(scope, ['1', '2', '3']), true); assert.equal(f.show(scope, ['4']), false);
  f.time.tick(15_000); f.lease(scope); assert.equal(f.show(scope, ['3']), false); assert.equal(f.show(scope, ['4']), true);
  f.time.tick(15_000); f.lease(scope); assert.equal(f.show(scope, ['5']), true);
  f.time.tick(15_000); f.lease(scope); assert.equal(f.show(scope, ['6']), true);
  assert.equal(f.show(scope, ['7']), false);
  for (let id = 7; id <= 530; id++) { f.time.tick(15_000); f.lease(scope); assert.equal(f.show(scope, [String(id)]), true); }
  f.time.tick(15_000); f.lease(scope); assert.equal(f.show(scope, ['529']), false);
  assert.ok(f.notices.slice(0, -2).every(value => value.closes > 0));
  f.notices[0].emit('click'); assert.equal(f.inbox.length, 0);
});

test('16 later committed lower notice ID is accepted once and replay stays blocked', async () => {
  const f = fixture(); const scope = await f.enable(); f.lease(scope);
  assert.equal(f.show(scope, ['100']), true);
  f.time.tick(15_000); f.lease(scope); assert.equal(f.show(scope, ['99']), true);
  f.time.tick(15_000); f.lease(scope); assert.equal(f.show(scope, ['99']), false);
  assert.equal(f.show(scope, ['100']), false); assert.equal(f.notices.length, 2);
});

function mainRuntime() {
  const handles = new Map(); const notices = []; const identity = []; const sent = []; const windows = [];
  const app = new EventEmitter();
  Object.assign(app, { isPackaged: true, commandLine: { getSwitchValue: () => '' }, setName() {}, requestSingleInstanceLock: () => true,
    quit() {}, getPath: () => '/isolated-fixture', whenReady: () => Promise.resolve(),
    setToastActivatorCLSID: value => identity.push(['clsid', value]), setAppUserModelId: value => identity.push(['aumid', value]) });
  class Window extends EventEmitter {
    constructor() {
      super(); windows.push(this);
      const web = this.webContents = new EventEmitter();
      Object.assign(web, { mainFrame: { url: 'nerkhbaan://app/index.html' }, isDestroyed: () => false,
        getURL: () => web.mainFrame.url, setWindowOpenHandler() {}, setBackgroundThrottling() {},
        send: (...values) => sent.push(values) });
    }
    isDestroyed() { return false; } loadURL() { return Promise.resolve(); } maximize() {} isMinimized() { return false; }
    restore() {} show() {} focus() {}
  }
  class Native extends EventEmitter {
    static isSupported() { return true; }
    constructor(options) { super(); this.options = options; this.closes = 0; notices.push(this); }
    show() {} close() { this.closes++; this.emit('close'); }
  }
  let rmCalled = false;
  const electron = { app, BrowserWindow: Window, Notification: Native, dialog: { showMessageBox: async () => ({ response: 1 }) },
    ipcMain: { handle: (name, handler) => handles.set(name, handler), on() {} }, safeStorage: { isEncryptionAvailable: () => false },
    session: { defaultSession: { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} } },
    shell: { openExternal: () => { throw new Error('unexpected shell'); } }, protocol: { registerSchemesAsPrivileged() {}, handle() {} }, net: {} };
  const fakeFs = { promises: { rm: async () => { rmCalled = true; throw new Error('synthetic file failure'); } } };
  const context = { require: name => name === 'electron' ? electron : name === 'fs' ? fakeFs
    : name === './native-notifications.cjs' ? require('../apps/desktop/electron/native-notifications.cjs') : require(name),
  __dirname: '/fixture/electron', process: { platform: 'win32' }, URL, Response, console: { error() {}, log() {} } };
  vm.runInNewContext(readFileSync(new URL('../apps/desktop/electron/main.cjs', import.meta.url), 'utf8'), context);
  return { handles, notices, identity, sent, windows, app, get rmCalled() { return rmCalled; } };
}

test('12 actual main frame gates and every teardown revoke before async credential cleanup', async () => {
  const runtime = mainRuntime(); await flush();
  const window = runtime.windows[0]; const web = window.webContents;
  const good = { sender: web, senderFrame: web.mainFrame };
  const call = (method, ...args) => runtime.handles.get(CHANNELS[method])(good, ...args);
  for (const bad of [{ sender: {}, senderFrame: web.mainFrame }, { sender: web, senderFrame: { url: web.mainFrame.url } }]) {
    for (const method of ['status', 'enableSession', 'refreshLease', 'showPending', 'disableSession']) {
      const args = method === 'status' ? [] : [{ version: 1, sessionGeneration: 0, rightsEpoch: 0, locale: 'en' }];
      assert.equal(await runtime.handles.get(CHANNELS[method])(bad, ...args), false);
    }
  }
  web.mainFrame.url = 'https://untrusted.example/index.html'; assert.equal(call('status'), false); web.mainFrame.url = 'nerkhbaan://app/index.html';
  async function show() {
    const scope = await call('enableSession', { version: 1, sessionGeneration: call('status').sessionGeneration, rightsEpoch: 1, locale: 'en' });
    assert.ok(scope); assert.equal(call('refreshLease', request(scope, { pushApp: true, silent: true })), true);
    assert.equal(call('showPending', request(scope, { noticeIds: ['1'] })), true); return scope;
  }
  await show(); const clearing = runtime.handles.get('auth-clear-credentials')(good);
  assert.equal(runtime.rmCalled, true); assert.equal(call('status').optedIn, false); assert.equal(runtime.notices[0].closes, 1);
  await assert.rejects(clearing, /synthetic file failure/);
  for (const name of ['render-process-gone', 'destroyed']) {
    await show(); web.emit(name); assert.equal(call('status').optedIn, false);
  }
  await show(); web.emit('did-start-navigation', {}, 'nerkhbaan://app/index.html#/settings', true, true);
  assert.equal(call('status').optedIn, true); web.emit('did-start-navigation', {}, 'nerkhbaan://app/index.html', false, true);
  assert.equal(call('status').optedIn, false);
  await show(); runtime.app.emit('before-quit'); assert.equal(call('status').optedIn, false);
  assert.deepEqual(runtime.identity, [['clsid', TOAST_CLSID], ['aumid', APP_ID]]);
});

function preloadRuntime(invoke) {
  const events = new EventEmitter(); const time = clock(); let bridge;
  const ipc = { invoke, on: (name, listener) => events.on(name, listener), removeListener: (name, listener) => events.removeListener(name, listener), send() {} };
  vm.runInNewContext(readFileSync(new URL('../apps/desktop/electron/preload.js', import.meta.url), 'utf8'), {
    require: () => ({ contextBridge: { exposeInMainWorld: (_name, value) => { bridge = value; } }, ipcRenderer: ipc }),
    process: { platform: 'win32', versions: {} }, setTimeout: time.setTimeout, clearTimeout: time.clearTimeout,
  });
  return { bridge: bridge.notifications, events, time };
}

test('13 preload exposes only six frozen methods; subscribe strips the raw event and unsubscribe wins late attach', async () => {
  const scope = { nonce: 'a'.repeat(64), sessionGeneration: 4, rightsEpoch: 5 };
  let resolveStatus;
  const f = preloadRuntime(() => new Promise(resolve => { resolveStatus = resolve; }));
  assert.equal(Object.isFrozen(f.bridge), true);
  assert.deepEqual(Object.keys(f.bridge).sort(), ['disableSession', 'enableSession', 'onOpenInbox', 'refreshLease', 'showPending', 'status']);
  const received = []; const stop = f.bridge.onOpenInbox(value => received.push(value)); await flush();
  stop(); stop(); resolveStatus({ supported: true }); await flush(); assert.equal(f.events.listenerCount(CHANNELS.openInbox), 0);
  const stop2 = f.bridge.onOpenInbox(value => received.push(value)); await flush(); resolveStatus({ supported: true }); await flush();
  f.events.emit(CHANNELS.openInbox, { secretRawEvent: true }, { ...scope, message: 'forbidden' });
  assert.equal(received.length, 0); f.events.emit(CHANNELS.openInbox, { secretRawEvent: true }, scope);
  assert.equal(received.length, 1); assert.deepEqual(JSON.parse(JSON.stringify(received[0])), scope); assert.equal(Object.isFrozen(received[0]), true);
  stop2(); assert.equal(f.events.listenerCount(CHANNELS.openInbox), 0);
});

test('14 preload converts throw/reject/timeout to false and revoke defeats a late enable reply', async () => {
  const throwing = preloadRuntime(() => { throw new Error('closed transport'); });
  assert.equal(await throwing.bridge.status(), false); assert.equal(await throwing.bridge.showPending({}), false);
  let resolveEnable;
  const f = preloadRuntime(channel => channel === CHANNELS.enableSession ? new Promise(resolve => { resolveEnable = resolve; }) : Promise.resolve(true));
  const pending = f.bridge.enableSession({}); await flush(); await f.bridge.disableSession({});
  resolveEnable({ nonce: 'a'.repeat(64), sessionGeneration: 0, rightsEpoch: 0 }); assert.equal(await pending, false);
  const never = preloadRuntime(() => new Promise(() => {})); const status = never.bridge.status(); never.time.tick(3000); assert.equal(await status, false);
});

test('15 narrow IPC registration rejects extra arguments; failed constructors and late frame loss never show', async () => {
  const f = fixture(); const handlers = new Map(); registerNotificationIpc({ handle: (name, handler) => handlers.set(name, handler) }, f.controller);
  assert.equal(handlers.size, 5); assert.equal(handlers.get(CHANNELS.status)(event, 'extra'), false);
  assert.equal(await handlers.get(CHANNELS.enableSession)(event), false);
  const scope = await f.enable(); f.lease(scope); f.setFrame(false);
  assert.equal(f.show(scope), false); assert.equal(f.notices.length, 0);
  f.setFrame(true); f.adapter.createNotification = () => { throw new Error('private platform failure'); };
  assert.equal(f.show(scope, ['2']), false); assert.equal(f.controller.status(event).lastEvent, 'failed');
});
