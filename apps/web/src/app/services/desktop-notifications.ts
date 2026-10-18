import { api, getPrices, type NotificationItem, type NotificationPreferences, type UserProfile } from './api';
import { currentRightsEpoch, currentRightsRevision, rightsArePending } from './price-stream';
import { desktopNoticeSession, subscribeDesktopNoticeSession } from './desktop-notification-session';
import { subscribePricesConnection, type PricesConnectionStatus } from './prices-connection';
import type { DesktopNotificationBridge, DesktopNoticeScope } from './desktop-notification-types';

export const DESKTOP_OPEN_INBOX = 'desktop-open-inbox';
type State = { supported: boolean; optedIn: boolean; pending: boolean; reason: 'off' | 'ready' | 'blocked' };
type Dependencies = {
  bridge(): DesktopNotificationBridge | undefined;
  session(): { authenticated: boolean; generation: number };
  rights(): { epoch: number; revision: string; pending: boolean };
  me(signal: AbortSignal): Promise<UserProfile>;
  preferences(signal: AbortSignal): Promise<NotificationPreferences>;
  prices(signal: AbortSignal): Promise<unknown>;
  list(signal: AbortSignal): Promise<NotificationItem[]>;
  connect(status: (value: PricesConnectionStatus) => void): () => void;
  openInbox(): void;
  now(): number;
  setTimeout: typeof setTimeout;
  clearTimeout: typeof clearTimeout;
};

export function safeNoticeId(value: unknown): string | null {
  const text = typeof value === 'number' && Number.isSafeInteger(value) ? String(value) : value;
  return typeof text === 'string' && /^[1-9]\d{0,15}$/.test(text) && Number.isSafeInteger(Number(text)) ? text : null;
}
export function eligibleDesktopNotice(item: NotificationItem, baseline: number, now: number): string | null {
  if (!item || item.resource_type !== 'alert_trigger' || typeof item.resource_id !== 'string'
      || !/^[1-9]\d{0,18}$/.test(item.resource_id) || BigInt(item.resource_id) >= BigInt('9223372036854775808')
      || item.read_at !== null || typeof item.created_at !== 'string'
      || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(item.created_at)) return null;
  const created = Date.parse(item.created_at);
  return Number.isFinite(created) && created > baseline && created <= now + 30_000 && now - created <= 60_000 ? safeNoticeId(item.id) : null;
}
const validScope = (value: unknown): value is DesktopNoticeScope => {
  const scope = value as DesktopNoticeScope | null;
  return Boolean(scope && typeof scope.nonce === 'string' && /^[a-f0-9]{64}$/.test(scope.nonce)
    && Number.isSafeInteger(scope.sessionGeneration) && scope.sessionGeneration >= 0
    && Number.isSafeInteger(scope.rightsEpoch) && scope.rightsEpoch >= 0);
};
const sameScope = (left: DesktopNoticeScope, right: DesktopNoticeScope) => left.nonce === right.nonce
  && left.sessionGeneration === right.sessionGeneration && left.rightsEpoch === right.rightsEpoch;

export function createDesktopNotifications(deps: Dependencies) {
  let state: State = { supported: false, optedIn: false, pending: false, reason: 'off' };
  const listeners = new Set<() => void>();
  let scope: DesktopNoticeScope | null = null;
  let pendingGeneration: number | null = null;
  let operation = 0;
  let sessionGeneration = -1;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let request: AbortController | null = null;
  let disconnect: (() => void) | undefined;
  let socketStatus: PricesConnectionStatus = 'fallback';
  let baseline: number | null = null;
  let leaseUntil = 0;
  let awaitingConsent = false;
  let liveReady: ((live: boolean) => void) | undefined;
  const seen = new Set<string>();
  const publish = (next: Partial<State>) => { state = { ...state, ...next }; listeners.forEach(listener => listener()); };
  const bounded = async <T>(promise: Promise<T>, milliseconds = 18_000): Promise<T> => {
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try { return await Promise.race([promise, new Promise<never>((_, reject) => { timeout = deps.setTimeout(() => reject(new Error('Native notice deadline')), milliseconds); })]); }
    finally { deps.clearTimeout(timeout); }
  };
  function disable(reason: State['reason'] = 'off'): void {
    operation += 1;
    const generation = scope?.sessionGeneration ?? pendingGeneration;
    scope = null; pendingGeneration = null; awaitingConsent = false; leaseUntil = 0;
    liveReady?.(false); liveReady = undefined;
    request?.abort(); request = null; deps.clearTimeout(timer); timer = undefined;
    disconnect?.(); disconnect = undefined; socketStatus = 'fallback'; baseline = null; seen.clear();
    publish({ optedIn: false, pending: false, reason });
    if (generation !== null) {
      try { void deps.bridge()?.disableSession({ version: 1, sessionGeneration: generation }).catch(() => undefined); } catch { /* Local revoke already took effect. */ }
    }
  }
  const current = (token: number, active: DesktopNoticeScope | null = scope): boolean => {
    const session = deps.session(), rights = deps.rights();
    return token === operation && session.authenticated && session.generation === sessionGeneration
      && !rights.pending && Boolean(rights.revision) && (!active || rights.epoch === active.rightsEpoch);
  };
  function rightsChanged(): void {
    if (deps.rights().pending || scope || awaitingConsent) disable('blocked');
  }
  async function poll(): Promise<void> {
    if (!scope || request) return;
    const active = scope, token = operation, bridge = deps.bridge();
    if (!bridge || !current(token, active) || socketStatus !== 'live') { disable('blocked'); return; }
    const controller = new AbortController(); request = controller;
    try {
      const [user, prefs, , items] = await bounded(Promise.all([
        deps.me(controller.signal), deps.preferences(controller.signal), deps.prices(controller.signal), deps.list(controller.signal),
      ]));
      if (controller.signal.aborted || !current(token, active)) return;
      if (user.must_change_password !== false || prefs.push_app !== true || typeof prefs.silent_mode !== 'boolean'
          || !Array.isArray(items) || items.length > 1_000) throw new Error('Notice eligibility unavailable');
      if (!await bounded(bridge.refreshLease({ version: 1, ...active, pushApp: true, silent: prefs.silent_mode }), 3_000)) throw new Error('Notice lease rejected');
      if (controller.signal.aborted || !current(token, active)) return;
      leaseUntil = deps.now() + 40_000;
      if (baseline === null) {
        baseline = deps.now();
        items.forEach(item => { const id = safeNoticeId(item?.id); if (id) seen.add(id); });
      } else {
        const ids: string[] = [];
        for (const item of items) {
          const id = eligibleDesktopNotice(item, baseline, deps.now());
          if (!id || seen.has(id)) continue;
          seen.add(id); if (ids.length < 16) ids.push(id);
        }
        while (seen.size > 2_048) seen.delete(seen.values().next().value!);
        if (ids.length && current(token, active) && deps.now() < leaseUntil) {
          if (!await bounded(bridge.showPending({ version: 1, ...active, noticeIds: ids }), 3_000)) throw new Error('Notice request rejected');
        }
      }
      if (current(token, active)) timer = deps.setTimeout(() => void poll(), 15_000);
    } catch {
      if (token === operation) disable('blocked');
    } finally { if (request === controller) request = null; }
  }
  async function enable(locale: 'fa' | 'en'): Promise<boolean> {
    disable();
    const bridge = deps.bridge(), session = deps.session();
    if (!bridge || !session.authenticated) return false;
    sessionGeneration = session.generation;
    const token = operation;
    const controller = new AbortController(); request = controller;
    publish({ pending: true });
    try {
      const status = await bounded(bridge.status(), 3_000);
      if (token !== operation || !deps.session().authenticated || deps.session().generation !== sessionGeneration) return false;
      if (!status || !status.supported || !Number.isSafeInteger(status.sessionGeneration)) throw new Error('Native notices unavailable');
      publish({ supported: true }); pendingGeneration = status.sessionGeneration;
      const [user, prefs] = await bounded(Promise.all([deps.me(controller.signal), deps.preferences(controller.signal), deps.prices(controller.signal)]));
      if (controller.signal.aborted || !current(token, null)) return false;
      if (user.must_change_password !== false || prefs.push_app !== true || typeof prefs.silent_mode !== 'boolean') throw new Error('Native notices disabled');
      disconnect = deps.connect(value => {
        socketStatus = value;
        if (value === 'live') liveReady?.(true);
        if (value === 'fallback' && scope) disable('blocked');
      });
      if (socketStatus !== 'live') {
        const live = await bounded(new Promise<boolean>(resolve => { liveReady = resolve; }), 10_000);
        liveReady = undefined;
        if (!live || controller.signal.aborted || !current(token, null)) throw new Error('Notice connection unavailable');
      }
      const epoch = deps.rights().epoch;
      awaitingConsent = true;
      const granted = await bounded(bridge.enableSession({ version: 1, sessionGeneration: status.sessionGeneration, rightsEpoch: epoch, locale }), 22_000);
      awaitingConsent = false;
      if (!validScope(granted)) throw new Error('Native consent declined');
      if (controller.signal.aborted || !current(token, granted) || granted.sessionGeneration !== status.sessionGeneration || granted.rightsEpoch !== epoch) {
        void bridge.disableSession({ version: 1, sessionGeneration: granted.sessionGeneration }).catch(() => undefined);
        return false;
      }
      scope = granted; pendingGeneration = null; request = null;
      publish({ optedIn: true, pending: false, reason: 'ready' });
      await poll();
      return token === operation && state.optedIn;
    } catch { if (token === operation) disable('blocked'); return false; }
    finally { if (request === controller) request = null; }
  }
  function openInbox(value: DesktopNoticeScope): void {
    if (scope && validScope(value) && sameScope(scope, value) && current(operation, scope) && deps.now() < leaseUntil) deps.openInbox();
  }
  function start(): () => void {
    let active = true;
    const bridge = deps.bridge();
    const unsubscribe = bridge?.onOpenInbox(openInbox);
    if (bridge) void bounded(bridge.status(), 3_000).then(status => {
      if (!active || !status) return;
      publish({ supported: status.supported });
      if (status.optedIn && !scope && !state.pending) void bridge.disableSession({ version: 1, sessionGeneration: status.sessionGeneration }).catch(() => undefined);
    }).catch(() => undefined);
    return () => { active = false; unsubscribe?.(); disable(); };
  }
  return { start, enable, disable, poll, rightsChanged, openInbox,
    snapshot: () => state,
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
  };
}

export const desktopNotifications = createDesktopNotifications({
  bridge: () => window.electronAPI?.notifications,
  session: desktopNoticeSession,
  rights: () => ({ epoch: currentRightsEpoch(), revision: currentRightsRevision(), pending: rightsArePending() }),
  me: signal => api.auth.me(signal), preferences: signal => api.notifications.preferences(signal),
  prices: getPrices, list: signal => api.notifications.list(signal),
  connect: status => subscribePricesConnection({ status }),
  openInbox: () => window.dispatchEvent(new Event(DESKTOP_OPEN_INBOX)),
  now: Date.now,
  setTimeout: (callback, delay) => setTimeout(callback, delay),
  clearTimeout: timer => clearTimeout(timer),
});
subscribeDesktopNoticeSession(() => desktopNotifications.disable());
