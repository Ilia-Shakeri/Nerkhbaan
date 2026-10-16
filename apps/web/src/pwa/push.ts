import { apiInstance } from "@/app/services/api";

import { logoutGeneration, logoutIsPending } from '@/app/services/logout-state';

const subscriptionWrites = new Set<Promise<unknown>>();

async function writeSubscription(subscription: PushSubscription, generation: number): Promise<void> {
  if (logoutIsPending() || generation !== logoutGeneration()) return;
  const request = apiInstance.post('push/subscribe', subscription.toJSON());
  subscriptionWrites.add(request);
  try { await request; }
  finally { subscriptionWrites.delete(request); }
}

function base64ToUint8Array(base64String: string) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
}

export function pushIsConfigured(): boolean {
  return Boolean(import.meta.env.VITE_VAPID_PUBLIC_KEY);
}

export function pushIsSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    !window.electronAPI &&
    "Notification" in window &&
    "PushManager" in window &&
    "serviceWorker" in navigator
  );
}

async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (!pushIsSupported()) return null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const existing = await navigator.serviceWorker.getRegistration();
    if (!existing) return null;
    return await Promise.race([
      navigator.serviceWorker.ready,
      new Promise<null>(resolve => { timer = setTimeout(() => resolve(null), 3000); }),
    ]);
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export async function hasPushSubscription(): Promise<boolean> {
  if (!pushIsConfigured() || !pushIsSupported() || Notification.permission !== "granted") return false;
  const worker = await registration();
  return Boolean(worker && await worker.pushManager.getSubscription());
}

/**
 * Send the current browser subscription to the API.
 *
 * Called after sign-in as well as on first grant: a subscription created while
 * signed out is stored with no user attached, and without re-sending it after
 * authentication the account never receives a push.
 */
export async function syncPushSubscription(): Promise<void> {
  if (!pushIsConfigured() || logoutIsPending()) return;
  const generation = logoutGeneration();
  const worker = await registration();
  if (!worker) return;
  const existing = await worker.pushManager.getSubscription();
  if (!existing) return;
  try {
    await writeSubscription(existing, generation);
  } catch {
    // A failed sync is retried the next time the app starts.
  }
}

/**
 * Ask for notification permission and subscribe.
 *
 * Deliberately not called on load: prompting an anonymous visitor before they
 * have asked for alerts is how browsers end up blocking the prompt outright.
 */
export async function enablePushNotifications(): Promise<boolean> {
  if (!pushIsConfigured() || !pushIsSupported() || logoutIsPending()) return false;
  const generation = logoutGeneration();

  const permission = await Notification.requestPermission();
  if (permission !== "granted" || logoutIsPending() || generation !== logoutGeneration()) return false;

  const worker = await registration();
  if (!worker || logoutIsPending() || generation !== logoutGeneration()) return false;

  const vapidPublicKey = import.meta.env.VITE_VAPID_PUBLIC_KEY as string;
  const subscription =
    (await worker.pushManager.getSubscription()) ||
    (await worker.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: base64ToUint8Array(vapidPublicKey),
    }));

  if (logoutIsPending() || generation !== logoutGeneration()) return false;
  await writeSubscription(subscription, generation);
  return true;
}

/**
 * Detach this browser from the account on sign-out.
 *
 * Without this the endpoint stays bound to the previous user, so the next
 * person to use the device inherits their alerts.
 */
export async function disablePushNotifications(): Promise<void> {
  // Finish writes already sent before deleting their endpoint. New writes are
  // blocked by the logout marker, including a late startup subscription read.
  await Promise.allSettled([...subscriptionWrites]);
  const worker = await registration();
  if (!worker) return;
  const subscription = await worker.pushManager.getSubscription();
  if (!subscription) return;
  const endpoint = subscription.endpoint;
  const results = await Promise.allSettled([
    subscription.unsubscribe(),
    apiInstance.post('push/unsubscribe', { endpoint }),
  ]);
  if (results[1].status === 'fulfilled') return;
  if (results[0].status === 'fulfilled' && (results[0].value === true || !await worker.pushManager.getSubscription())) return;
  throw new Error('Notification cleanup failed');
}
