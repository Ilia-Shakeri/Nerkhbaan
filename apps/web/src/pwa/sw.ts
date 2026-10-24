/// <reference lib="webworker" />
import { cleanupOutdatedCaches, precacheAndRoute } from "workbox-precaching";
import { NavigationRoute, registerRoute } from "workbox-routing";
import { createHandlerBoundToURL } from "workbox-precaching";

declare const self: ServiceWorkerGlobalScope;

type PushPayload = {
  title?: string;
  body?: string;
  asset?: string;
  silent?: boolean;
  url?: string;
};

// Injected by vite-plugin-pwa (injectManifest strategy).
precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();

registerRoute(
  new NavigationRoute(createHandlerBoundToURL("index.html"), {
    // The admin panel is a separate application on the same origin.
    denylist: [/^\/api\//, /^\/admin(?:\/|$)/],
  }),
);

// A generated Workbox worker has no push listener, so every web push arrived
// as the browser's generic "site updated in the background" notice and the
// server-supplied title, body and silent flag were discarded.
self.addEventListener("push", (event: PushEvent) => {
  let payload: PushPayload = {};
  try {
    const data: unknown = event.data?.json();
    if (data && typeof data === 'object' && !Array.isArray(data)) payload = data as PushPayload;
  } catch {
    payload = { body: event.data?.text() };
  }

  const title = typeof payload.title === 'string' && payload.title ? payload.title : "Nerkhbaan";
  const options: NotificationOptions & { renotify?: boolean } = {
    body: typeof payload.body === 'string' ? payload.body : "",
    // userVisibleOnly subscriptions must show something; keep it silent
    // rather than skipping the notification when the user asked for quiet.
    silent: payload.silent === true,
    tag: typeof payload.asset === 'string' && payload.asset ? `nerkhbaan-${payload.asset}` : "nerkhbaan",
    // Replaces an earlier alert for the same asset instead of stacking, and
    // still vibrates. Not yet in the bundled DOM typings.
    renotify: true,
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    data: { url: notificationTarget(payload.url) },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

function notificationTarget(value: unknown): string {
  try {
    const target = new URL(typeof value === 'string' ? value : '/', self.location.origin);
    if (target.origin === self.location.origin && !target.username && !target.password &&
        !/^\/(?:admin|api)(?:\/|$)/i.test(decodeURIComponent(target.pathname))) return target.href;
  } catch { /* Malformed targets fall back to the public application. */ }
  return `${self.location.origin}/`;
}

self.addEventListener("notificationclick", (event: NotificationEvent) => {
  event.notification.close();
  const target = notificationTarget(event.notification.data?.url);
  event.waitUntil(
    (async () => {
      const clientList = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });
      for (const client of clientList) {
        // Leave the separate admin application and other tabs in place.
        if (notificationTarget(client.url) !== client.url || !('navigate' in client)) continue;
        try {
          const navigated = await client.navigate(target);
          if (navigated) { await navigated.focus(); return; }
        } catch { /* Try another client or open a new window. */ }
      }
      await self.clients.openWindow(target);
    })(),
  );
});

// The page decides when a new worker takes over, so an update cannot swap
// chunk hashes underneath a session that is already running.
self.addEventListener("message", (event: ExtendableMessageEvent) => {
  if (event.data?.type === "SKIP_WAITING") {
    void self.skipWaiting();
  }
});
