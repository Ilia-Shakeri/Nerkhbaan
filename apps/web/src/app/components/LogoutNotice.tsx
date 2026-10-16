import { useEffect, useState, useSyncExternalStore } from 'react';
import { readPreference } from '../legal/storage';
import { requestLogout } from '../services/logout';
import { getLogoutStatus, subscribeLogoutStatus } from '../services/logout-state';

export function LogoutNotice() {
  const status = useSyncExternalStore(subscribeLogoutStatus, getLogoutStatus);
  const [language, setLanguage] = useState(() => readPreference('language') ?? document.documentElement.lang);
  useEffect(() => {
    const observer = new MutationObserver(() => setLanguage(document.documentElement.lang));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    return () => observer.disconnect();
  }, []);
  if (status === 'idle') return null;
  const persian = language === 'fa';
  return (
    <aside role="alert" aria-label={persian ? 'خروج کامل نشده' : 'Sign-out incomplete'} dir={persian ? 'rtl' : 'ltr'} className="fixed inset-x-4 bottom-4 z-[120] mx-auto max-w-xl rounded-2xl border border-amber-400 bg-[#191309] p-4 text-[#FFF1C8] shadow-xl">
      <p className="font-bold">{persian ? 'خروج کامل نشده' : 'Sign-out incomplete'}</p>
      <p className="mt-1 text-sm leading-6">{persian ? 'حساب روی این صفحه بسته است. خروج سرور یا قطع اعلان هنوز تأیید نشده. پیش از ورود دوباره یا دادن دستگاه به فرد دیگر، خروج را دوباره انجام دهید.' : 'This page is signed out. Server sign-out or notification cleanup is still unconfirmed. Retry before signing in again or sharing this device.'}</p>
      <button type="button" disabled={status === 'pending'} aria-busy={status === 'pending'} onClick={() => { void requestLogout().catch(() => undefined); }} className="mt-3 min-h-11 rounded-xl bg-[#D4AF37] px-4 py-2 font-bold text-black disabled:opacity-60">
        {status === 'pending' ? persian ? 'در حال خروج…' : 'Signing out…' : persian ? 'تلاش دوباره برای خروج' : 'Retry sign-out'}
      </button>
    </aside>
  );
}
