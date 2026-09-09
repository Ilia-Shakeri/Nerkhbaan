import { registerSW } from "virtual:pwa-register";

let applyUpdate: ((reload?: boolean) => Promise<void>) | null = null;

/**
 * Register the service worker without taking over the running page.
 *
 * `skipWaiting` plus `clientsClaim` swapped the worker underneath an open
 * session, so a deploy made the already-loaded page request chunk hashes that
 * no longer existed. The new worker now waits until the user acts on it.
 */
export function registerServiceWorker() {
  applyUpdate = registerSW({
    immediate: true,
    onNeedRefresh() {
      window.dispatchEvent(new Event("app-update-available"));
    },
  });
}

/** Activate a waiting worker and reload. Triggered from the update prompt. */
export async function applyPendingUpdate(): Promise<void> {
  if (!applyUpdate) {
    window.location.reload();
    return;
  }
  await applyUpdate(true);
}
