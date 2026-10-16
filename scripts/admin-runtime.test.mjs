import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const root = path.resolve(import.meta.dirname, '..');
const flush = async () => { for (let index = 0; index < 12; index++) await Promise.resolve(); };
function moduleAt(file, globals, imports = {}) {
  const source = readFileSync(path.join(root, file), 'utf8').replaceAll('import.meta.env', '__env');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const context = { exports: {}, require: name => imports[name], __env: {}, Headers, AbortController, DOMException, Event, setTimeout, clearTimeout, ...globals };
  vm.runInNewContext(compiled, context, { filename: file });
  return context.exports;
}

function harness(fetch) {
  const timers = new Map(); let nextTimer = 0;
  const values = new Map([['nerkhbaan_admin_csrf', 'fake-csrf']]);
  const events = [];
  const exports = moduleAt('apps/admin-web/src/api.ts', {
    fetch, sessionStorage: { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) },
    window: { dispatchEvent: event => events.push(event.type) },
    setTimeout: callback => { timers.set(++nextTimer, callback); return nextTimer; }, clearTimeout: id => timers.delete(id),
  });
  return { ...exports, events, timers, timeout: () => { for (const callback of [...timers.values()]) callback(); } };
}
const settle = promise => Promise.race([promise.then(value => ({ value }), error => ({ error })), new Promise(resolve => setTimeout(() => resolve({ hung: true }), 40))]);

test('admin read timeout aborts stalled transport and remains retryable by the caller', async () => {
  let calls = 0, signal;
  const client = harness((_url, init) => { calls++; signal = init.signal; return new Promise(() => {}); });
  const request = settle(client.adminApi.get('/users'));
  await flush(); client.timeout();
  const result = await request;
  assert.equal(result.hung, undefined, 'stalled admin fetch must finish with a timeout');
  assert.equal(result.error.status, 408);
  assert.match(result.error.message, /timed out/i);
  assert.equal(signal.aborted, true);
  assert.equal(calls, 1);
  assert.equal(client.timers.size, 0);
});

test('admin timeout covers a stalled response body and never repeats a sensitive write', async () => {
  let calls = 0;
  const client = harness(async () => { calls++; return { status: 200, ok: true, headers: new Headers({ 'content-type': 'application/json' }), json: () => new Promise(() => {}) }; });
  const request = settle(client.adminApi.post('/users/2/access', { role: 'owner' }));
  await flush(); client.timeout();
  const result = await request;
  assert.equal(result.hung, undefined, 'a stalled response body must remain bounded');
  assert.match(result.error.message, /may have completed/i);
  assert.equal(calls, 1);
});

test('admin caller cancellation aborts read transport without expiring session', async () => {
  let signal;
  const client = harness((_url, init) => { signal = init.signal; return new Promise(() => {}); });
  const controller = new AbortController();
  const request = settle(client.adminApi.get('/users', controller.signal));
  await flush(); controller.abort();
  const result = await request;
  assert.equal(result.hung, undefined, 'caller cancellation must end the read');
  assert.equal(result.error.name, 'AbortError');
  assert.equal(signal.aborted, true);
  assert.deepEqual(client.events, []);
  assert.equal(client.timers.size, 0);
});

test('already cancelled admin reads send no request and late responses have no session side effects', async () => {
  let calls = 0, release;
  const client = harness(() => { calls++; return new Promise(resolve => { release = resolve; }); });
  const stopped = new AbortController(); stopped.abort();
  await assert.rejects(client.adminApi.get('/users', stopped.signal), { name: 'AbortError' });
  assert.equal(calls, 0);
  const active = new AbortController();
  const request = client.adminApi.get('/users', active.signal);
  active.abort();
  await assert.rejects(request, { name: 'AbortError' });
  release(new Response(JSON.stringify({ detail: 'Expired old read' }), { status: 401, headers: { 'content-type': 'application/json' } }));
  await flush();
  assert.deepEqual(client.events, []);
});

test('admin download body timeout aborts its stream without a second request', async () => {
  let calls = 0, signal;
  const client = harness(async (_url, init) => { calls++; signal = init.signal; return { status: 200, ok: true, blob: () => new Promise(() => {}) }; });
  const request = settle(client.adminApi.download('/audit/export'));
  await flush(); client.timeout();
  const result = await request;
  assert.equal(result.hung, undefined);
  assert.equal(result.error.status, 408);
  assert.equal(signal.aborted, true);
  assert.equal(calls, 1);
});

test('admin signin and downloads also have a bounded request lifetime', async () => {
  const client = harness(() => new Promise(() => {}));
  const signin = settle(client.adminApi.signin('test', 'fake-password'));
  const download = settle(client.adminApi.download('/audit/export'));
  await flush(); client.timeout();
  for (const result of await Promise.all([signin, download])) {
    assert.equal(result.hung, undefined);
    assert.equal(result.error.status, 408);
  }
});

test('admin authentication errors preserve MFA retry and expire an invalid session', async () => {
  let detail = 'MFA code is invalid';
  const client = harness(async () => new Response(JSON.stringify({ detail }), { status: 401, headers: { 'content-type': 'application/json' } }));
  await assert.rejects(client.adminApi.reauthenticate('fake-password', '000000'), /MFA code/);
  assert.deepEqual(client.events, []);
  detail = 'Session expired';
  await assert.rejects(client.adminApi.get('/users'), /Session expired/);
  assert.deepEqual(client.events, ['admin-session-expired']);
});

test('admin resource cancels replaced reads and unmount without surfacing cancellation', async () => {
  const states = [], refs = [], memos = [], effects = []; const calls = [];
  let stateIndex = 0, refIndex = 0, memoIndex = 0, effectIndex = 0;
  const equal = (left, right) => left && left.length === right.length && left.every((value, index) => value === right[index]);
  const react = {
    useState: initial => { const index = stateIndex++; if (!(index in states)) states[index] = initial; return [states[index], value => { states[index] = typeof value === 'function' ? value(states[index]) : value; }]; },
    useRef: initial => { const index = refIndex++; return refs[index] ||= { current: initial }; },
    useCallback: (callback, deps) => { const index = memoIndex++; if (!equal(memos[index]?.deps, deps)) memos[index] = { callback, deps }; return memos[index].callback; },
    useEffect: (callback, deps) => { const index = effectIndex++; if (!equal(effects[index]?.deps, deps)) { effects[index]?.cleanup?.(); effects[index] = { callback, deps, pending: true }; } },
  };
  const { useResource } = moduleAt('apps/admin-web/src/ui.tsx', {}, { react, 'react/jsx-runtime': {}, './api': { ApiError: Error, adminApi: { get: (url, signal) => new Promise((resolve, reject) => { calls.push({ url, signal, resolve, reject }); signal?.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError'))); }) } } });
  const render = (url = '/users') => { stateIndex = refIndex = memoIndex = effectIndex = 0; const value = useResource(url, []); for (const effect of effects) if (effect.pending) { effect.pending = false; effect.cleanup = effect.callback(); } return value; };
  let value = render();
  void value.reload();
  assert.equal(calls[0].signal?.aborted, true, 'manual reload must abort the prior HTTP read');
  render('/reports');
  assert.equal(calls[1].signal.aborted, true, 'path changes must abort the replaced HTTP read');
  await flush();
  value = render('/reports');
  assert.equal(value.error, '');
  calls[2].resolve(['fresh report']);
  await flush();
  value = render('/reports');
  assert.equal(value.data[0], 'fresh report');
  assert.equal(value.loading, false);
  for (const effect of effects) effect.cleanup?.();
  assert.equal(calls[2].signal.aborted, true, 'unmount must abort the active HTTP read');
  await flush();
});
