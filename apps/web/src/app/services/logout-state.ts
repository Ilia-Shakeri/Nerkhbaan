export const LOGOUT_PENDING_KEY = 'nerkhbaan-logout-pending';
const LOGOUT_EVENT = 'logout-state-changed';
let pending = false;
let attempting = false;
let generation = 0;

const urlIsPending = () => new URLSearchParams(window.location.search).get('signout') === 'pending'
  || new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('signout') === 'pending';

export const logoutAuthPath = () => logoutIsPending() ? '/auth?signout=pending' : '/auth';

function updateUrl(success: boolean): void {
  const url = new URL(window.location.href);
  if (success) {
    url.searchParams.delete('signout');
    const [route, search] = url.hash.split('?');
    if (search) {
      const params = new URLSearchParams(search);
      params.delete('signout');
      url.hash = `${route}${params.size ? `?${params}` : ''}`;
    }
  } else url.searchParams.set('signout', 'pending');
  window.history.replaceState(window.history.state, '', url);
}

export function logoutIsPending(): boolean {
  if (pending) return true;
  if (urlIsPending()) return true;
  try { if (localStorage.getItem(LOGOUT_PENDING_KEY) === '1') return true; } catch { /* Cookie fallback remains available. */ }
  try { return document.cookie.split(';').some(item => item.trim() === `${LOGOUT_PENDING_KEY}=1`); } catch { return false; }
}

export const logoutGeneration = () => generation;
export const getLogoutStatus = (): 'idle' | 'pending' | 'failed' => logoutIsPending() ? attempting ? 'pending' : 'failed' : 'idle';

export function beginLogout(): void {
  pending = true;
  attempting = true;
  generation++;
  updateUrl(false);
  try { localStorage.setItem(LOGOUT_PENDING_KEY, '1'); } catch { /* First-party cookies also preserve the lock across reloads. */ }
  try { document.cookie = `${LOGOUT_PENDING_KEY}=1; Path=/; Max-Age=31536000; SameSite=Strict`; } catch { /* The in-memory lock still applies to this page. */ }
  window.dispatchEvent(new Event(LOGOUT_EVENT));
}

export function finishLogout(success: boolean): void {
  attempting = false;
  if (success) {
    pending = false;
    try { localStorage.removeItem(LOGOUT_PENDING_KEY); } catch { /* Cookie fallback is cleared below. */ }
    try { document.cookie = `${LOGOUT_PENDING_KEY}=; Path=/; Max-Age=0; SameSite=Strict`; } catch { /* Storage can be disabled. */ }
    updateUrl(true);
  }
  window.dispatchEvent(new Event(LOGOUT_EVENT));
}

export function subscribeLogoutStatus(listener: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key !== LOGOUT_PENDING_KEY && event.key !== null) return;
    pending = event.newValue === '1';
    attempting = false;
    generation++;
    listener();
  };
  window.addEventListener(LOGOUT_EVENT, listener);
  window.addEventListener('storage', onStorage);
  window.addEventListener('focus', listener);
  return () => {
    window.removeEventListener(LOGOUT_EVENT, listener);
    window.removeEventListener('storage', onStorage);
    window.removeEventListener('focus', listener);
  };
}
