import { useState } from 'react';
import { useAppContext } from '../context/AppContext';
import { apiInstance } from '../services/api';

export function LocalPreviewNotice() {
  const { language, isAuthenticated } = useAppContext();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const local = ['127.0.0.1', 'localhost', '[::1]'].includes(window.location.hostname);
  if (!import.meta.env.DEV || import.meta.env.VITE_LOCAL_PREVIEW !== 'true' || !local) return null;
  const fa = language === 'fa';
  const notice = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await apiInstance.post('local-preview/notice', {});
      setMessage(fa ? 'پیام نمونه ثبت شد؛ زنگ اعلان را باز کنید.' : 'Sample message saved. Open the notification bell.');
      window.dispatchEvent(new Event('focus'));
    } catch {
      setMessage(fa ? 'ثبت پیام نمونه انجام نشد؛ دوباره تلاش کنید.' : 'Could not save the sample message. Try again.');
    } finally {
      setBusy(false);
    }
  };
  return <aside aria-label={fa ? 'نسخهٔ محلی' : 'Local preview'} className="shrink-0 border-b border-amber-500/30 bg-amber-50 px-4 py-3 text-sm text-amber-950" dir={fa ? 'rtl' : 'ltr'}>
    <p className="font-bold">{fa ? 'مرور محلی نرخ‌بان' : 'Nerkhbaan local preview'}</p>
    <p>{fa ? 'نرخ و نمودار نمونه‌اند؛ حساب و هشدار فقط روی این رایانه ذخیره می‌شوند. پیام بیرونی ارسال نمی‌شود.' : 'Rates and charts are synthetic. Accounts and alerts stay on this computer. No external messages are sent.'}</p>
    {isAuthenticated && <button type="button" disabled={busy} onClick={() => { void notice(); }} className="mt-2 min-h-11 rounded-lg border border-amber-700 px-3 font-semibold disabled:opacity-50">{fa ? 'ثبت اعلان نمونه در برنامه' : 'Add sample in-app notification'}</button>}
    {message && <p role="status" className="mt-1">{message}</p>}
  </aside>;
}
