import { disablePushNotifications } from '@/pwa/push';
import { api } from './api';
import { beginLogout, finishLogout } from './logout-state';

let request: Promise<void> | null = null;

export function requestLogout(): Promise<void> {
  if (request) return request;
  beginLogout();
  request = (async () => {
    let cleanupFailed = false;
    await api.auth.signout(async () => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        await Promise.race([
          disablePushNotifications(),
          new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('Notification cleanup timed out')), 4000); }),
        ]);
      } catch { cleanupFailed = true; }
      finally { clearTimeout(timer); }
    });
    if (cleanupFailed) throw new Error('Notification cleanup needs another attempt');
    finishLogout(true);
  })().catch(error => {
    finishLogout(false);
    throw error;
  }).finally(() => { request = null; });
  return request;
}
