import { getPricesWebSocketUrl } from './api';
import { acceptRightsRevision } from './price-stream';
export type PricesConnectionStatus = 'connecting' | 'live' | 'fallback';
type Listener = { message?: (value: unknown) => void; status?: (value: PricesConnectionStatus) => void };
const listeners = new Set<Listener>();
let socket: WebSocket | null = null;
let retry: ReturnType<typeof setTimeout> | undefined;
let watchdog: ReturnType<typeof setInterval> | undefined;
let retries = 0;
let lastMessage = 0;
let connectedAt = 0;
let status: PricesConnectionStatus = 'fallback';
let installed = false;
const publish = (value: PricesConnectionStatus) => { status = value; [...listeners].forEach(listener => listener.status?.(value)); };
function scheduleRetry(): void {
  if (!listeners.size) return;
  const delay = Math.min(1_000 * 2 ** Math.min(retries++, 5), 30_000);
  retry = setTimeout(connect, Math.round(delay * (0.8 + Math.random() * 0.4)));
}
function connect(): void {
  clearTimeout(retry); retry = undefined;
  if (!listeners.size || socket) return;
  if (!navigator.onLine) { publish('fallback'); return; }
  publish('connecting');
  let current: WebSocket;
  try { current = new WebSocket(getPricesWebSocketUrl()); }
  catch { publish('fallback'); scheduleRetry(); return; }
  socket = current; connectedAt = Date.now();
  current.onopen = () => {
    if (socket !== current) return;
    retries = 0; lastMessage = Date.now(); publish('live');
  };
  current.onmessage = event => {
    if (socket !== current) return;
    lastMessage = Date.now();
    try {
      const value: unknown = JSON.parse(event.data);
      if (!value || typeof value !== 'object') return;
      const root = value as Record<string, unknown>;
      const nested = root.data && typeof root.data === 'object' ? root.data as Record<string, unknown> : {};
      if (!acceptRightsRevision(root.rights_revision ?? nested.rights_revision, 'socket')) return;
      [...listeners].forEach(listener => listener.message?.(value));
    } catch { /* A malformed packet cannot create another connection. */ }
  };
  current.onerror = () => current.close();
  current.onclose = () => {
    if (socket !== current) return;
    socket = null; publish('fallback');
    scheduleRetry();
  };
}
function online(): void { if (!socket) connect(); }
function offline(): void { publish('fallback'); socket?.close(); }
export function subscribePricesConnection(listener: Listener): () => void {
  listeners.add(listener); listener.status?.(status);
  if (!installed) {
    installed = true;
    window.addEventListener('online', online); window.addEventListener('offline', offline);
    watchdog = setInterval(() => {
      const timeout = Math.max(Number(import.meta.env.VITE_WS_HEARTBEAT_TIMEOUT_MS) || 45_000, 15_000);
      if (socket?.readyState === WebSocket.OPEN && Date.now() - lastMessage > timeout) socket.close();
      else if (socket && socket.readyState !== WebSocket.OPEN && Date.now() - connectedAt > timeout) {
        const stale = socket; socket = null; stale.close(); publish('fallback'); scheduleRetry();
      }
    }, 5_000);
  }
  connect();
  return () => {
    listeners.delete(listener);
    if (listeners.size) return;
    clearTimeout(retry); clearInterval(watchdog); retry = undefined; watchdog = undefined;
    const previous = socket; socket = null; previous?.close(); retries = 0; status = 'fallback';
    window.removeEventListener('online', online); window.removeEventListener('offline', offline); installed = false;
  };
}
