import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import { Activity, Bell, CheckCircle2, Languages, LifeBuoy, Mail, Moon, Repeat, Send, ShieldCheck, Smartphone, Sun, VolumeX } from 'lucide-react';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { Switch } from '@nerkhbaan/ui/app/components/ui/switch';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { useAppContext } from '../context/AppContext';
import { api, type NotificationPreferences, type TelegramDeepLink } from '../services/api';
import { toast } from 'sonner';

type OtpPanel = 'sms' | 'email' | null;

const emptyPrefs: NotificationPreferences = {
  push_app: true,
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

export function SettingsView() {
  const navigate = useNavigate();
  const { language, theme, toggleTheme, toggleLanguage } = useAppContext();
  const isDark = theme === 'dark';

  const [prefs, setPrefs] = useState<NotificationPreferences>(emptyPrefs);
  const [otpPanel, setOtpPanel] = useState<OtpPanel>(null);
  const [otpDestination, setOtpDestination] = useState('');
  const [otpCode, setOtpCode] = useState('');
  const [otpSent, setOtpSent] = useState(false);
  const [telegramId, setTelegramId] = useState('');
  const [telegramCode, setTelegramCode] = useState('');
  const [telegramCodeSent, setTelegramCodeSent] = useState(false);
  const [telegramLink, setTelegramLink] = useState<TelegramDeepLink | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const t = {
    general: { fa: 'عمومی', en: 'General' },
    notifications: { fa: 'اطلاع‌رسانی', en: 'Notifications' },
    behavior: { fa: 'رفتار برنامه', en: 'Behavior' },
    support: { fa: 'پشتیبانی', en: 'Support' },
    darkTheme: { fa: 'حالت تاریک', en: 'Dark Theme' },
    darkThemeSub: { fa: 'تغییر ظاهر برنامه به حالت شب', en: 'Switch to night appearance' },
    languageSet: { fa: 'زبان برنامه', en: 'App Language' },
    pushApp: { fa: 'اعلان درون‌برنامه‌ای', en: 'In-App Notifications' },
    sms: { fa: 'پیامک', en: 'SMS' },
    email: { fa: 'ایمیل', en: 'Email' },
    telegram: { fa: 'ربات تلگرام', en: 'Telegram Bot' },
    aggressiveTl: { fa: 'هشدار مکرر', en: 'Aggressive Alerts' },
    aggressiveSub: { fa: 'تکرار هشدار تا زمان مشاهده', en: 'Repeat until acknowledged' },
    silent: { fa: 'حالت بی‌صدا', en: 'Silent Mode' },
    silentSub: { fa: 'عدم پخش صدا برای هشدارها', en: 'No sounds for alerts' },
    contact: { fa: 'تماس با ما', en: 'Contact Us' },
    privacy: { fa: 'حریم خصوصی', en: 'Privacy Policy' },
    sendCode: { fa: 'ارسال کد', en: 'Send code' },
    confirm: { fa: 'تایید', en: 'Confirm' },
    phonePlaceholder: { fa: '+989121234567', en: '+989121234567' },
    emailPlaceholder: { fa: 'name@example.com', en: 'name@example.com' },
    otpPlaceholder: { fa: 'کد تایید', en: 'Verification code' },
    telegramPlaceholder: { fa: '@username', en: '@username' },
    telegramHelp: { fa: 'ربات را start کنید؛ سپس کد تایید برای شما ارسال می‌شود.', en: 'Start the bot, then request a verification code.' },
    telegramLinkHelp: { fa: 'ربات را باز کنید و دکمه شروع را بزنید. این صفحه خودکار بررسی می‌شود.', en: 'Open the bot and press Start. This page will check automatically.' },
    openTelegram: { fa: 'باز کردن ربات', en: 'Open bot' },
    telegramOpenFailed: { fa: 'باز کردن ربات ممکن نشد. دوباره تلاش کنید.', en: 'The bot could not be opened. Try again.' },
    verified: { fa: 'تایید شده', en: 'Verified' },
    pending: { fa: 'در انتظار تایید', en: 'Pending verification' },
    saved: { fa: 'ذخیره شد', en: 'Saved' },
    unavailable: { fa: 'در دسترس نیست', en: 'Unavailable' },
  };

  useEffect(() => {
    api.notifications.preferences().then((value) => {
      setPrefs(value);
      setTelegramId(value.telegram_id ?? '');
    }).catch((error) => toast.error(error instanceof Error ? error.message : 'Failed to load settings'));
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

  const headingCls = `mb-4 flex items-center gap-2 text-xl font-bold tracking-tight ${isDark ? 'text-white' : 'text-[#3B2E13]'}`;
  const cardCls = `divide-y ${isDark ? 'divide-white/5 border-white/5 bg-[#0E0E0E]/70' : 'divide-black/5 border-black/5 bg-white/80'} backdrop-blur-md rounded-2xl`;
  const rowCls = 'flex items-center justify-between gap-4 p-5';
  const iconWrap = (tone: string) => `flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${tone}`;

  const saveBasic = async (key: 'push_app' | 'silent_mode' | 'aggressive_alerts', enabled: boolean) => {
    setPrefs((prev) => ({ ...prev, [key]: enabled }));
    try {
      setPrefs(await api.notifications.setBasic(key, enabled));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save');
    }
  };

  const toggleOtpChannel = async (channel: 'sms' | 'email', checked: boolean) => {
    if (!checked) {
      setPrefs(await api.notifications.disable(channel));
      return;
    }
    setOtpPanel(channel);
    setOtpDestination(channel === 'sms' ? (prefs.sms_phone ?? '+98') : (prefs.email_address ?? ''));
    setOtpCode('');
    setOtpSent(false);
  };

  const sendOtp = async (channel: 'sms' | 'email') => {
    setIsSaving(true);
    try {
      const result = await api.notifications.startOtp(channel, otpDestination);
      setOtpDestination(result.destination);
      setOtpSent(true);
      toast.success(t.sendCode[language]);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to send code');
    } finally {
      setIsSaving(false);
    }
  };

  const confirmOtp = async (channel: 'sms' | 'email') => {
    setIsSaving(true);
    try {
      setPrefs(await api.notifications.confirmOtp(channel, otpDestination, otpCode));
      setOtpPanel(null);
      toast.success(t.verified[language]);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to confirm');
    } finally {
      setIsSaving(false);
    }
  };

  const enableTelegram = async (checked: boolean) => {
    if (!checked) {
      setPrefs(await api.notifications.disable('telegram'));
      setTelegramCodeSent(false);
      setTelegramCode('');
      setTelegramLink(null);
      return;
    }
    if (prefs.telegram_deeplink_available) {
      setIsSaving(true);
      try {
        setTelegramLink(await api.notifications.createTelegramDeepLink());
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'Failed to create Telegram link');
      } finally {
        setIsSaving(false);
      }
      return;
    }
    if (!telegramId.trim() && !prefs.telegram_id) {
      setTelegramId('@');
      return;
    }
    setIsSaving(true);
    try {
      setPrefs(await api.notifications.setTelegram(telegramId || prefs.telegram_id || ''));
      setTelegramCodeSent(true);
      toast.success(t.sendCode[language]);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save');
    } finally {
      setIsSaving(false);
    }
  };

  const openTelegramLink = () => {
    if (!telegramLink) return;
    const opened = window.open(telegramLink.url, '_blank', 'noopener,noreferrer');
    if (!opened) toast.error(t.telegramOpenFailed[language]);
  };

  const confirmTelegram = async () => {
    setIsSaving(true);
    try {
      setPrefs(await api.notifications.confirmTelegram(telegramCode.trim()));
      setTelegramCodeSent(false);
      setTelegramCode('');
      toast.success(t.verified[language]);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to confirm');
    } finally {
      setIsSaving(false);
    }
  };

  const otpFields = (channel: 'sms' | 'email') => (
    <AnimatePresence>
      {otpPanel === channel && (
        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
          <div className="grid gap-3 px-5 pb-5 sm:grid-cols-[1fr_140px]">
            <Input dir="ltr" value={otpDestination} onChange={(event: React.ChangeEvent<HTMLInputElement>) => setOtpDestination(event.target.value)} placeholder={channel === 'sms' ? t.phonePlaceholder[language] : t.emailPlaceholder[language]} />
            <Button disabled={isSaving || !otpDestination.trim()} onClick={() => sendOtp(channel)} className="bg-[#D4AF37] text-black">{t.sendCode[language]}</Button>
            {otpSent && (
              <>
                <Input dir="ltr" value={otpCode} onChange={(event: React.ChangeEvent<HTMLInputElement>) => setOtpCode(event.target.value)} placeholder={t.otpPlaceholder[language]} className="tracking-[0.3em]" />
                <Button disabled={isSaving || !otpCode.trim()} onClick={() => confirmOtp(channel)} className="bg-emerald-500 text-white">{t.confirm[language]}</Button>
              </>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );

  return (
    <div className="mx-auto max-w-4xl space-y-8 pb-10">
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <h2 className={headingCls}><Activity className="text-[#D4AF37]" size={22} />{t.general[language]}</h2>
        <Card className={cardCls}>
          <div className={rowCls}>
            <div className="flex items-center gap-4">
              <div className={iconWrap(isDark ? 'bg-[#D4AF37]/10 text-[#D4AF37]' : 'bg-[#D4AF37]/15 text-[#8A6A20]')}>{isDark ? <Moon size={20} /> : <Sun size={20} />}</div>
              <div><div className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.darkTheme[language]}</div><div className={`text-sm ${isDark ? 'text-[#5A4E35]' : 'text-[#A8883A]'}`}>{t.darkThemeSub[language]}</div></div>
            </div>
            <Switch checked={isDark} onCheckedChange={toggleTheme} />
          </div>
          <div className={rowCls}>
            <div className="flex items-center gap-4">
              <div className={iconWrap(isDark ? 'bg-[#D4AF37]/10 text-[#D4AF37]' : 'bg-[#D4AF37]/15 text-[#8A6A20]')}><Languages size={20} /></div>
              <span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.languageSet[language]}</span>
            </div>
            <button onClick={toggleLanguage} className={`rounded-xl px-4 py-2 text-sm font-bold transition-colors ${isDark ? 'bg-[#D4AF37]/10 text-[#D4AF37]' : 'bg-[#D4AF37]/15 text-[#8A6A20]'}`}>{language === 'fa' ? 'English' : 'فارسی'}</button>
          </div>
        </Card>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}>
        <h2 className={headingCls}><Bell className="text-[#D4AF37]" size={22} />{t.notifications[language]}</h2>
        <Card className={cardCls}>
          <div className={rowCls}>
            <div className="flex items-center gap-4"><div className={iconWrap('bg-[#D4AF37]/10 text-[#D4AF37]')}><Bell size={20} /></div><span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.pushApp[language]}</span></div>
            <Switch disabled={!prefs.push_available} checked={prefs.push_available && prefs.push_app} onCheckedChange={(value: boolean) => saveBasic('push_app', value)} />
          </div>
          <div>
            <div className={rowCls}>
              <div className="flex items-center gap-4"><div className={iconWrap('bg-emerald-500/10 text-emerald-400')}><Smartphone size={20} /></div><div><span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.sms[language]}</span>{prefs.sms_verified && <span className="ms-2 inline-flex items-center gap-1 text-xs text-emerald-400"><CheckCircle2 size={13} />{t.verified[language]}</span>}{!prefs.sms_available && <span className="ms-2 text-xs text-slate-500">{t.unavailable[language]}</span>}</div></div>
              <Switch disabled={!prefs.sms_available} checked={prefs.sms_enabled && prefs.sms_verified} onCheckedChange={(value: boolean) => toggleOtpChannel('sms', value)} />
            </div>
            {otpFields('sms')}
          </div>
          <div>
            <div className={rowCls}>
              <div className="flex items-center gap-4"><div className={iconWrap('bg-purple-500/10 text-purple-400')}><Mail size={20} /></div><div><span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.email[language]}</span>{prefs.email_verified && <span className="ms-2 inline-flex items-center gap-1 text-xs text-emerald-400"><CheckCircle2 size={13} />{t.verified[language]}</span>}{!prefs.email_available && <span className="ms-2 text-xs text-slate-500">{t.unavailable[language]}</span>}</div></div>
              <Switch disabled={!prefs.email_available} checked={prefs.email_enabled && prefs.email_verified} onCheckedChange={(value: boolean) => toggleOtpChannel('email', value)} />
            </div>
            {otpFields('email')}
          </div>
          <div>
            <div className={rowCls}>
              <div className="flex min-w-0 flex-1 items-center gap-4"><div className={iconWrap('bg-sky-500/10 text-sky-400')}><Send size={20} /></div><div className="min-w-0 flex-1"><span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.telegram[language]}</span><p className={`mt-1 text-xs ${isDark ? 'text-[#8C7A52]' : 'text-[#8A6A25]'}`}>{prefs.telegram_verified ? t.verified[language] : telegramLink || telegramCodeSent ? t.pending[language] : prefs.telegram_deeplink_available ? t.telegramLinkHelp[language] : t.telegramHelp[language]}</p></div></div>
              <Switch disabled={!prefs.telegram_available || isSaving} checked={(prefs.telegram_enabled && prefs.telegram_verified) || Boolean(telegramLink)} onCheckedChange={enableTelegram} />
            </div>
            <AnimatePresence>
              {telegramLink && !prefs.telegram_verified && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                  <div className="flex flex-col gap-3 px-5 pb-5 sm:flex-row sm:items-center sm:justify-between" aria-live="polite">
                    <p className={`text-sm ${isDark ? 'text-[#8C7A52]' : 'text-[#8A6A25]'}`}>{t.telegramLinkHelp[language]}</p>
                    <Button onClick={openTelegramLink} className="shrink-0 bg-[#D4AF37] text-black">{t.openTelegram[language]}</Button>
                  </div>
                </motion.div>
              )}
              {!prefs.telegram_deeplink_available && (!prefs.telegram_enabled && (telegramId || telegramCodeSent)) && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                  <div className="grid gap-3 px-5 pb-5 sm:grid-cols-[1fr_140px]">
                    <Input disabled={!prefs.telegram_available || telegramCodeSent} dir="ltr" value={telegramId} onChange={(event: React.ChangeEvent<HTMLInputElement>) => setTelegramId(event.target.value)} placeholder={t.telegramPlaceholder[language]} />
                    <Button disabled={isSaving || !prefs.telegram_available || telegramCodeSent || !telegramId.trim()} onClick={() => enableTelegram(true)} className="bg-[#D4AF37] text-black">{t.sendCode[language]}</Button>
                    {telegramCodeSent && (
                      <>
                        <Input dir="ltr" value={telegramCode} onChange={(event: React.ChangeEvent<HTMLInputElement>) => setTelegramCode(event.target.value)} placeholder={t.otpPlaceholder[language]} className="tracking-[0.3em]" />
                        <Button disabled={isSaving || !/^\d{6}$/.test(telegramCode)} onClick={confirmTelegram} className="bg-emerald-500 text-white">{t.confirm[language]}</Button>
                      </>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </Card>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.16 }}>
        <h2 className={headingCls}><Activity className="text-[#D4AF37]" size={22} />{t.behavior[language]}</h2>
        <Card className={cardCls}>
          <div className={rowCls}>
            <div className="flex items-center gap-4"><div className={iconWrap('bg-slate-500/10 text-slate-400')}><VolumeX size={20} /></div><div><span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.silent[language]}</span><div className={`text-sm ${isDark ? 'text-[#5A4E35]' : 'text-[#A8883A]'}`}>{t.silentSub[language]}</div></div></div>
            <Switch checked={prefs.silent_mode} onCheckedChange={(value: boolean) => saveBasic('silent_mode', value)} />
          </div>
          <div className={rowCls}>
            <div className="flex items-center gap-4"><div className={iconWrap('bg-orange-500/10 text-orange-400')}><Repeat size={20} /></div><div><span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.aggressiveTl[language]}</span><div className={`text-sm ${isDark ? 'text-[#5A4E35]' : 'text-[#A8883A]'}`}>{t.aggressiveSub[language]}</div></div></div>
            <Switch checked={prefs.aggressive_alerts} onCheckedChange={(value: boolean) => saveBasic('aggressive_alerts', value)} />
          </div>
        </Card>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.24 }}>
        <h2 className={headingCls}><LifeBuoy className="text-[#D4AF37]" size={22} />{t.support[language]}</h2>
        <Card className={cardCls}>
          <button onClick={() => navigate('/support')} className={`flex w-full items-center gap-4 p-5 text-start transition-colors ${isDark ? 'hover:bg-white/3' : 'hover:bg-[#D4AF37]/5'}`}><div className={iconWrap('bg-[#D4AF37]/10 text-[#D4AF37]')}><LifeBuoy size={20} /></div><span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.contact[language]}</span></button>
          <button onClick={() => navigate('/privacy')} className={`flex w-full items-center gap-4 p-5 text-start transition-colors ${isDark ? 'hover:bg-white/3' : 'hover:bg-[#D4AF37]/5'}`}><div className={iconWrap('bg-[#D4AF37]/10 text-[#D4AF37]')}><ShieldCheck size={20} /></div><span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.privacy[language]}</span></button>
        </Card>
      </motion.div>
    </div>
  );
}
