import { registerSW } from "virtual:pwa-register";
import { registerPushNotifications } from "@/pwa/push";

export function registerServiceWorker() {
  registerSW({
    immediate: true,
    onRegisteredSW: async (_swUrl, registration) => {
      if (!registration) {
        return;
      }

      try {
        await registerPushNotifications(registration);
      } catch {
        return;
      }
    }
  });
}
