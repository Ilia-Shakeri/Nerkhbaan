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
    denylist: [/^\/api\//],
  }),
);

// A generated Workbox worker has no push listener, so every web push arrived
// as the browser's generic "site updated in the background" notice and the
// server-supplied title, body and silent flag were discarded.
self.addEventListener("push", (event: PushEvent) => {
  let payload: PushPayload = {};
  try {
    payload = (event.data?.json() ?? {}) as PushPayload;
  } catch {
    payload = { body: event.data?.text() };
  }

  const title = payload.title || "Nerkhbaan";
  const options: NotificationOptions & { renotify?: boolean } = {
    body: payload.body || "",
    // userVisibleOnly subscriptions must show something; keep it silent
    // rather than skipping the notification when the user asked for quiet.
    silent: Boolean(payload.silent),
    tag: payload.asset ? `nerkhbaan-${payload.asset}` : "nerkhbaan",
    // Replaces an earlier alert for the same asset instead of stacking, and
    // still vibrates. Not yet in the bundled DOM typings.
    renotify: true,
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    data: { url: payload.url || "/" },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event: NotificationEvent) => {
  event.notification.close();
  const target = (event.notification.data?.url as string) || "/";
  event.waitUntil(
    (async () => {
      const clientList = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });
      for (const client of clientList) {
        if ("focus" in client) {
          await client.focus();
          if ("navigate" in client) {
            await client.navigate(target);
          }
          return;
        }
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
