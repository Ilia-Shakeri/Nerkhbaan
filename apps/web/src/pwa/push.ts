import { apiInstance } from "@/app/services/api";

function base64ToUint8Array(base64String: string) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
}

export function pushIsConfigured(): boolean {
  return Boolean(import.meta.env.VITE_VAPID_PUBLIC_KEY);
}

function pushIsSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "Notification" in window &&
    "PushManager" in window &&
    "serviceWorker" in navigator
  );
}

async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (!pushIsSupported()) return null;
  try {
    return await navigator.serviceWorker.ready;
  } catch {
    return null;
  }
}

/**
 * Send the current browser subscription to the API.
 *
 * Called after sign-in as well as on first grant: a subscription created while
 * signed out is stored with no user attached, and without re-sending it after
 * authentication the account never receives a push.
 */
export async function syncPushSubscription(): Promise<void> {
  if (!pushIsConfigured()) return;
  const worker = await registration();
  if (!worker) return;
  const existing = await worker.pushManager.getSubscription();
  if (!existing) return;
  try {
    await apiInstance.post("push/subscribe", existing.toJSON());
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
  if (!pushIsConfigured() || !pushIsSupported()) return false;

  const permission = await Notification.requestPermission();
  if (permission !== "granted") return false;

  const worker = await registration();
  if (!worker) return false;

  const vapidPublicKey = import.meta.env.VITE_VAPID_PUBLIC_KEY as string;
  const subscription =
    (await worker.pushManager.getSubscription()) ||
    (await worker.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: base64ToUint8Array(vapidPublicKey),
    }));

  await apiInstance.post("push/subscribe", subscription.toJSON());
  return true;
}

/**
 * Detach this browser from the account on sign-out.
 *
 * Without this the endpoint stays bound to the previous user, so the next
 * person to use the device inherits their alerts.
 */
export async function disablePushNotifications(): Promise<void> {
  const worker = await registration();
  if (!worker) return;
  const subscription = await worker.pushManager.getSubscription();
  if (!subscription) return;
  const endpoint = subscription.endpoint;
  try {
    await subscription.unsubscribe();
  } catch {
    // Continue: the server record still has to be released.
  }
  try {
    await apiInstance.post("push/unsubscribe", { endpoint });
  } catch {
    // Best effort; the endpoint is already dead from the browser's side.
  }
}
