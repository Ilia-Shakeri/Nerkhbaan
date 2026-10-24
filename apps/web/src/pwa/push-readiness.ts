export type PushReadiness = 'insecure' | 'install' | 'unsupported' | 'denied' | 'unconfigured' | 'ready';

export function pushReadiness(configured: boolean, supported: boolean): PushReadiness {
  if (!window.isSecureContext) return 'insecure';
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const standalone = window.matchMedia?.('(display-mode: standalone)').matches ||
    Boolean((navigator as Navigator & { standalone?: boolean }).standalone);
  // Device detection only supplies installation help; capability checks decide support.
  if (ios && !standalone) return 'install';
  if (!supported) return 'unsupported';
  if (Notification.permission === 'denied') return 'denied';
  if (!configured) return 'unconfigured';
  return 'ready';
}

export function pushReadinessText(state: PushReadiness, active: boolean, language: 'fa' | 'en'): string {
  const text = {
    insecure: { fa: 'برای اعلان، سایت را با HTTPS باز کنید.', en: 'Open this site over HTTPS to enable notifications.' },
    install: { fa: 'در آیفون و آیپد با نسخه ۱۶.۴ یا بالاتر، از Safari گزینه اشتراک‌گذاری و «افزودن به صفحه اصلی» را بزنید؛ سپس برنامه را از همان نشان باز کنید.', en: 'On iOS or iPadOS 16.4 or later, use Safari → Share → Add to Home Screen, then open the app from that icon.' },
    unsupported: { fa: 'این مرورگر اعلان وب را پشتیبانی نمی‌کند؛ مرورگر به‌روز و خارج از پیام‌رسان را باز کنید.', en: 'This browser does not support web push. Use an up-to-date browser outside your messaging app.' },
    denied: { fa: 'اعلان این سایت بسته است؛ از تنظیمات سایت در مرورگر اجازه اعلان بدهید و به این صفحه برگردید.', en: 'Notifications are blocked. Allow them in browser site settings, then return here.' },
    unconfigured: { fa: 'اعلان وب در خدمت آماده نیست؛ با مدیر تماس بگیرید.', en: 'Web notifications are not configured. Contact the administrator.' },
    ready: active
      ? { fa: 'این مرورگر ثبت شده است. دریافت به اینترنت، دسترسی اعلان دستگاه و خدمت ارسال وابسته است؛ ثبت، رسید دریافت نیست.', en: 'This browser is registered. Delivery needs connectivity, device permission and the push service; registration is not a delivery receipt.' }
      : { fa: 'اعلان وب را روشن کنید و اجازه مرورگر را بدهید. در هر دستگاه جدا روشن شود.', en: 'Turn on web notifications and allow the browser prompt. Enable separately on each device.' },
  };
  return text[state][language];
}
