import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const root = path.resolve(import.meta.dirname, '..');
const defer = () => { let resolve, reject; const promise = new Promise((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; };
const flush = async () => { for (let index = 0; index < 6; index++) await Promise.resolve(); };

function contextHarness(pending = false) {
  const states = [];
  const refs = [];
  const effects = [];
  const initial = defer();
  let stateIndex = 0, refIndex = 0, signouts = 0, syncs = 0, profiles = 0, logoutListener;
  const context = {};
  const react = {
    createContext: () => ({ Provider: {} }),
    createElement: (_type, props) => { context.value = props.value; return null; },
    useState: value => {
      const index = stateIndex++;
      if (!(index in states)) states[index] = typeof value === 'function' ? value() : value;
      return [states[index], next => { states[index] = typeof next === 'function' ? next(states[index]) : next; }];
    },
    useRef: value => { const index = refIndex++; return refs[index] ||= { current: value }; },
    useEffect: callback => { if (!context.mounted) effects.push(callback); },
    useCallback: callback => callback,
    useMemo: callback => callback(),
  };
  const imports = {
    react,
    '../services/api': { api: { auth: { me: () => { profiles++; return initial.promise; } } } },
    '../services/logout': { requestLogout: async () => { signouts++; } },
    '../services/logout-state': { logoutIsPending: () => pending, subscribeLogoutStatus: listener => { logoutListener = listener; return () => {}; } },
    '../services/desktop-notification-session': { startDesktopNoticeSession() {}, revokeDesktopNoticeSession() {} },
    '@/pwa/push': { disablePushNotifications: async () => {}, syncPushSubscription: async () => { syncs++; } },
    '../legal/storage': { readPreference: () => null, rememberPreference() {} },
  };
  const source = readFileSync(path.join(root, 'apps/web/src/app/context/AppContext.tsx'), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true } }).outputText;
  const runtime = { exports: {}, require: name => imports[name], setTimeout, clearTimeout, CustomEvent, window: { dispatchEvent() {} }, document: { documentElement: { classList: { add() {}, remove() {} } } } };
  vm.runInNewContext(compiled, runtime, { filename: 'AppContext.tsx' });
  const render = () => { stateIndex = 0; refIndex = 0; runtime.exports.AppProvider({ children: null }); return context.value; };
  render();
  const cleanup = effects.map(effect => effect());
  context.mounted = true;
  return { initial, render, value: () => context.value, unmount: () => cleanup.forEach(effect => effect?.()), signouts: () => signouts, syncs: () => syncs, profiles: () => profiles, pending: () => { pending = true; logoutListener(); } };
}

test('late startup profile cannot restore authentication after logout', async () => {
  const harness = contextHarness();
  await harness.value().logout();
  harness.initial.resolve({ must_change_password: true });
  await flush();
  const value = harness.render();
  assert.equal(value.isAuthenticated, false);
  assert.equal(value.mustChangePassword, false);
  assert.equal(value.authReady, true);
  assert.equal(harness.signouts(), 1);
  assert.equal(harness.syncs(), 0);
});

test('late startup rejection cannot discard a later successful login', async () => {
  const harness = contextHarness();
  harness.value().login({ must_change_password: true });
  harness.initial.reject(new Error('older profile expired'));
  await flush();
  const value = harness.render();
  assert.equal(value.isAuthenticated, true);
  assert.equal(value.mustChangePassword, true);
  assert.equal(value.authReady, true);
  assert.equal(harness.syncs(), 1);
});

test('current startup profile is applied and unmounted startup is ignored', async () => {
  const current = contextHarness();
  current.initial.resolve({ must_change_password: false });
  await flush();
  assert.equal(current.render().isAuthenticated, true);
  assert.equal(current.syncs(), 1);
  const closed = contextHarness();
  closed.unmount();
  closed.initial.resolve({ must_change_password: true });
  await flush();
  assert.equal(closed.render().isAuthenticated, false);
  assert.equal(closed.syncs(), 0);
});

test('unfinished logout skips startup profile and a cross-tab logout invalidates an in-flight profile', async () => {
  const locked = contextHarness(true);
  assert.equal(locked.profiles(), 0);
  assert.equal(locked.render().authReady, true);
  locked.value().login({ must_change_password: false });
  assert.equal(locked.render().isAuthenticated, false);
  const shared = contextHarness();
  shared.pending();
  shared.initial.resolve({ must_change_password: false });
  await flush();
  assert.equal(shared.render().isAuthenticated, false);
  assert.equal(shared.syncs(), 0);
});
