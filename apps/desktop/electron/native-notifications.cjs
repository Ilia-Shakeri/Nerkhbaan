const { randomBytes } = require('node:crypto');

const APP_ID = 'ir.nerkhbaan.desktop';
const TOAST_CLSID = '{26DC4DD1-8853-505B-8CDA-B9A48FFAA1AF}';
const LEASE_MS = 45_000;
const CONSENT_MS = 20_000;
const HOLD_MS = 30_000;
const CHANNELS = Object.freeze({
  status: 'native-notifications-status',
  enableSession: 'native-notifications-enable-session',
  refreshLease: 'native-notifications-refresh-lease',
  showPending: 'native-notifications-show-pending',
  disableSession: 'native-notifications-disable-session',
  openInbox: 'native-notifications-open-inbox',
});
const COPY = Object.freeze({
  fa: Object.freeze({
    body: 'هشدار تازه دارید. برای دیدن، برنامه را باز کنید.',
    consent: 'اعلان‌های عمومی ویندوز برای این نشست روشن شود؟ جزئیات در برنامه می‌ماند. برنامه باید باز بماند.',
    cancel: 'لغو', enable: 'روشن شود',
  }),
  en: Object.freeze({
    body: 'You have a new alert. Open the app to view it.',
    consent: 'Enable generic Windows notices for this session? Details stay in the app. The app must stay open.',
    cancel: 'Cancel', enable: 'Enable',
  }),
});

const safeInteger = value => Number.isSafeInteger(value) && value >= 0;
const validNonce = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

function record(value, keys) {
  try {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
    const proto = Object.getPrototypeOf(value);
    if (proto !== Object.prototype && proto !== null) return false;
    const own = Reflect.ownKeys(value);
    if (own.length !== keys.length || own.some(key => !keys.includes(key))) return false;
    if (Object.values(Object.getOwnPropertyDescriptors(value)).some(entry => !('value' in entry))) return false;
    return Buffer.byteLength(JSON.stringify(value), 'utf8') <= 1024 && value.version === 1;
  } catch { return false; }
}

function configureWindowsIdentity(app, platform) {
  if (platform !== 'win32' || !app.isPackaged) return false;
  try {
    app.setToastActivatorCLSID(TOAST_CLSID);
    app.setAppUserModelId(APP_ID);
    return true;
  } catch { return false; }
}

function createNotificationController(adapter) {
  const now = adapter.now || (() => performance.now());
  const schedule = adapter.setTimeout || setTimeout;
  const unschedule = adapter.clearTimeout || clearTimeout;
  const nonce = adapter.nonce || (() => randomBytes(32).toString('hex'));
  let generation = 0;
  let grant = null;
  let pending = null;
  let leaseUntil = 0;
  let leaseTimer = null;
  let lastEvent = 'idle';
  let showTimes = [];
  let seen = new Set();
  const held = new Set();

  const trusted = event => {
    try { return adapter.isTrusted(event) === true && adapter.isCurrentFrameTrusted() === true; } catch { return false; }
  };
  const currentFrame = () => {
    try { return adapter.isCurrentFrameTrusted() === true; } catch { return false; }
  };
  const supported = () => {
    try {
      return adapter.platform === 'win32' && adapter.packaged === true && adapter.identityReady === true
        && adapter.isSupported() === true && generation < Number.MAX_SAFE_INTEGER;
    } catch { return false; }
  };
  const timer = (callback, delay) => {
    const result = schedule(callback, delay);
    result?.unref?.();
    return result;
  };
  const setActive = active => {
    try { adapter.setActive?.(active); } catch { /* Teardown can outlive the window. */ }
  };
  const close = entry => {
    try { entry.native.close(); } catch { /* Removal remains a bounded best effort. */ }
  };
  const closeHeld = (retain = false) => {
    for (const entry of held) {
      entry.expired = true;
      unschedule(entry.timer);
      close(entry);
    }
    if (!retain) held.clear();
  };
  const expireLease = () => {
    if (grant && leaseUntil > 0 && now() >= leaseUntil) {
      leaseUntil = 0;
      lastEvent = 'expired';
      closeHeld(true);
    }
  };
  const leaseActive = () => {
    expireLease();
    return Boolean(grant && leaseUntil > now());
  };
  const scope = () => grant && ({ nonce: grant.nonce, sessionGeneration: generation, rightsEpoch: grant.rightsEpoch });
  const matches = value => Boolean(grant && validNonce(value.nonce) && safeInteger(value.sessionGeneration)
    && safeInteger(value.rightsEpoch) && value.nonce === grant.nonce
    && value.sessionGeneration === generation && value.rightsEpoch === grant.rightsEpoch);

  function revoke(reason = 'revoked') {
    const waiting = pending;
    pending = null;
    grant = null;
    leaseUntil = 0;
    unschedule(leaseTimer);
    leaseTimer = null;
    generation = Math.min(Number.MAX_SAFE_INTEGER, generation + 1);
    lastEvent = reason;
    seen.clear();
    showTimes = [];
    if (waiting) {
      unschedule(waiting.timer);
      waiting.abort.abort();
      waiting.finish(false);
    }
    closeHeld();
    setActive(false);
  }

  function status(event) {
    if (!trusted(event)) return false;
    return { supported: supported(), optedIn: Boolean(grant), sessionGeneration: generation,
      rightsEpoch: grant?.rightsEpoch ?? 0, leaseActive: leaseActive(), lastEvent };
  }

  function enableSession(event, value) {
    if (!trusted(event) || !supported() || !record(value, ['version', 'sessionGeneration', 'rightsEpoch', 'locale'])
      || !safeInteger(value.sessionGeneration) || value.sessionGeneration !== generation
      || !safeInteger(value.rightsEpoch) || typeof value.locale !== 'string'
      || !Object.hasOwn(COPY, value.locale) || pending || grant) return Promise.resolve(false);
    const capturedGeneration = generation;
    const started = now();
    return new Promise(resolve => {
      const waiting = { abort: new AbortController(), timer: null, finish: resolve };
      pending = waiting;
      waiting.timer = timer(() => { if (pending === waiting) revoke('expired'); }, CONSENT_MS);
      Promise.resolve().then(() => {
        if (pending !== waiting || !trusted(event) || !currentFrame()) return false;
        return adapter.askConsent(COPY[value.locale], waiting.abort.signal);
      }).then(accepted => {
        if (pending !== waiting) return;
        if (accepted !== true || waiting.abort.signal.aborted || generation !== capturedGeneration
          || now() - started >= CONSENT_MS || !trusted(event) || !currentFrame() || !supported()) {
          revoke('revoked');
          return;
        }
        const token = nonce();
        if (!validNonce(token)) { revoke('failed'); return; }
        pending = null;
        unschedule(waiting.timer);
        grant = { nonce: token, rightsEpoch: value.rightsEpoch, locale: value.locale, silent: true };
        lastEvent = 'enabled';
        setActive(true);
        resolve(scope());
      }).catch(() => { if (pending === waiting) revoke('failed'); });
    });
  }

  function refreshLease(event, value) {
    if (!trusted(event) || !supported() || !record(value, ['version', 'nonce', 'sessionGeneration', 'rightsEpoch', 'pushApp', 'silent'])
      || !matches(value) || typeof value.pushApp !== 'boolean' || typeof value.silent !== 'boolean') return false;
    if (!value.pushApp) { revoke(); return false; }
    grant.silent = value.silent;
    leaseUntil = now() + LEASE_MS;
    unschedule(leaseTimer);
    const expectedDeadline = leaseUntil;
    leaseTimer = timer(() => { if (leaseUntil === expectedDeadline) expireLease(); }, LEASE_MS);
    return true;
  }

  function showPending(event, value) {
    if (!trusted(event) || !supported() || !record(value, ['version', 'nonce', 'sessionGeneration', 'rightsEpoch', 'noticeIds'])
      || !matches(value) || !leaseActive() || !Array.isArray(value.noticeIds)
      || value.noticeIds.length < 1 || value.noticeIds.length > 16
      || value.noticeIds.some(id => typeof id !== 'string' || !/^[1-9][0-9]{0,15}$/.test(id) || !Number.isSafeInteger(Number(id)))
      || new Set(value.noticeIds).size !== value.noticeIds.length) return false;
    const ids = value.noticeIds.filter(id => !seen.has(id));
    if (!ids.length) return false;
    const stamp = now();
    showTimes = showTimes.filter(at => stamp - at < 60_000);
    if (showTimes.length >= 4 || (showTimes.length && stamp - showTimes.at(-1) < 15_000)) return false;
    showTimes.push(stamp);
    const captured = scope();
    let entry;
    try {
      const native = adapter.createNotification({ title: 'Nerkhbaan', body: COPY[grant.locale].body,
        silent: grant.silent, timeoutType: 'default' });
      entry = { native, timer: null, expired: false };
      if (!matches(captured) || !leaseActive() || !trusted(event) || !currentFrame()) { close(entry); return false; }
      while (held.size >= 4) {
        const oldest = held.values().next().value;
        held.delete(oldest); unschedule(oldest.timer); close(oldest);
      }
      held.add(entry);
      const live = () => held.has(entry) && !entry.expired && matches(captured) && leaseActive() && currentFrame();
      native.on('show', () => { if (live()) lastEvent = 'shown'; });
      native.on('failed', () => { if (live()) lastEvent = 'failed'; });
      native.on('close', () => { if (live()) lastEvent = 'closed'; });
      native.on('click', () => {
        if (!live()) return;
        lastEvent = 'clicked';
        try { adapter.focusWindow(); adapter.openInbox({ ...captured }); } catch { /* Window can close during a click. */ }
      });
      entry.timer = timer(() => {
        if (!held.has(entry)) return;
        entry.expired = true;
        close(entry);
      }, HOLD_MS);
      if (!live() || !trusted(event)) {
        held.delete(entry); unschedule(entry.timer); close(entry); return false;
      }
      lastEvent = 'accepted';
      native.show();
      for (const id of ids) {
        seen.add(id);
        if (seen.size > 512) seen.delete(seen.values().next().value);
      }
      return true;
    } catch {
      if (entry) { held.delete(entry); unschedule(entry.timer); close(entry); }
      lastEvent = 'failed';
      return false;
    }
  }

  function disableSession(event, value) {
    if (!trusted(event) || !record(value, ['version', 'sessionGeneration']) || !safeInteger(value.sessionGeneration)
      || value.sessionGeneration !== generation) return false;
    revoke();
    return true;
  }

  return Object.freeze({ status, enableSession, refreshLease, showPending, disableSession, revoke });
}

function registerNotificationIpc(ipcMain, controller) {
  for (const name of ['status', 'enableSession', 'refreshLease', 'showPending', 'disableSession']) {
    ipcMain.handle(CHANNELS[name], (event, ...args) => {
      if (args.length !== (name === 'status' ? 0 : 1)) return false;
      return controller[name](event, args[0]);
    });
  }
}

module.exports = { APP_ID, TOAST_CLSID, LEASE_MS, CONSENT_MS, HOLD_MS, CHANNELS, COPY,
  configureWindowsIdentity, createNotificationController, registerNotificationIpc };
