import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, CheckCircle2, Languages, LifeBuoy, Loader2, Mail, Moon, Repeat, Send, ShieldCheck, Smartphone, Sun, VolumeX } from 'lucide-react';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { Switch } from '@nerkhbaan/ui/app/components/ui/switch';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { toast } from 'sonner';
import { useAppContext } from '../context/AppContext';
import { api, type NotificationPreferences, type TelegramDeepLink } from '../services/api';

const emptyPreferences: NotificationPreferences = {
  push_app: false,
  sms_enabled: false,
  sms_phone: null,
  sms_verified: false,
  email_enabled: false,
  email_address: null,
  email_verified: false,
  telegram_enabled: false,
  telegram_id: null,
  telegram_verified: false,
  silent_mode: false,
  aggressive_alerts: false,
  push_available: false,
  email_available: false,
  sms_available: false,
  telegram_available: false,
  telegram_deeplink_available: false,
};

type VerifyChannel = 'sms' | 'email';

export function SettingsView() {
  const navigate = useNavigate();
  const { language, theme, toggleLanguage, toggleTheme } = useAppContext();
  const isDark = theme === 'dark';
  const [prefs, setPrefs] = useState<NotificationPreferences>(emptyPreferences);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [verifyChannel, setVerifyChannel] = useState<VerifyChannel | null>(null);
  const [destination, setDestination] = useState('');
  const [code, setCode] = useState('');
  const [codeSent, setCodeSent] = useState(false);
  const [telegramId, setTelegramId] = useState('');
  const [telegramCode, setTelegramCode] = useState('');
  const [telegramCodeSent, setTelegramCodeSent] = useState(false);
  const [telegramLink, setTelegramLink] = useState<TelegramDeepLink | null>(null);

  const t = {
    general: { fa: 'عمومی', en: 'General' },
    notifications: { fa: 'اطلاع‌رسانی', en: 'Notifications' },
    behavior: { fa: 'رفتار هشدار', en: 'Alert behavior' },
    dark: { fa: 'حالت تاریک', en: 'Dark theme' },
    language: { fa: 'زبان برنامه', en: 'App language' },
    push: { fa: 'اعلان درون برنامه', en: 'In-app notifications' },
    sms: { fa: 'پیامک', en: 'SMS' },
    email: { fa: 'ایمیل', en: 'Email' },
    telegram: { fa: 'تلگرام', en: 'Telegram' },
    telegramLinkHelp: { fa: 'ربات را باز کنید و دکمه شروع را بزنید. این صفحه خودکار بررسی می‌شود.', en: 'Open the bot and press Start. This page will check automatically.' },
    openTelegram: { fa: 'باز کردن ربات', en: 'Open bot' },
    silent: { fa: 'حالت بی‌صدا', en: 'Silent mode' },
    repeat: { fa: 'هشدار مکرر', en: 'Recurring alerts' },
    verified: { fa: 'تأیید شده', en: 'Verified' },
    unverified: { fa: 'تأیید نشده', en: 'Not verified' },
    configure: { fa: 'تنظیم', en: 'Configure' },
    disable: { fa: 'غیرفعال', en: 'Disable' },
    send: { fa: 'ارسال کد', en: 'Send code' },
    confirm: { fa: 'تأیید', en: 'Confirm' },
    cancel: { fa: 'انصراف', en: 'Cancel' },
    support: { fa: 'پشتیبانی', en: 'Support' },
    privacy: { fa: 'حریم خصوصی', en: 'Privacy' },
  };

  useEffect(() => {
    let active = true;
    api.notifications.preferences()
      .then((value) => {
        if (active) {
          setPrefs(value);
          setTelegramId(value.telegram_id ?? '');
        }
      })
      .catch((error) => toast.error(error instanceof Error ? error.message : 'Failed to load settings'))
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!telegramLink || prefs.telegram_verified) return;
    let active = true;
    const poll = async () => {
      if (Date.now() >= Date.parse(telegramLink.expires_at)) {
        if (active) setTelegramLink(null);
        return;
      }
      try {
        const value = await api.notifications.preferences();
        if (!active) return;
        setPrefs(value);
        if (value.telegram_verified) {
          setTelegramLink(null);
          toast.success(t.verified[language]);
        }
      } catch {
        // A later poll can recover from a short route failure.
      }
    };
    const timer = window.setInterval(() => void poll(), 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [language, prefs.telegram_verified, telegramLink]);

  const setBasic = async (key: 'push_app' | 'silent_mode' | 'aggressive_alerts', enabled: boolean) => {
    const previous = prefs;
    setPrefs((current) => ({ ...current, [key]: enabled }));
    try {
      setPrefs(await api.notifications.setBasic(key, enabled));
    } catch (error) {
      setPrefs(previous);
      toast.error(error instanceof Error ? error.message : 'Failed to save setting');
    }
  };

  const disableChannel = async (channel: VerifyChannel | 'telegram') => {
    try {
      setPrefs(await api.notifications.disable(channel));
      if (channel === 'telegram') {
        setTelegramLink(null);
        setTelegramCodeSent(false);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to disable channel');
    }
  };

  const createTelegramLink = async () => {
    setIsSaving(true);
    try {
      setTelegramLink(await api.notifications.createTelegramDeepLink());
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to create Telegram link');
    } finally {
      setIsSaving(false);
    }
  };

  const openTelegramLink = async () => {
    if (!telegramLink) return;
    const opened = await window.electronAPI?.openTelegramLink(telegramLink.url);
    if (!opened) toast.error('Telegram link could not be opened');
  };

  const startVerification = async () => {
    if (!verifyChannel || !destination.trim()) return;
    setIsSaving(true);
    try {
      await api.notifications.startOtp(verifyChannel, destination.trim());
      setCodeSent(true);
      toast.success(language === 'fa' ? 'کد ارسال شد' : 'Verification code sent');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Channel is unavailable');
    } finally {
      setIsSaving(false);
    }
  };

  const confirmVerification = async () => {
    if (!verifyChannel || !destination.trim() || !code.trim()) return;
    setIsSaving(true);
    try {
      setPrefs(await api.notifications.confirmOtp(verifyChannel, destination.trim(), code.trim()));
      setVerifyChannel(null);
      setDestination('');
      setCode('');
      setCodeSent(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Verification failed');
    } finally {
      setIsSaving(false);
    }
  };

  const saveTelegram = async () => {
    if (!telegramId.trim()) return;
    setIsSaving(true);
    try {
      setPrefs(await api.notifications.setTelegram(telegramId.trim()));
      setTelegramCodeSent(true);
      toast.success(language === 'fa' ? 'کد تأیید ارسال شد' : 'Verification code sent');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Telegram is unavailable');
    } finally {
      setIsSaving(false);
    }
  };

  const confirmTelegram = async () => {
    if (!/^\d{6}$/.test(telegramCode.trim())) return;
    setIsSaving(true);
    try {
      setPrefs(await api.notifications.confirmTelegram(telegramCode.trim()));
      setTelegramCode('');
      setTelegramCodeSent(false);
      toast.success(t.verified[language]);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Verification failed');
    } finally {
      setIsSaving(false);
    }
  };

  const heading = 'mb-4 flex items-center gap-2 text-xl font-bold tracking-tight text-[#0B1F3A] dark:text-white';
  const row = 'flex items-center justify-between gap-4 p-5';

  if (isLoading) return <div className="flex min-h-64 items-center justify-center"><Loader2 className="animate-spin text-[#D4AF37]" /></div>;

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <section>
        <h2 className={heading}><Sun className="text-[#D4AF37]" size={22} />{t.general[language]}</h2>
        <Card className="divide-y divide-slate-100 dark:divide-white/5">
          <div className={row}>
            <div className="flex items-center gap-3"><Moon size={20} /><span className="font-semibold">{t.dark[language]}</span></div>
            <Switch checked={isDark} onCheckedChange={toggleTheme} />
          </div>
          <button type="button" onClick={toggleLanguage} className={`${row} w-full text-start`}>
            <div className="flex items-center gap-3"><Languages size={20} /><span className="font-semibold">{t.language[language]}</span></div>
            <span className="text-sm text-[#D4AF37]">{language === 'fa' ? 'English' : 'فارسی'}</span>
          </button>
        </Card>
      </section>

      <section>
        <h2 className={heading}><Bell className="text-[#D4AF37]" size={22} />{t.notifications[language]}</h2>
        <Card className="divide-y divide-slate-100 dark:divide-white/5">
          <div className={row}>
            <div className="flex items-center gap-3"><Bell size={20} /><span className="font-semibold">{t.push[language]}</span></div>
            <Switch disabled={!prefs.push_available} checked={prefs.push_available && prefs.push_app} onCheckedChange={(value) => void setBasic('push_app', value)} />
          </div>
          {(['email', 'sms'] as const).map((channel) => {
            const enabled = channel === 'email' ? prefs.email_enabled : prefs.sms_enabled;
            const verified = channel === 'email' ? prefs.email_verified : prefs.sms_verified;
            const value = channel === 'email' ? prefs.email_address : prefs.sms_phone;
            const Icon = channel === 'email' ? Mail : Smartphone;
            return (
              <div key={channel} className={row}>
                <div className="flex items-center gap-3">
                  <Icon size={20} />
                  <div><div className="font-semibold">{t[channel][language]}</div><div className="text-xs text-slate-500" dir="ltr">{value ?? t.unverified[language]}</div></div>
                </div>
                <Button variant="ghost" disabled={channel === 'email' ? !prefs.email_available : !prefs.sms_available} onClick={() => enabled ? void disableChannel(channel) : setVerifyChannel(channel)}>
                  {enabled && verified ? t.disable[language] : t.configure[language]}
                </Button>
              </div>
            );
          })}
          <div className={`${row} flex-wrap`}>
            <div className="flex items-center gap-3"><Send size={20} /><div><div className="font-semibold">{t.telegram[language]}</div><div className="text-xs text-slate-500">{prefs.telegram_verified ? t.verified[language] : t.unverified[language]}</div></div></div>
            <div className="flex gap-2">
              {!prefs.telegram_deeplink_available && <Input disabled={!prefs.telegram_available} value={telegramId} onChange={(event) => setTelegramId(event.target.value)} placeholder="@username" dir="ltr" className="w-40" />}
              <Button variant="ghost" disabled={isSaving || !prefs.telegram_available} onClick={() => prefs.telegram_enabled || telegramLink ? void disableChannel('telegram') : prefs.telegram_deeplink_available ? void createTelegramLink() : void saveTelegram()}>{prefs.telegram_enabled || telegramLink ? t.disable[language] : t.configure[language]}</Button>
            </div>
            {telegramLink && !prefs.telegram_verified && <div className="flex w-full flex-col gap-3 sm:flex-row sm:items-center sm:justify-end" aria-live="polite"><span className="text-sm text-slate-500">{t.telegramLinkHelp[language]}</span><Button variant="primary" onClick={() => void openTelegramLink()}>{t.openTelegram[language]}</Button></div>}
            {!prefs.telegram_deeplink_available && telegramCodeSent && <div className="flex w-full justify-end gap-2"><Input value={telegramCode} onChange={(event) => setTelegramCode(event.target.value)} placeholder="123456" dir="ltr" className="w-40" /><Button variant="primary" disabled={isSaving || !/^\d{6}$/.test(telegramCode)} onClick={() => void confirmTelegram()}>{t.confirm[language]}</Button></div>}
          </div>
        </Card>
      </section>

      {verifyChannel && (
        <Card className="space-y-3 border-[#D4AF37]/30 p-5">
          <div className="font-semibold">{t[verifyChannel][language]}</div>
          <Input value={destination} onChange={(event) => setDestination(event.target.value)} dir="ltr" placeholder={verifyChannel === 'email' ? 'name@example.com' : '+989121234567'} />
          {codeSent && <Input value={code} onChange={(event) => setCode(event.target.value)} dir="ltr" placeholder="123456" />}
          <div className="flex gap-2"><Button variant="primary" disabled={isSaving} onClick={() => void (codeSent ? confirmVerification() : startVerification())}>{codeSent ? t.confirm[language] : t.send[language]}</Button><Button variant="ghost" onClick={() => setVerifyChannel(null)}>{t.cancel[language]}</Button></div>
        </Card>
      )}

      <section>
        <h2 className={heading}><Repeat className="text-[#D4AF37]" size={22} />{t.behavior[language]}</h2>
        <Card className="divide-y divide-slate-100 dark:divide-white/5">
          <div className={row}><div className="flex items-center gap-3"><VolumeX size={20} /><span className="font-semibold">{t.silent[language]}</span></div><Switch checked={prefs.silent_mode} onCheckedChange={(value) => void setBasic('silent_mode', value)} /></div>
          <div className={row}><div className="flex items-center gap-3"><Repeat size={20} /><span className="font-semibold">{t.repeat[language]}</span></div><Switch checked={prefs.aggressive_alerts} onCheckedChange={(value) => void setBasic('aggressive_alerts', value)} /></div>
        </Card>
      </section>

      <section>
        <h2 className={heading}><LifeBuoy className="text-[#D4AF37]" size={22} />{t.support[language]}</h2>
        <Card className="divide-y divide-slate-100 dark:divide-white/5"><button className={`${row} w-full text-start`} onClick={() => navigate('/support')}><LifeBuoy size={20} /><span className="flex-1 font-semibold">{t.support[language]}</span></button><button className={`${row} w-full text-start`} onClick={() => navigate('/privacy')}><ShieldCheck size={20} /><span className="flex-1 font-semibold">{t.privacy[language]}</span></button></Card>
      </section>
    </div>
  );
}
