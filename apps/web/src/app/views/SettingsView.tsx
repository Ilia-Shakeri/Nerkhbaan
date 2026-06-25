import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'motion/react';
import { Moon, Sun, Languages, Bell, Smartphone, Mail, Send, Activity, ShieldCheck, LifeBuoy, VolumeX, Repeat } from 'lucide-react';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { Switch } from '@nerkhbaan/ui/app/components/ui/switch';
import { useAppContext } from '../context/AppContext';

const PREFS_KEY = 'nerkhbaan_notification_prefs';

type NotifPrefs = {
  pushApp: boolean;
  sms: boolean;
  email: boolean;
  telegram: boolean;
  silentMode: boolean;
  aggressiveAlerts: boolean;
};

const DEFAULT_PREFS: NotifPrefs = {
  pushApp: true,
  sms: false,
  email: false,
  telegram: false,
  silentMode: false,
  aggressiveAlerts: false,
};

function loadPrefs(): NotifPrefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) return { ...DEFAULT_PREFS, ...JSON.parse(raw) };
  } catch { /* ignore parse errors */ }
  return { ...DEFAULT_PREFS };
}

export function SettingsView() {
  const navigate = useNavigate();
  const { language, theme, toggleTheme, toggleLanguage } = useAppContext();
  const isDark = theme === 'dark';

  const [prefs, setPrefs] = useState<NotifPrefs>(loadPrefs);

  useEffect(() => {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  }, [prefs]);

  const setPref = (key: keyof NotifPrefs) => (value: boolean) => {
    setPrefs((prev) => ({ ...prev, [key]: value }));
  };

  const t = {
    general:      { fa: 'عمومی',                    en: 'General'               },
    notifications:{ fa: 'اطلاع‌رسانی',              en: 'Notifications'         },
    behavior:     { fa: 'رفتار برنامه',              en: 'Behavior'              },
    support:      { fa: 'پشتیبانی',                 en: 'Support'               },
    darkTheme:    { fa: 'حالت تاریک',               en: 'Dark Theme'            },
    darkThemeSub: { fa: 'تغییر ظاهر برنامه به حالت شب', en: 'Switch to night appearance' },
    languageSet:  { fa: 'زبان برنامه',              en: 'App Language'          },
    langSub:      { fa: 'فارسی / English',           en: 'فارسی / English'       },
    pushApp:      { fa: 'اعلان درون‌برنامه‌ای',      en: 'In-App Notifications'  },
    sms:          { fa: 'پیامک (SMS)',               en: 'SMS Notifications'     },
    email:        { fa: 'ایمیل',                    en: 'Email Notifications'   },
    telegram:     { fa: 'ربات تلگرام',              en: 'Telegram Bot'          },
    aggressiveTl: { fa: 'حالت هشدار مکرر',          en: 'Aggressive Alerts'     },
    aggressiveSub:{ fa: 'تکرار هشدار تا زمان مشاهده', en: 'Repeat until acknowledged' },
    silent:       { fa: 'حالت بی‌صدا',              en: 'Silent Mode'           },
    silentSub:    { fa: 'عدم پخش صدا برای هشدارها', en: 'No sounds for alerts'  },
    contact:      { fa: 'تماس با ما',               en: 'Contact Us'            },
    privacy:      { fa: 'حریم خصوصی',              en: 'Privacy Policy'        },
  };

  const headingCls = `mb-4 flex items-center gap-2 text-xl font-bold tracking-tight ${isDark ? 'text-white' : 'text-[#3B2E13]'}`;
  const cardCls = `divide-y ${isDark ? 'divide-white/5 border-white/5 bg-[#0E0E0E]/70' : 'divide-black/5 border-black/5 bg-white/80'} backdrop-blur-md rounded-2xl`;
  const rowCls = 'flex items-center justify-between p-5';
  const iconWrapCls = (color: string) =>
    `flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${isDark ? `${color}/10` : `${color}/15`}`;

  return (
    <div className="mx-auto max-w-4xl space-y-8 pb-10">

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <h2 className={headingCls}>
          <Activity className="text-[#D4AF37]" size={22} />
          {t.general[language]}
        </h2>
        <Card className={cardCls}>
          <div className={rowCls}>
            <div className="flex items-center gap-4">
              <div className={`${iconWrapCls('bg-[#D4AF37]')} text-[#D4AF37]`}>
                {isDark ? <Moon size={20} /> : <Sun size={20} />}
              </div>
              <div className="flex flex-col">
                <span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.darkTheme[language]}</span>
                <span className={`text-sm ${isDark ? 'text-[#5A4E35]' : 'text-[#A8883A]'}`}>{t.darkThemeSub[language]}</span>
              </div>
            </div>
            <Switch checked={isDark} onCheckedChange={toggleTheme} />
          </div>

          <div className={rowCls}>
            <div className="flex items-center gap-4">
              <div className={`${iconWrapCls('bg-[#D4AF37]')} text-[#D4AF37]`}>
                <Languages size={20} />
              </div>
              <div className="flex flex-col">
                <span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.languageSet[language]}</span>
                <span className={`text-sm ${isDark ? 'text-[#5A4E35]' : 'text-[#A8883A]'}`}>{t.langSub[language]}</span>
              </div>
            </div>
            <button
              onClick={toggleLanguage}
              className={`rounded-xl px-4 py-2 text-sm font-bold transition-colors ${isDark ? 'bg-[#D4AF37]/10 text-[#D4AF37] hover:bg-[#D4AF37]/20' : 'bg-[#D4AF37]/15 text-[#8A6A20] hover:bg-[#D4AF37]/25'}`}
            >
              {language === 'fa' ? 'English' : 'فارسی'}
            </button>
          </div>
        </Card>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}>
        <h2 className={headingCls}>
          <Bell className="text-[#D4AF37]" size={22} />
          {t.notifications[language]}
        </h2>
        <Card className={cardCls}>
          {([
            { key: 'pushApp',   icon: <Bell size={20} />,        color: 'bg-[#D4AF37]', iconColor: 'text-[#D4AF37]',   label: t.pushApp   },
            { key: 'sms',       icon: <Smartphone size={20} />,  color: 'bg-emerald-500', iconColor: 'text-emerald-400', label: t.sms       },
            { key: 'email',     icon: <Mail size={20} />,        color: 'bg-purple-500', iconColor: 'text-purple-400',  label: t.email     },
            { key: 'telegram',  icon: <Send size={20} />,        color: 'bg-sky-500',    iconColor: 'text-sky-400',     label: t.telegram  },
          ] as const).map(({ key, icon, color, iconColor, label }) => (
            <div key={key} className={rowCls}>
              <div className="flex items-center gap-4">
                <div className={`${iconWrapCls(color)} ${iconColor}`}>{icon}</div>
                <span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{label[language]}</span>
              </div>
              <Switch checked={prefs[key as keyof NotifPrefs] as boolean} onCheckedChange={setPref(key as keyof NotifPrefs)} />
            </div>
          ))}
        </Card>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.16 }}>
        <h2 className={headingCls}>
          <Activity className="text-[#D4AF37]" size={22} />
          {t.behavior[language]}
        </h2>
        <Card className={cardCls}>
          <div className={rowCls}>
            <div className="flex items-center gap-4">
              <div className={`${iconWrapCls('bg-slate-500')} ${isDark ? 'text-slate-400' : 'text-slate-600'}`}><VolumeX size={20} /></div>
              <div className="flex flex-col">
                <span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.silent[language]}</span>
                <span className={`text-sm ${isDark ? 'text-[#5A4E35]' : 'text-[#A8883A]'}`}>{t.silentSub[language]}</span>
              </div>
            </div>
            <Switch checked={prefs.silentMode} onCheckedChange={setPref('silentMode')} />
          </div>
          <div className={rowCls}>
            <div className="flex items-center gap-4">
              <div className={`${iconWrapCls('bg-orange-500')} ${isDark ? 'text-orange-400' : 'text-orange-600'}`}><Repeat size={20} /></div>
              <div className="flex flex-col">
                <span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.aggressiveTl[language]}</span>
                <span className={`text-sm ${isDark ? 'text-[#5A4E35]' : 'text-[#A8883A]'}`}>{t.aggressiveSub[language]}</span>
              </div>
            </div>
            <Switch checked={prefs.aggressiveAlerts} onCheckedChange={setPref('aggressiveAlerts')} />
          </div>
        </Card>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.24 }}>
        <h2 className={headingCls}>
          <LifeBuoy className="text-[#D4AF37]" size={22} />
          {t.support[language]}
        </h2>
        <Card className={cardCls}>
          <button
            onClick={() => navigate('/contact')}
            className={`flex w-full items-center gap-4 p-5 text-start transition-colors rounded-t-2xl ${isDark ? 'hover:bg-white/3' : 'hover:bg-[#D4AF37]/5'}`}
          >
            <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-[#D4AF37]/10 text-[#D4AF37]' : 'bg-[#D4AF37]/15 text-[#8A6A20]'}`}>
              <LifeBuoy size={20} />
            </div>
            <span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.contact[language]}</span>
          </button>
          <button
            onClick={() => navigate('/privacy')}
            className={`flex w-full items-center gap-4 p-5 text-start transition-colors rounded-b-2xl ${isDark ? 'hover:bg-white/3' : 'hover:bg-[#D4AF37]/5'}`}
          >
            <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-[#D4AF37]/10 text-[#D4AF37]' : 'bg-[#D4AF37]/15 text-[#8A6A20]'}`}>
              <ShieldCheck size={20} />
            </div>
            <span className={`font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{t.privacy[language]}</span>
          </button>
        </Card>
      </motion.div>

    </div>
  );
}
